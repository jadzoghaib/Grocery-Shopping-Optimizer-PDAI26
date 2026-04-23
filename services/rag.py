"""Conversational grocery assistant — LangGraph ReAct agent (Groq).

The LLM has two tools and decides when and how to use them.
Single provider: Groq via langchain-groq + langgraph create_react_agent.
"""
import json as _json

import pandas as pd
from core.cache import cache_data
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent


# ── Mercadona index ────────────────────────────────────────────────────────────

@cache_data(ttl=604800)
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
    scores   = cosine_similarity(vectorizer.transform([query]), matrix).flatten()
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
    """Return top matching Mercadona products as a DataFrame (no LLM)."""
    df, vectorizer, matrix = _load_index()
    if df.empty:
        return pd.DataFrame(columns=["name", "price", "unit", "url"])
    scores  = cosine_similarity(vectorizer.transform([query]), matrix).flatten()
    top_idx = scores.argsort()[::-1][:top_k]
    top_idx = [i for i in top_idx if scores[i] >= min_score]
    if not top_idx:
        return pd.DataFrame(columns=["name", "price", "unit", "url"])
    return df.iloc[top_idx].copy().reset_index(drop=True)


# ── Key validation ─────────────────────────────────────────────────────────────

def is_valid_key(key: str) -> bool:
    return len(key.strip()) >= 20


# ── Pinned chat model ──────────────────────────────────────────────────────────

CHAT_MODEL = "llama-3.3-70b-versatile"


# ── LangChain tools ────────────────────────────────────────────────────────────

@tool
def search_recipes(query: str, top_k: int = 5) -> str:
    """Search the recipe database. Use for: finding recipes by name, cuisine or ingredient,
    listing a recipe's ingredients, checking nutrition (calories, protein, carbs, fat),
    meal suggestions, or any cooking question."""
    try:
        from services.retrieval import retrieve_recipes
        result = retrieve_recipes(query, top_k=int(top_k))
        return result or "No recipes found."
    except Exception as e:
        return f"Tool error: {e}"


@tool
def search_mercadona(query: str, top_k: int = 5) -> str:
    """Search the Mercadona supermarket product catalog. Use for: finding products,
    checking prices, looking up specific ingredients available at Mercadona,
    or building a shopping basket."""
    try:
        result = retrieve(query, top_k=int(top_k))
        return result or "No Mercadona products found."
    except Exception as e:
        return f"Tool error: {e}"


_TOOLS = [search_recipes, search_mercadona]


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a friendly grocery shopping assistant.\n\n"
    "You have two tools:\n"
    "- search_recipes: find recipes, ingredients, and nutrition info\n"
    "- search_mercadona: find Mercadona supermarket products with prices\n\n"
    "Use your tools whenever you need information. For basket requests, call search_recipes "
    "first to get the ingredient list, then call search_mercadona once per ingredient.\n\n"
    "After listing a recipe's ingredients, always offer to add them to the basket.\n\n"
    "BASKET: When the user wants to add items to their basket, end your response with this "
    "JSON on its own line (no markdown fences):\n"
    '{"add_to_basket": [{"name": "Product Name", "price": 1.99, "qty": "1 unit", "url": "https://..."}]}\n'
    "Only include products actually returned by search_mercadona. Copy prices and URLs exactly.\n\n"
    "IMPORTANT: Never output tool call syntax in your response text. "
    "Use your tools silently and only show the final answer to the user."
)


# ── Agent builder ──────────────────────────────────────────────────────────────

def _build_grocery_agent(api_key: str):
    """Build and return a compiled LangGraph ReAct agent for grocery chat."""
    from core.llm_config import build_llm
    llm = build_llm(api_key.strip(), temperature=0.3)
    return create_react_agent(llm, tools=_TOOLS)


# ── Main entry point ───────────────────────────────────────────────────────────

def rag_answer(question: str, messages_history: list, api_key: str) -> str:
    """Run the grocery ReAct agent and return the final text response."""
    agent = _build_grocery_agent(api_key)

    # Build LangChain message list
    lc_messages = [SystemMessage(content=SYSTEM_PROMPT)]
    for m in messages_history:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            lc_messages.append(AIMessage(content=content))

    lc_messages.append(HumanMessage(content=question))

    print(f"[Groq/{CHAT_MODEL}] LangGraph ReAct agent invoked")
    try:
        result = agent.invoke({"messages": lc_messages})
        # The last message in the output is the final AI response
        final = result["messages"][-1]
        return (final.content or "").strip()
    except Exception as e:
        print(f"[Groq/{CHAT_MODEL}] agent error: {e}")
        return "I encountered an error. Please try again."


# ── Basket intent parser ───────────────────────────────────────────────────────

def parse_basket_intent(reply: str) -> tuple[str, list]:
    """Split LLM reply into (display_text, basket_items).
    Uses bracket-depth scanning to handle large arrays correctly."""
    key = '"add_to_basket"'
    idx = reply.find(key)
    if idx == -1:
        return reply, []

    start = reply.rfind('{', 0, idx)
    if start == -1:
        return reply, []

    depth, end = 0, -1
    for i, ch in enumerate(reply[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return reply[:start].strip(), []

    try:
        data  = _json.loads(reply[start:end])
        raw   = data.get("add_to_basket", [])
        # Normalize: LLM sometimes returns strings instead of dicts
        items = []
        for it in raw:
            if isinstance(it, dict):
                items.append(it)
            elif isinstance(it, str) and it.strip():
                items.append({"name": it.strip(), "price": 0.0, "qty": "1 unit", "url": ""})
        clean = (reply[:start] + reply[end:]).strip()
        return clean, items
    except Exception:
        return reply, []
