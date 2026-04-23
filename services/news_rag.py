"""RAG + CAG health-news pipeline with Filter Agent, Trend Detection & Writer-Critic loop.

Architecture
------------

  OFFLINE (ingest, every 6h):
    Articles (up to 60) ──► Filter Agent (relevance + novelty ≥ 0.4) ──► filtered set
    filtered set ──► CAG preprocessing (Groq) ──► KV cache JSON
    filtered set ──► HuggingFace embeddings ──► Qdrant
    filtered set ──► Trend Detection (Groq) ──► trends cache JSON

  QUERY TIME:
    Query ──► Qdrant retrieval ──► top-5 chunks
    Writer  (Groq key 1) ──► draft answer
    Critic  (Groq key 2) ──► score 0-10 + feedback
    If score < 7 and iterations < 2 ──► Writer rewrites
    Return final answer + sources

Public API
----------
ingest_news_articles(force, api_key) -> int
query_news(question, api_key) -> dict
get_ingestion_status() -> dict
get_trends() -> list[dict]
"""
from __future__ import annotations

import json
import logging
import os
from typing import TypedDict

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_ROOT          = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
_DATA_DIR      = os.path.join(_ROOT, "data")
_QDRANT_PATH   = os.path.join(_DATA_DIR, "qdrant_news")
_KV_CACHE_PATH = os.path.join(_DATA_DIR, "news_kv_cache.json")
_TRENDS_PATH   = os.path.join(_DATA_DIR, "news_trends_cache.json")
_COLLECTION    = "health_news"

# ── Model config ───────────────────────────────────────────────────────────────
_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
_GROQ_MODEL  = "llama-3.3-70b-versatile"

# ── Lazy singletons ────────────────────────────────────────────────────────────
_qdrant_client = None
_index         = None


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _get_client():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        os.makedirs(_QDRANT_PATH, exist_ok=True)
        _qdrant_client = QdrantClient(path=_QDRANT_PATH)
    return _qdrant_client


def _get_embed_model():
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    return HuggingFaceEmbedding(model_name=_EMBED_MODEL)


def _collection_has_points() -> bool:
    try:
        client = _get_client()
        names = [c.name for c in client.get_collections().collections]
        if _COLLECTION not in names:
            return False
        return client.count(_COLLECTION).count > 0
    except Exception:
        return False


def _groq_call(client, prompt: str, max_tokens: int = 600,
               json_mode: bool = False, temperature: float = 0) -> str:
    """Single Groq completion call; returns raw content string."""
    kwargs = dict(
        model=_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def _get_all_groq_clients(primary_key: str) -> list:
    """Return a list of Groq clients for all available keys (primary first)."""
    from groq import Groq
    seen = set()
    clients = []
    for key in [
        primary_key,
        os.environ.get("GROQ_API_KEY",   ""),
        os.environ.get("GROQ_API_KEY_2", ""),
        os.environ.get("GROQ_API_KEY_3", ""),
    ]:
        k = (key or "").strip()
        if k and k not in seen:
            seen.add(k)
            clients.append(Groq(api_key=k))
    return clients


def _make_groq_clients(primary_key: str):
    """Return (primary_client, first_fallback | None) for backwards compat."""
    clients = _get_all_groq_clients(primary_key)
    primary  = clients[0]
    fallback = clients[1] if len(clients) > 1 else None
    return primary, fallback


def _call_lightning_ai(prompt: str, max_tokens: int = 600,
                       json_mode: bool = False) -> str:
    """Call Lightning AI (litai) as the last-resort fallback."""
    key = os.environ.get("LIGHTNING_API_KEY", "").strip()
    if not key:
        raise RuntimeError("LIGHTNING_API_KEY not set")
    from litai import LLM
    llm = LLM(model="lightning-ai/llama-3.3-70b", api_key=key)
    if json_mode:
        prompt = prompt + "\n\nIMPORTANT: respond with ONLY a valid JSON object, no markdown fences."
    return llm.chat(prompt)


def _call_with_fallback(primary, fallback, prompt: str,
                        max_tokens: int = 600,
                        json_mode: bool = False,
                        temperature: float = 0) -> str:
    """Try all Groq keys in order; if all rate-limited fall back to Lightning AI."""
    # Build full pool from env every call so we always have all 3 keys
    all_clients = _get_all_groq_clients(
        os.environ.get("GROQ_API_KEY", "").strip()
    )
    # Put the explicitly passed primary first
    clients = [primary] + [c for c in all_clients if c.api_key != primary.api_key]

    last_exc = None
    for i, client in enumerate(clients):
        try:
            return _groq_call(client, prompt, max_tokens, json_mode, temperature)
        except Exception as e:
            err = str(e)
            should_rotate = ("429" in err or "rate_limit" in err.lower()
                             or "401" in err or "invalid_api_key" in err.lower())
            if should_rotate:
                logger.debug(f"[news_rag] Groq key {i+1} failed ({err[:60]})"
                             + (f" — trying key {i+2}" if i < len(clients) - 1
                                else " — falling back to Lightning AI"))
                last_exc = e
                continue
            raise

    # All Groq keys exhausted — try Lightning AI
    try:
        logger.info("[news_rag] All Groq keys rate-limited — using Lightning AI fallback")
        return _call_lightning_ai(prompt, max_tokens, json_mode)
    except Exception as e:
        logger.error(f"[news_rag] Lightning AI fallback also failed: {e}")
        raise last_exc


# ══════════════════════════════════════════════════════════════════════════════
# 1. Filter Agent — relevance + novelty scoring
# ══════════════════════════════════════════════════════════════════════════════

_FILTER_PROMPT = """\
You are a relevance filter for a health and longevity research knowledge base.
Score each article on two dimensions (0.0 to 1.0):
  relevance: how relevant is this to health, longevity, supplements, aging, nutrition, fitness, biomarkers, or clinical research?
  novelty:   how novel and substantive is this? (0 = generic lifestyle tip, 1 = specific research finding)

Return ONLY a JSON array with one entry per article, same order as input:
[{{"id": 0, "relevance": 0.8, "novelty": 0.6}}, ...]

Articles:
{articles_json}"""


def _filter_articles(articles: list[dict], primary, fallback,
                     min_score: float = 0.4) -> list[dict]:
    """Score articles for relevance + novelty; keep those above min_score.

    Batches up to 8 articles per LLM call to minimise token usage.
    Articles that fail scoring are kept conservatively.
    """
    if not articles:
        return []

    batch_size = 8
    kept: list[dict] = []
    total = len(articles)

    for batch_start in range(0, total, batch_size):
        batch = articles[batch_start: batch_start + batch_size]
        batch_info = json.dumps([
            {"id": i, "title": a.get("title", ""), "source": a.get("source", ""),
             "summary": (a.get("summary", "") or "")[:200]}
            for i, a in enumerate(batch)
        ], ensure_ascii=False)

        prompt = _FILTER_PROMPT.format(articles_json=batch_info)
        try:
            raw = _call_with_fallback(primary, fallback, prompt,
                                      max_tokens=300, json_mode=False)
            # Strip markdown fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            scores: list[dict] = json.loads(raw)
            score_map = {s["id"]: s for s in scores}
        except Exception as e:
            logger.warning(f"[news_rag/filter] Batch scoring failed: {e} — keeping all")
            kept.extend(batch)
            continue

        for i, article in enumerate(batch):
            entry  = score_map.get(i, {})
            rel    = float(entry.get("relevance", 0.5))
            nov    = float(entry.get("novelty",   0.5))
            avg    = (rel + nov) / 2
            article["_filter_relevance"] = round(rel, 2)
            article["_filter_novelty"]   = round(nov, 2)
            if avg >= min_score:
                kept.append(article)
            else:
                logger.debug(f"[news_rag/filter] DROPPED (rel={rel:.2f} nov={nov:.2f}): "
                             f"{article.get('title', '')[:60]}")

    logger.info(f"[news_rag/filter] {len(kept)}/{total} articles passed filter "
                f"(threshold={min_score})")
    return kept


# ══════════════════════════════════════════════════════════════════════════════
# 2. CAG — LLM preprocessing → KV cache
# ══════════════════════════════════════════════════════════════════════════════

_PREPROCESS_PROMPT = """\
You are preprocessing a health/longevity article for a knowledge cache.
Extract and return ONLY a JSON object with these exact keys:

{{
  "main_finding": "one-sentence summary of the key research finding",
  "evidence_level": "strong | moderate | preliminary | anecdotal",
  "supplements_or_interventions": ["list", "of", "specific", "items", "mentioned"],
  "key_statistics": "any quantitative findings — dosages, % improvements, study sizes (or null)",
  "applicability": "who this is most relevant for (e.g. 'adults over 50', 'athletes', 'general population')"
}}

Article title: {title}

Article text:
{text}

Respond with ONLY the JSON object. No explanation, no markdown fences."""


def _preprocess_articles_for_kv_cache(articles: list[dict],
                                       primary, fallback) -> list[dict]:
    """Run each article through Groq to extract structured key information."""
    cached: list[dict] = []
    for a in articles:
        title = a.get("title", "")
        text  = f"{title}\n\n{a.get('summary', '')}".strip()
        if len(text) < 30:
            continue

        prompt = _PREPROCESS_PROMPT.format(title=title, text=text[:1500])
        try:
            raw = _call_with_fallback(primary, fallback, prompt,
                                      max_tokens=400, json_mode=True)
            extracted = json.loads(raw or "{}")
        except Exception as e:
            logger.warning(f"[news_rag/CAG] preprocessing failed for '{title}': {e}")
            extracted = {}

        cached.append({
            "title":  title,
            "source": a.get("source", ""),
            "url":    a.get("url",    ""),
            "date":   a.get("date",   ""),
            **extracted,
        })
        logger.debug(f"[news_rag/CAG] preprocessed: {title[:60]}")

    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_KV_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cached, f, indent=2, ensure_ascii=False)

    logger.info(f"[news_rag/CAG] KV cache written: {len(cached)} articles → {_KV_CACHE_PATH}")
    return cached


def _load_kv_cache() -> list[dict]:
    if not os.path.exists(_KV_CACHE_PATH):
        return []
    try:
        with open(_KV_CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _format_kv_cache_context(cache: list[dict]) -> str:
    if not cache:
        return "(no preprocessed knowledge cache available)"

    lines = ["=== PREPROCESSED KNOWLEDGE CACHE (all articles, LLM-structured) ===\n"]
    for i, entry in enumerate(cache, 1):
        lines.append(f"[Article {i}] {entry.get('title', 'Untitled')} — {entry.get('source', '')}")
        if entry.get("main_finding"):
            lines.append(f"  Finding: {entry['main_finding']}")
        if entry.get("evidence_level"):
            lines.append(f"  Evidence: {entry['evidence_level']}")
        if entry.get("supplements_or_interventions"):
            items = entry["supplements_or_interventions"]
            if isinstance(items, list):
                lines.append(f"  Interventions: {', '.join(items)}")
        if entry.get("key_statistics"):
            lines.append(f"  Stats: {entry['key_statistics']}")
        if entry.get("applicability"):
            lines.append(f"  Applies to: {entry['applicability']}")
        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# 3. Trend Detection
# ══════════════════════════════════════════════════════════════════════════════

_TREND_PROMPT = """\
You are analyzing a set of health and longevity articles to detect emerging trends.
Identify 3 to 5 key trends across these articles. For each trend classify it as:
  Emergence   — a new topic appearing for the first time
  Acceleration — an existing topic gaining significant momentum
  Disruption  — a new approach replacing an established method

Return ONLY a JSON array:
[{{
  "topic": "short trend name (3-6 words)",
  "type": "Emergence|Acceleration|Disruption",
  "summary": "1-2 sentences describing what is happening and why it matters",
  "article_indices": [0, 3, 7]
}}]

Articles (title + source):
{articles_json}"""


def _detect_trends(articles: list[dict], primary, fallback) -> list[dict]:
    """Group filtered articles and identify 3-5 health/longevity trends."""
    if len(articles) < 3:
        return []

    articles_info = json.dumps([
        {"id": i, "title": a.get("title", ""), "source": a.get("source", "")}
        for i, a in enumerate(articles)
    ], ensure_ascii=False)

    prompt = _TREND_PROMPT.format(articles_json=articles_info)
    try:
        raw = _call_with_fallback(primary, fallback, prompt,
                                  max_tokens=800, json_mode=False)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        trends = json.loads(raw)
        logger.info(f"[news_rag/trends] Detected {len(trends)} trends")
        return trends
    except Exception as e:
        logger.warning(f"[news_rag/trends] Trend detection failed: {e}")
        return []


def _save_trends_cache(trends: list[dict]) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_TRENDS_PATH, "w", encoding="utf-8") as f:
        json.dump(trends, f, indent=2, ensure_ascii=False)


def _load_trends_cache() -> list[dict]:
    if not os.path.exists(_TRENDS_PATH):
        return []
    try:
        with open(_TRENDS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_trends() -> list[dict]:
    """Public API: return the most recently detected trends."""
    return _load_trends_cache()


# ══════════════════════════════════════════════════════════════════════════════
# Ingestion  (Filter → CAG → RAG → Trends)
# ══════════════════════════════════════════════════════════════════════════════

def ingest_news_articles(force: bool = False, api_key: str | None = None) -> int:
    """Fetch up to 60 articles, filter for relevance/novelty, then run all paths:

    1. Filter Agent — score + discard low-relevance/novelty articles
    2. CAG path     — preprocess with Groq LLM → KV cache JSON
    3. RAG path     — embed with HuggingFace → Qdrant
    4. Trend Detection — detect 3-5 trends → trends cache JSON
    """
    global _index

    _api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()

    if not force and _collection_has_points() and os.path.exists(_KV_CACHE_PATH):
        logger.info("[news_rag] Both RAG index and KV cache exist — skipping ingest")
        return _get_client().count(_COLLECTION).count

    # ── Fetch articles (wider net) ─────────────────────────────────────────────
    from services.body import fetch_health_news
    articles = fetch_health_news(max_items=60, force_refresh=force)
    if not articles:
        logger.warning("[news_rag] No articles returned — skipping ingest")
        return 0

    logger.info(f"[news_rag] Fetched {len(articles)} raw articles")

    # ── Build Groq clients ─────────────────────────────────────────────────────
    if _api_key:
        primary, fallback = _make_groq_clients(_api_key)
    else:
        primary = fallback = None

    # ── 1. Filter Agent ────────────────────────────────────────────────────────
    if primary:
        logger.info("[news_rag/filter] Scoring articles for relevance + novelty …")
        filtered = _filter_articles(articles, primary, fallback)
    else:
        logger.warning("[news_rag/filter] No API key — skipping filter, using all articles")
        filtered = articles

    if not filtered:
        logger.warning("[news_rag] All articles filtered out — using original set")
        filtered = articles

    # ── 2. CAG path: LLM preprocessing → KV cache ─────────────────────────────
    if primary:
        logger.info(f"[news_rag/CAG] Preprocessing {len(filtered)} articles …")
        _preprocess_articles_for_kv_cache(filtered, primary, fallback)
    else:
        logger.warning("[news_rag/CAG] No API key — skipping KV cache update")

    # ── 3. RAG path: embed → Qdrant ────────────────────────────────────────────
    from llama_index.core import Document, Settings, VectorStoreIndex, StorageContext
    from llama_index.vector_stores.qdrant import QdrantVectorStore

    docs: list[Document] = []
    for a in filtered:
        text = f"{a.get('title', '')}\n\n{a.get('summary', '')}".strip()
        if len(text) < 20:
            continue
        docs.append(Document(
            text=text,
            metadata={
                "title":  a.get("title",  ""),
                "source": a.get("source", ""),
                "url":    a.get("url",    ""),
                "date":   a.get("date",   ""),
            },
        ))

    if not docs:
        logger.warning("[news_rag/RAG] All filtered articles too short — nothing to embed")
        return 0

    Settings.embed_model = _get_embed_model()
    Settings.llm = None

    client          = _get_client()
    vector_store    = QdrantVectorStore(client=client, collection_name=_COLLECTION)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    _index = VectorStoreIndex.from_documents(
        docs, storage_context=storage_context, show_progress=False,
    )

    count = client.count(_COLLECTION).count
    logger.info(f"[news_rag/RAG] {len(docs)} articles → {count} chunks in Qdrant")

    # ── 4. Trend Detection ─────────────────────────────────────────────────────
    if primary:
        logger.info("[news_rag/trends] Detecting trends …")
        trends = _detect_trends(filtered, primary, fallback)
        _save_trends_cache(trends)

    return count


# ══════════════════════════════════════════════════════════════════════════════
# Writer-Critic loop (LangGraph)
# ══════════════════════════════════════════════════════════════════════════════

class _QueryState(TypedDict):
    question:         str
    context_str:      str
    kv_cache_section: str
    draft:            str
    critique:         str
    score:            float
    iterations:       int


_WRITER_PROMPT = """\
You are a health and longevity research assistant with access to two knowledge sources.

{kv_cache_section}

=== RETRIEVED CONTEXT (top matches for this specific question) ===

{context_str}

=== END OF SOURCES ===

Instructions:
- Use BOTH sources. Retrieved context gives the most relevant excerpts; the knowledge cache gives the broader structured picture.
- Answer using ONLY information present in the sources above. Do not invent facts.
- Be specific: cite dosages, study sizes, and statistics when available.
- After your answer, cite the articles you relied on (title + outlet).
{critique_section}
Question: {question}

Answer:"""

_CRITIC_PROMPT = """\
You are a strict quality reviewer for health research answers.
Review the answer below on 4 dimensions, each scored 0–10:
  1. Grounding     — are all claims traceable to the provided source context?
  2. Coherence     — is the answer well-structured and logically consistent?
  3. Completeness  — does it address all aspects of the question?
  4. Actionability — are the insights specific and practically useful?

Overall score = average of the 4 dimensions.

Source context available to the writer:
{context_str}

Question: {question}

Answer to review:
{draft}

Return ONLY a JSON object:
{{"score": 7.5, "grounding": 8, "coherence": 7, "completeness": 7, "actionability": 8,
  "feedback": "specific improvement instructions, or null if score >= 7"}}"""


def _build_writer_critic_graph(writer_client, critic_client):
    """Build and compile a LangGraph StateGraph for the writer-critic loop."""
    from langgraph.graph import StateGraph, END

    def writer_node(state: _QueryState) -> dict:
        critique_section = ""
        if state.get("critique"):
            critique_section = (
                f"\n\nPREVIOUS REVIEW — address these issues in your rewrite:\n"
                f"{state['critique']}\n"
            )
        prompt = _WRITER_PROMPT.format(
            kv_cache_section=state["kv_cache_section"],
            context_str=state["context_str"],
            critique_section=critique_section,
            question=state["question"],
        )
        try:
            draft = _call_with_fallback(writer_client, critic_client, prompt,
                                        max_tokens=1000, temperature=0.2)
        except Exception as e:
            logger.warning(f"[news_rag/writer] All providers failed: {e}")
            draft = f"Query failed: {e}"
        return {"draft": draft, "iterations": state.get("iterations", 0) + 1}

    def critic_node(state: _QueryState) -> dict:
        prompt = _CRITIC_PROMPT.format(
            context_str=state["context_str"],
            question=state["question"],
            draft=state["draft"],
        )
        try:
            raw = _call_with_fallback(critic_client, writer_client, prompt,
                                      max_tokens=300, json_mode=True, temperature=0)
            data = json.loads(raw or "{}")
            score    = float(data.get("score",    7.0))
            feedback = data.get("feedback") or ""
            logger.info(f"[news_rag/critic] Score: {score:.1f} | "
                        f"G={data.get('grounding','?')} Co={data.get('coherence','?')} "
                        f"Cp={data.get('completeness','?')} A={data.get('actionability','?')}")
        except Exception as e:
            logger.warning(f"[news_rag/critic] Scoring failed: {e} — approving draft")
            score, feedback = 7.0, ""
        return {"score": score, "critique": feedback}

    def should_rewrite(state: _QueryState) -> str:
        if state.get("score", 7.0) >= 7.0 or state.get("iterations", 0) >= 2:
            return "end"
        logger.info(f"[news_rag/critic] Score {state['score']:.1f} < 7 — requesting rewrite "
                    f"(iteration {state['iterations']})")
        return "rewrite"

    g = StateGraph(_QueryState)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", should_rewrite, {"end": END, "rewrite": "writer"})
    g.set_entry_point("writer")
    return g.compile()


# ══════════════════════════════════════════════════════════════════════════════
# Query  (RAG retrieval  →  Writer-Critic loop)
# ══════════════════════════════════════════════════════════════════════════════

def query_news(question: str, api_key: str) -> dict:
    """RAG + CAG query with Writer-Critic quality loop.

    Returns::

        {
            "answer":        "<final answer after critic approval>",
            "sources":       [{"title": ..., "source": ..., "url": ..., "score": ...}],
            "node_count":    5,
            "kv_cache_used": True,
            "critic_score":  8.2,
            "iterations":    1,
        }
    """
    global _index

    from llama_index.core import Settings, StorageContext, VectorStoreIndex
    from llama_index.vector_stores.qdrant import QdrantVectorStore

    # ── Load Qdrant index ──────────────────────────────────────────────────────
    if _index is None:
        if not _collection_has_points():
            return {
                "answer": (
                    "The news index is still loading — the background ingestion job "
                    "runs 60 seconds after server start. Please try again in a moment."
                ),
                "sources": [], "node_count": 0, "kv_cache_used": False,
                "critic_score": None, "iterations": 0,
            }
        Settings.embed_model = _get_embed_model()
        client       = _get_client()
        vector_store = QdrantVectorStore(client=client, collection_name=_COLLECTION)
        storage_ctx  = StorageContext.from_defaults(vector_store=vector_store)
        _index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_ctx)

    # ── Retrieve top-10 candidates, dedup by title → up to 5 unique articles ──
    Settings.embed_model = _get_embed_model()
    retriever = _index.as_retriever(similarity_top_k=10)
    try:
        nodes = retriever.retrieve(question)
    except Exception as e:
        return {"answer": f"Retrieval failed: {e}", "sources": [],
                "node_count": 0, "kv_cache_used": False,
                "critic_score": None, "iterations": 0}

    # Deduplicate nodes by title — LlamaIndex may chunk one article into several
    # nodes with the same title; keep only the highest-scoring one per title.
    seen_titles: set[str] = set()
    unique_nodes = []
    for n in sorted(nodes, key=lambda x: float(x.score or 0), reverse=True):
        title = (n.metadata or {}).get("title", "")
        if title not in seen_titles:
            seen_titles.add(title)
            unique_nodes.append(n)
        if len(unique_nodes) >= 5:
            break
    nodes = unique_nodes

    context_str = "\n\n---\n\n".join(
        f"[{(n.metadata or {}).get('source', '')}] {(n.metadata or {}).get('title', '')}\n{n.get_content()}"
        for n in nodes
    )
    sources = [
        {
            "title":  (n.metadata or {}).get("title",  ""),
            "source": (n.metadata or {}).get("source", ""),
            "url":    (n.metadata or {}).get("url",    ""),
            "score":  round(float(n.score or 0), 3),
            "text":   n.get_content(),
        }
        for n in nodes
    ]

    # ── Load KV cache (CAG) ────────────────────────────────────────────────────
    kv_cache      = _load_kv_cache()
    kv_section    = _format_kv_cache_context(kv_cache)
    kv_cache_used = len(kv_cache) > 0

    # ── Build Groq clients for writer + critic ─────────────────────────────────
    _active_key = api_key.strip() or os.environ.get("GROQ_API_KEY", "")
    all_clients = _get_all_groq_clients(_active_key)

    # Writer = key 1, Critic = key 2, key 3 is spare for fallback inside each
    writer_client = all_clients[0]
    critic_client = all_clients[1] if len(all_clients) > 1 else all_clients[0]

    # ── Writer-Critic loop ─────────────────────────────────────────────────────
    if critic_client.api_key != writer_client.api_key:
        # Two distinct keys → full writer-critic loop
        try:
            graph = _build_writer_critic_graph(writer_client, critic_client)
            result = graph.invoke({
                "question":         question,
                "context_str":      context_str,
                "kv_cache_section": kv_section,
                "draft":            "",
                "critique":         "",
                "score":            0.0,
                "iterations":       0,
            })
            answer      = result["draft"].strip()
            critic_score = result.get("score")
            iterations   = result.get("iterations", 1)
        except Exception as e:
            logger.warning(f"[news_rag] Writer-critic loop failed: {e} — falling back to single pass")
            answer      = _groq_call(writer_client,
                                     _WRITER_PROMPT.format(
                                         kv_cache_section=kv_section,
                                         context_str=context_str,
                                         critique_section="",
                                         question=question,
                                     ), max_tokens=1000, temperature=0.2)
            critic_score = None
            iterations   = 1
    else:
        # Single key only — skip critic to save tokens
        logger.info("[news_rag] Single Groq key — skipping critic")
        answer = _call_with_fallback(
            writer_client, writer_client,
            _WRITER_PROMPT.format(
                kv_cache_section=kv_section,
                context_str=context_str,
                critique_section="",
                question=question,
            ), max_tokens=1000, temperature=0.2)
        critic_score = None
        iterations   = 1

    return {
        "answer":        answer,
        "sources":       sources,
        "node_count":    len(sources),
        "kv_cache_used": kv_cache_used,
        "critic_score":  critic_score,
        "iterations":    iterations,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Status
# ══════════════════════════════════════════════════════════════════════════════

def get_ingestion_status() -> dict:
    """Return Qdrant + KV cache + trends statistics."""
    try:
        client = _get_client()
        names  = [c.name for c in client.get_collections().collections]
        chunks = 0
        if _COLLECTION in names:
            chunks = client.count(_COLLECTION).count
        kv_cache = _load_kv_cache()
        trends   = _load_trends_cache()
        return {
            "ready":          chunks > 0,
            "chunks":         chunks,
            "kv_cache_size":  len(kv_cache),
            "kv_cache_ready": len(kv_cache) > 0,
            "trends_count":   len(trends),
        }
    except Exception as e:
        return {"ready": False, "chunks": 0, "kv_cache_size": 0,
                "trends_count": 0, "error": str(e)}
