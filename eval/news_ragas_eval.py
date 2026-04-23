"""RAGAS evaluation of the health-news RAG pipeline.

Scores three metrics against a fixed set of health/longevity questions:
  - Faithfulness              : does the answer stay within the retrieved context?
  - Response Relevancy        : does the answer actually address the question?
  - Context Precision (no ref): are the top retrieved chunks relevant to the query?

Usage
-----
    # First run (populates cache + Qdrant, then evaluates)
    python -m eval.news_ragas_eval --groq-key gsk_xxx

    # Subsequent runs (Qdrant already populated, much faster)
    python -m eval.news_ragas_eval --groq-key gsk_xxx --out eval/results/

Output
------
    eval/results/news_ragas_<YYYY-MM-DD>.json
    Printed score table in terminal.

Architecture note
-----------------
RAGAS uses an LLM as the "judge" that scores each metric.  We pass it the same
Groq model used everywhere else in the project (llama-3.3-70b-versatile) via the
LangChain wrapper, so no additional API keys are needed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()  # load .env so OPENROUTER_API_KEY / GEMINI_API_KEY are available

# Force UTF-8 output on Windows so box-drawing characters don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── Sample evaluation questions ───────────────────────────────────────────────
# Cover a range of topics present in the ingested sources so retrieval can
# actually find relevant chunks.  Ground-truth answers are not required for
# the three metrics we use (faithfulness, relevancy, context precision without
# reference).

EVAL_QUESTIONS: list[str] = [
    "What are the latest findings on extending human healthspan or lifespan?",
    "What supplements or interventions are associated with slowing aging?",
    "How does diet or nutrition influence longevity according to recent research?",
    "What does current research say about sleep and healthy aging?",
    "What lifestyle habits are most associated with reduced disease risk?",
    "What are recent breakthroughs in aging biology or anti-aging treatments?",
    "How does exercise affect longevity biomarkers and healthspan?",
    "What does recent research reveal about gut health and longevity?",
    "What are the most promising longevity interventions being studied today?",
    "How do stress and mental health affect biological aging?",
]


# ══════════════════════════════════════════════════════════════════════════════
# Evaluation runner
# ══════════════════════════════════════════════════════════════════════════════

def run_eval(groq_key: str, out_dir: str = "eval/results") -> dict:
    """Run the full RAGAS evaluation and write results to *out_dir*.

    Returns the results dict (also written to JSON).
    """
    # ── Ensure index is populated ─────────────────────────────────────────────
    from services.news_rag import ingest_news_articles, query_news, get_ingestion_status

    status = get_ingestion_status()
    if not status["ready"]:
        print("[ragas eval] Qdrant index empty — ingesting articles first …")
        count = ingest_news_articles(force=False)
        print(f"[ragas eval] Ingested {count} chunks")
    else:
        print(f"[ragas eval] Qdrant ready ({status['chunks']} chunks) — skipping ingest")

    # ── Collect (question, answer, contexts) triples ──────────────────────────
    print(f"\n[ragas eval] Running {len(EVAL_QUESTIONS)} queries …\n")
    samples: list[dict] = []

    for i, q in enumerate(EVAL_QUESTIONS, 1):
        print(f"  [{i}/{len(EVAL_QUESTIONS)}] {q[:70]} …")
        result = query_news(q, groq_key)
        if result.get("node_count", 0) == 0:
            print("    ⚠  no chunks retrieved — skipping")
            continue
        samples.append({
            "question": q,
            "answer":   result["answer"],
            # Use actual chunk text for proper RAGAS evaluation.
            # Fall back to "title [source]" if text not available.
            "contexts": [
                s.get("text") or f"{s.get('title', '')} [{s.get('source', '')}]"
                for s in result["sources"]
            ],
        })

    if not samples:
        print("[ragas eval] No samples collected — cannot run RAGAS. Exiting.")
        return {}

    print(f"\n[ragas eval] Collected {len(samples)} samples — running RAGAS …\n")

    # ── RAGAS scoring ─────────────────────────────────────────────────────────
    scores: dict = {}
    try:
        import warnings
        import datasets as hf_datasets
        from ragas import evaluate
        from ragas.metrics._faithfulness import Faithfulness
        from ragas.metrics._answer_relevance import AnswerRelevancy
        from ragas.metrics._context_precision import LLMContextPrecisionWithoutReference
        from ragas.llms.base import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from langchain_community.embeddings import HuggingFaceEmbeddings as LCHFEmb

        # ── Judge LLM: Lightning AI (no daily token limit) ────────────────────
        # RAGAS requires a plain LangChain LLM with an accessible `temperature`
        # field — RunnableWithFallbacks doesn't expose this, causing ValueError.
        # We use a thin LangChain wrapper around litai.LLM instead.
        from langchain_core.language_models.chat_models import SimpleChatModel
        from langchain_core.messages import BaseMessage, AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        lightning_key = os.environ.get("LIGHTNING_API_KEY", "").strip()

        class _LightningChatModel(SimpleChatModel):
            """Minimal LangChain wrapper around litai.LLM for RAGAS judge."""
            temperature: float = 0.0

            def _call(self, messages: list[BaseMessage], stop=None, **kwargs) -> str:
                from litai import LLM
                llm = LLM(model="lightning-ai/llama-3.3-70b",
                          api_key=lightning_key)
                prompt = "\n".join(
                    f"{'Human' if m.type == 'human' else 'Assistant'}: {m.content}"
                    for m in messages
                )
                return llm.chat(prompt) or ""

            @property
            def _llm_type(self) -> str:
                return "lightning-ai"

        if lightning_key:
            judge_llm = LangchainLLMWrapper(_LightningChatModel())
            print("[ragas eval] Using Lightning AI (llama-3.3-70b) as judge")
        else:
            # Fallback: plain ChatGroq (no .with_fallbacks — RAGAS can't handle it)
            from langchain_groq import ChatGroq
            judge_llm = LangchainLLMWrapper(
                ChatGroq(api_key=groq_key, model="llama-3.3-70b-versatile", temperature=0)
            )
            print("[ragas eval] Using Groq as judge")

        judge_embeddings = LangchainEmbeddingsWrapper(
            LCHFEmb(model_name="BAAI/bge-small-en-v1.5")
        )

        faithfulness   = Faithfulness();                        faithfulness.llm   = judge_llm
        ans_relevancy  = AnswerRelevancy(strictness=1);         ans_relevancy.llm  = judge_llm; ans_relevancy.embeddings = judge_embeddings
        ctx_precision  = LLMContextPrecisionWithoutReference(); ctx_precision.llm  = judge_llm

        metrics = [faithfulness, ans_relevancy, ctx_precision]

        # evaluate() expects a HuggingFace Dataset with question/answer/contexts columns
        hf_data = hf_datasets.Dataset.from_list([
            {
                "question":  s["question"],
                "answer":    s["answer"],
                "contexts":  s["contexts"],
            }
            for s in samples
        ])

        result = evaluate(dataset=hf_data, metrics=metrics)
        scores_df = result.to_pandas()
        skip = {"question", "answer", "contexts", "ground_truth",
                "user_input", "retrieved_contexts", "response"}
        scores = {
            col: round(float(scores_df[col].mean()), 4)
            for col in scores_df.columns
            if col not in skip and scores_df[col].dtype.kind in ("f", "i")
        }

    except ImportError as e:
        print(f"[ragas eval] RAGAS import error — is 'ragas' installed? ({e})")
        scores = {"error": str(e)}
    except Exception as e:
        print(f"[ragas eval] RAGAS scoring failed: {e}")
        scores = {"error": str(e)}

    # ── Write results ─────────────────────────────────────────────────────────
    os.makedirs(out_dir, exist_ok=True)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    out_path  = os.path.join(out_dir, f"news_ragas_{date_str}.json")

    output = {
        "date":            date_str,
        "n_questions":     len(EVAL_QUESTIONS),
        "n_evaluated":     len(samples),
        "groq_model":      "llama-3.3-70b-versatile",
        "embed_model":     "BAAI/bge-small-en-v1.5 (HuggingFace/sentence-transformers)",
        "scores":          scores,
        "samples_preview": samples[:3],
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    # ── Print summary ─────────────────────────────────────────────────────────
    print("\n" + "─" * 52)
    print(f"  RAGAS results  ({date_str})")
    print("─" * 52)
    metric_labels = {
        "faithfulness":                      "Faithfulness              ",
        "answer_relevancy":                  "Answer Relevancy          ",
        "context_precision_without_reference": "Context Precision (no ref)",
    }
    for key, val in scores.items():
        if isinstance(val, float) and not (val != val):  # not NaN
            label = metric_labels.get(key, key)
            bar   = "█" * int(val * 20)
            print(f"  {label}  {val:.3f}  {bar}")
        elif isinstance(val, float):
            label = metric_labels.get(key, key)
            print(f"  {label}  NaN  (all evaluations failed — check rate limits)")
        else:
            print(f"  {key}: {val}")
    print("─" * 52)
    print(f"  Full results: {out_path}\n")

    return output


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="RAGAS evaluation for the health-news RAG pipeline"
    )
    parser.add_argument("--groq-key", required=True, help="Groq API key (gsk_…)")
    parser.add_argument(
        "--out", default="eval/results", help="Output directory for metrics JSON"
    )
    args = parser.parse_args()

    result = run_eval(groq_key=args.groq_key, out_dir=args.out)
    if not result:
        sys.exit(1)
