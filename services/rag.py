import json as _json
import re

import pandas as pd
import streamlit as st
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@st.cache_data(ttl=3600)
def _load_index():
    from core.data import load_mercadona_db
    df = load_mercadona_db().dropna(subset=["name"]).reset_index(drop=True)

    vectorizer = TfidfVectorizer(ngram_range=(1, 2), analyzer="word", min_df=1)
    matrix = vectorizer.fit_transform(df["name"].astype(str)) if not df.empty else vectorizer.fit_transform(["placeholder"])
    return df, vectorizer, matrix


def retrieve(query: str, top_k: int = 5) -> str:
    df, vectorizer, matrix = _load_index()
    if df.empty:
        return "No Mercadona product data available."

    scores = cosine_similarity(vectorizer.transform([query]), matrix).flatten()
    top_rows = df.iloc[scores.argsort()[::-1][:top_k]]

    lines = []
    for _, row in top_rows.iterrows():
        price_str = f"€{row['price']:.2f}" if pd.notna(row.get("price")) else "price unknown"
        line = f"- {row['name']} | {price_str}/{str(row.get('unit', ''))}"
        if str(row.get("url", "")).strip():
            line += f" | {row['url']}"
        lines.append(line)
    return "\n".join(lines)


def search_products(query: str, top_k: int = 10, min_score: float = 0.1) -> pd.DataFrame:
    """Return top matching Mercadona products as a DataFrame (no LLM).
    Returns empty DataFrame if best match scores below min_score."""
    df, vectorizer, matrix = _load_index()
    if df.empty:
        return pd.DataFrame(columns=["name", "price", "unit", "url"])
    scores = cosine_similarity(vectorizer.transform([query]), matrix).flatten()
    top_idx = scores.argsort()[::-1][:top_k]
    top_idx = [i for i in top_idx if scores[i] >= min_score]
    if not top_idx:
        return pd.DataFrame(columns=["name", "price", "unit", "url"])
    top_rows = df.iloc[top_idx].copy()
    return top_rows.reset_index(drop=True)


# ── Key validation ─────────────────────────────────────────────────────────────

_KEY_PATTERNS = {
    "OpenAI":    r"^sk-[A-Za-z0-9\-_]{20,}$",
    "Groq":      r"^gsk_[A-Za-z0-9]{20,}$",
    "Anthropic": r"^sk-ant-[A-Za-z0-9\-_]{20,}$",
}

def is_valid_key(key: str, provider: str) -> bool:
    key = key.strip()
    if provider == "Ollama":
        return True
    if not key:
        return False
    if provider in _KEY_PATTERNS:
        return bool(re.match(_KEY_PATTERNS[provider], key))
    if provider in ("Mistral", "Cohere", "Gemini", "OpenRouter"):
        return len(key) >= 20
    return False


# ── Default models per provider ───────────────────────────────────────────────

DEFAULT_MODELS = {
    "OpenAI":      "gpt-4o-mini",
    "Groq":        "llama-3.3-70b-versatile",
    "Anthropic":   "claude-sonnet-4-6",
    "Mistral":     "mistral-small-latest",
    "Cohere":      "command-r-plus",
    "Gemini":      "gemini-2.0-flash",
    "Ollama":      "deepseek-v3.1:671b-cloud",
    "OpenRouter":  "meta-llama/llama-3.3-70b-instruct:free",
}


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You are a smart grocery shopping assistant. "
    "You have two tools: search_recipes and search_mercadona. "
    "Use them whenever the user asks about recipes, meals, nutrition, products, prices, or shopping. "
    "For greetings and general conversation, respond directly without calling any tool.\n\n"

    "RULES:\n"
    "- Only use information returned by your tools. NEVER fabricate recipes, products, or nutrition values.\n"
    "- NEVER invent URLs. Only include a URL if it appears verbatim in a tool result.\n"
    "- If a tool returns no results, say: 'I don't have that information in my database.'\n"
    "- NEVER state how many total recipes or products exist — you only see what the tool returns.\n"
    "- Be concise. Answer only what was asked.\n\n"

    "BASKET RULE: When the user asks to add items to their basket, call search_mercadona for each "
    "ingredient, then respond naturally AND append on its own line at the very end a JSON block "
    "in exactly this format (no markdown fences):\n"
    "{\"add_to_basket\": [{\"name\": \"Product Name\", \"price\": 1.99, \"qty\": \"1 unit\", \"url\": \"https://...\"}]}\n"
    "Always pick the CLOSEST available Mercadona product — products are rarely an exact name match. "
    "Only omit the JSON block if the tool returned zero results."
)


# ── Tool definitions ───────────────────────────────────────────────────────────

_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": "search_recipes",
            "description": (
                "Search the recipe database for meals, nutrition info, or cooking ideas. "
                "Call this when the user asks about recipes, meals, ingredients, calories, protein, or cooking."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_mercadona",
            "description": (
                "Search Mercadona supermarket products and prices. "
                "Call this when the user asks about buying products, prices, adding items to basket, "
                "or product availability."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Product to search for"}
                },
                "required": ["query"],
            },
        },
    },
]

_TOOLS_ANTHROPIC = [
    {
        "name": "search_recipes",
        "description": (
            "Search the recipe database for meals, nutrition info, or cooking ideas. "
            "Call this when the user asks about recipes, meals, ingredients, calories, protein, or cooking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_mercadona",
        "description": (
            "Search Mercadona supermarket products and prices. "
            "Call this when the user asks about buying products, prices, adding items to basket, "
            "or product availability."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Product to search for"}
            },
            "required": ["query"],
        },
    },
]


# ── Tool executor ──────────────────────────────────────────────────────────────

def _execute_tool(name: str, args: dict) -> str:
    if name == "search_recipes":
        from services.retrieval import retrieve_recipes
        result = retrieve_recipes(args.get("query", ""), top_k=5)
        return result if result else "No matching recipes found in the database."
    if name == "search_mercadona":
        result = retrieve(args.get("query", ""), top_k=5)
        return result if result else "No matching Mercadona products found."
    return f"Unknown tool: {name}"


# ── Text-based tool call parser (fallback for models that don't use structured API) ──

def _parse_text_tool_calls(content: str) -> list:
    """Some models (e.g. DeepSeek via Ollama) output tool calls as plain text
    like: search_recipes{"query": "..."} instead of using the structured API.
    This parser extracts and returns them as (name, args) tuples."""
    calls = []
    # Match: tool_name{"key": "value", ...}  or  tool_name({"key": "value"})
    pattern = r'(search_recipes|search_mercadona)\s*[\(\{]?\s*(\{[^}]+\})\s*[\)\}]?'
    for match in re.finditer(pattern, content):
        tool_name = match.group(1)
        try:
            args = _json.loads(match.group(2))
            calls.append((tool_name, args))
        except Exception:
            pass
    return calls


# ── OpenAI-compatible tool loop ────────────────────────────────────────────────

def _openai_tool_loop(client, model: str, messages: list, **kwargs) -> str:
    """Run the tool-use agentic loop for any OpenAI-compatible client.
    Falls back to text-based tool call parsing for models that don't use
    the structured function-calling API (e.g. DeepSeek via Ollama)."""
    response = client.chat.completions.create(
        model=model, messages=messages, tools=_TOOLS_OPENAI,
        tool_choice="auto", max_tokens=1024, **kwargs
    )
    for _ in range(5):  # max 5 tool rounds
        msg = response.choices[0].message
        content = msg.content or ""

        # ── Structured tool calls (standard API) ──
        if msg.tool_calls:
            messages.append(msg)
            for tc in msg.tool_calls:
                result = _execute_tool(tc.function.name, _json.loads(tc.function.arguments))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
            response = client.chat.completions.create(
                model=model, messages=messages, tools=_TOOLS_OPENAI,
                tool_choice="auto", max_tokens=1024, **kwargs
            )
            continue

        # ── Text-based tool calls (fallback for models like DeepSeek/Ollama) ──
        text_calls = _parse_text_tool_calls(content)
        if text_calls:
            # Strip the raw tool-call text from the assistant message
            clean_content = re.sub(
                r'(search_recipes|search_mercadona)\s*[\(\{]?\s*\{[^}]+\}\s*[\)\}]?',
                '', content
            ).strip()
            messages.append({"role": "assistant", "content": clean_content or "Looking that up..."})
            for tool_name, args in text_calls:
                result = _execute_tool(tool_name, args)
                messages.append({
                    "role": "user",
                    "content": f"[Tool result for {tool_name}]: {result}"
                })
            response = client.chat.completions.create(
                model=model, messages=messages, tools=_TOOLS_OPENAI,
                tool_choice="auto", max_tokens=1024, **kwargs
            )
            continue

        break  # No tool calls — final answer

    return (response.choices[0].message.content or "").strip()


# ── Anthropic tool loop ────────────────────────────────────────────────────────

def _anthropic_tool_loop(client, model: str, messages: list) -> str:
    """Run the tool-use agentic loop for Anthropic."""
    response = client.messages.create(
        model=model, max_tokens=1024,
        system=_SYSTEM_PROMPT, messages=messages, tools=_TOOLS_ANTHROPIC,
    )
    for _ in range(5):
        if response.stop_reason != "tool_use":
            break
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {"type": "tool_result", "tool_use_id": tu.id, "content": _execute_tool(tu.name, tu.input)}
            for tu in tool_uses
        ]
        messages.append({"role": "user", "content": tool_results})
        response = client.messages.create(
            model=model, max_tokens=1024,
            system=_SYSTEM_PROMPT, messages=messages, tools=_TOOLS_ANTHROPIC,
        )
    return next((b.text for b in response.content if hasattr(b, "text")), "").strip()


# ── LLM call ──────────────────────────────────────────────────────────────────

def rag_answer(question: str, messages_history: list, api_key: str, provider: str, model: str = None) -> str:
    model = model or DEFAULT_MODELS.get(provider, "")

    # Build message list (system prompt handled separately for Anthropic)
    base_messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    base_messages.extend(messages_history)
    base_messages.append({"role": "user", "content": question})

    # Anthropic-only messages (no system in the list)
    anthropic_messages = list(messages_history) + [{"role": "user", "content": question}]

    if provider == "OpenAI":
        from openai import OpenAI
        return _openai_tool_loop(
            OpenAI(api_key=api_key.strip()), model, base_messages, temperature=0.3
        )

    if provider == "Groq":
        from groq import Groq
        return _openai_tool_loop(
            Groq(api_key=api_key.strip()), model, base_messages, temperature=0.3
        )

    if provider == "Anthropic":
        import anthropic
        return _anthropic_tool_loop(
            anthropic.Anthropic(api_key=api_key.strip()), model, anthropic_messages
        )

    if provider == "Mistral":
        from mistralai import Mistral
        # Mistral uses OpenAI-compatible tool format via their SDK
        client = Mistral(api_key=api_key.strip())
        response = client.chat.complete(model=model, messages=base_messages, tools=_TOOLS_OPENAI)
        for _ in range(5):
            msg = response.choices[0].message
            if not getattr(msg, "tool_calls", None):
                break
            base_messages.append({"role": "assistant", "content": "", "tool_calls": msg.tool_calls})
            for tc in msg.tool_calls:
                result = _execute_tool(tc.function.name, _json.loads(tc.function.arguments))
                base_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            response = client.chat.complete(model=model, messages=base_messages, tools=_TOOLS_OPENAI)
        return (response.choices[0].message.content or "").strip()

    if provider == "Cohere":
        # Cohere tool-use has a different API — fall back to context injection
        import cohere
        from services.retrieval import build_context
        context   = build_context(question, messages_history)
        augmented = f"{question}\n\n{context}"
        msgs = [{"role": "system", "content": _SYSTEM_PROMPT}]
        msgs.extend(messages_history)
        msgs.append({"role": "user", "content": augmented})
        response = cohere.ClientV2(api_key=api_key.strip()).chat(model=model, messages=msgs)
        return response.message.content[0].text.strip()

    if provider == "Gemini":
        from openai import OpenAI
        return _openai_tool_loop(
            OpenAI(
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                api_key=api_key.strip(),
            ),
            model, base_messages, temperature=0.3,
        )

    if provider == "Ollama":
        from openai import OpenAI
        try:
            return _openai_tool_loop(
                OpenAI(base_url="http://localhost:11434/v1", api_key="ollama"),
                model, base_messages, temperature=0.3,
            )
        except Exception:
            # Fallback for models that don't support tool-use
            from openai import OpenAI
            from services.retrieval import build_context
            context   = build_context(question, messages_history)
            augmented = f"{question}\n\n{context}"
            msgs = [{"role": "system", "content": _SYSTEM_PROMPT}]
            msgs.extend(messages_history)
            msgs.append({"role": "user", "content": augmented})
            response = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama").chat.completions.create(
                model=model, messages=msgs, temperature=0.3
            )
            return response.choices[0].message.content.strip()

    if provider == "OpenRouter":
        from openai import OpenAI
        return _openai_tool_loop(
            OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key.strip()),
            model, base_messages, temperature=0.3,
        )

    raise ValueError(f"Unknown provider: {provider}")


# ── Basket intent parser ───────────────────────────────────────────────────────

def parse_basket_intent(reply: str) -> tuple[str, list]:
    """Split LLM reply into (display_text, basket_items)."""
    pattern = r'\{[^{}]*"add_to_basket"[^{}]*\[[^\]]*\][^{}]*\}'
    match = re.search(pattern, reply, re.DOTALL)
    if not match:
        return reply, []
    try:
        data = _json.loads(match.group())
        items = data.get("add_to_basket", [])
        clean_text = (reply[:match.start()] + reply[match.end():]).strip()
        return clean_text, items
    except Exception:
        return reply, []
