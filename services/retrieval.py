"""Multi-source retrieval for the app assistant.

Sources:
  1. Mercadona product catalogue (TF-IDF, via rag.retrieve)
  2. Recipe database (TF-IDF on name + keywords + ingredients)
  3. YouTube video search (youtubesearchpython, keyworded)
  4. Web search (DuckDuckGo, skipped for pure price/stock queries)
"""
from core.cache import cache_data
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ── Recipe index ──────────────────────────────────────────────────────────────

@cache_data(show_spinner=False)
def _recipe_index():
    try:
        from core.data import load_recipe_data
        df = load_recipe_data().reset_index(drop=True)
        if df.empty:
            return pd.DataFrame(), None, None
        text_col = (
            df.get('name',             pd.Series([''] * len(df))).fillna('') + ' ' +
            df.get('Keywords',         pd.Series([''] * len(df))).fillna('') + ' ' +
            df.get('RecipeCategory',   pd.Series([''] * len(df))).fillna('') + ' ' +
            df.get('ingredients',      pd.Series([''] * len(df))).fillna('')
        )
        vec = TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=20_000)
        mat = vec.fit_transform(text_col.astype(str))
        return df, vec, mat
    except Exception:
        return pd.DataFrame(), None, None


_MACRO_KEYWORDS = {
    "protein":  ["protein", "high protein", "most protein"],
    "calories": ["calorie", "calories", "high calorie", "most calories", "highest calorie"],
    "carbs":    ["carb", "carbs", "high carb", "most carbs"],
    "fat":      ["fat", "high fat", "most fat"],
}


def _detect_macro_sort(query: str):
    """Return column name to sort by if query asks for top-N by macro, else None."""
    q = query.lower()
    for col, keywords in _MACRO_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return col
    return None


_NAME_PREFIX_RE = None  # compiled lazily


def _strip_query_prefix(query: str) -> str:
    """Remove 'give me / ingredients for / recipe for …' prefixes to isolate a recipe name."""
    import re
    global _NAME_PREFIX_RE
    if _NAME_PREFIX_RE is None:
        _NAME_PREFIX_RE = re.compile(
            r'^(?:give me |show me |what are |list |find |get |the |a )?'
            r'(?:the )?'
            r'(?:ingredients? (?:for|of|in) |recipe (?:for|of) |details? (?:for|of) )?',
            re.IGNORECASE,
        )
    return _NAME_PREFIX_RE.sub('', query).strip()


def retrieve_recipes(query: str, top_k: int = 5, min_score: float = 0.12) -> str:
    df, vec, mat = _recipe_index()
    if df.empty or vec is None:
        return ""

    macro_col = _detect_macro_sort(query)
    if macro_col and macro_col in df.columns:
        top_rows = df.nlargest(top_k, macro_col)
    else:
        scores  = cosine_similarity(vec.transform([query]), mat).flatten()
        top_idx = scores.argsort()[::-1][:top_k]
        top_idx = [i for i in top_idx if scores[i] >= min_score]

        # Exact / near-exact name match boost
        # Fixes "Summer Sausage" → "Summer Pudding" TF-IDF failure
        clean = _strip_query_prefix(query)
        if 1 <= len(clean.split()) <= 7:
            exact_row = _get_recipe_row(clean)
            if exact_row is not None:
                exact_nm = str(exact_row.get('name', '')).lower()
                already_in = any(
                    str(df.iloc[i].get('name', '')).lower() == exact_nm
                    for i in top_idx
                )
                if not already_in:
                    mask = df['name'].str.lower() == exact_nm
                    if mask.any():
                        top_idx = [int(df.index[mask][0])] + top_idx[:top_k - 1]

        if not top_idx:
            return ""
        top_rows = df.iloc[top_idx]

    lines = []
    for _, r in top_rows.iterrows():
        name = r.get('name', 'Unknown')
        cat  = r.get('RecipeCategory', '')
        cals = r.get('calories', '')
        prot = r.get('protein', '')
        time = r.get('prep_time', '')
        cost = r.get('cost', '')
        ing  = str(r.get('ingredients', ''))
        line = f"- {name} | {cat} | {cals} kcal | {prot}g protein | {time} min | €{cost}"
        if ing and ing not in ('nan', ''):
            ing_names = _parse_ingredient_names(ing)
            if ing_names:
                ing_display = ', '.join(ing_names[:20])
                if len(ing_names) > 20:
                    ing_display += f', … (+{len(ing_names) - 20} more)'
                line += f" | Ingredients (names only — quantities not stored): {ing_display}"
        lines.append(line)
    return '\n'.join(lines)


def _get_recipe_row(recipe_name: str):
    """Return the DataFrame row for the best-matching recipe by name."""
    import re
    df, vec, mat = _recipe_index()
    if df.empty or vec is None:
        return None
    # Try exact match first
    mask = df['name'].str.lower() == recipe_name.lower()
    if mask.any():
        return df[mask].iloc[0]
    # Fallback to TF-IDF best match
    scores = cosine_similarity(vec.transform([recipe_name]), mat).flatten()
    best_idx = scores.argmax()
    if scores[best_idx] < 0.05:
        return None
    return df.iloc[best_idx]


def _parse_ingredient_names(raw: str) -> list:
    """Extract ingredient names from formats like c("garlic", "fresh ginger", ...)."""
    import re
    names = re.findall(r'"([^"]+)"', raw)
    if not names:
        names = [x.strip().strip("'\"") for x in raw.split(',') if x.strip()]
    return [n for n in names if n and n.lower() not in ('nan', '')]


# ── Web search (DuckDuckGo) ───────────────────────────────────────────────────

def search_web(query: str, max_results: int = 3) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        lines = [
            f"- {r['title']}: {r['body'][:200]} ({r['href']})"
            for r in results
        ]
        return '\n'.join(lines)
    except Exception:
        return ""


# ── YouTube search ────────────────────────────────────────────────────────────

_YT_KEYWORDS = {
    "video", "youtube", "watch", "tutorial",
    "how to make", "how do i make", "show me", "recipe video",
}


def search_youtube(query: str, max_results: int = 3) -> str:
    try:
        from youtubesearchpython import VideosSearch
        hits = VideosSearch(query, limit=max_results).result().get('result', [])
        lines = []
        for r in hits:
            title   = r.get('title', '')
            channel = r.get('channel', {}).get('name', '')
            link    = r.get('link', '')
            dur     = r.get('duration', '')
            lines.append(f"- {title} by {channel} ({dur}) — {link}")
        return '\n'.join(lines)
    except Exception:
        return ""


# ── Context router ────────────────────────────────────────────────────────────

# Queries that are purely about product availability / price — skip web search
_PRODUCT_ONLY_KWS = {
    "price", "cost", "how much", "do you have",
    "available", "in stock", "carry", "sell",
}

# Keywords that strongly signal a recipe/nutrition query (skip Mercadona products)
_RECIPE_ONLY_KWS = {
    "recipe", "recipes", "make", "cook", "bake", "ingredient",
    "calories", "protein", "carbs", "nutrition", "vegan",
    "vegetarian", "breakfast", "dinner", "lunch", "meal", "dish",
    "how to", "can i make", "what can i",
}

# Keywords that signal "add this recipe's ingredients to basket"
_ADD_BASKET_KWS = {"add", "basket", "buy", "purchase", "ingredients", "ingredient", "shopping"}


def _extract_recipe_name_from_history(messages_history: list) -> str:
    """Scan recent messages for a mentioned recipe name.

    Strategy: database-driven lookup first (most reliable — not dependent on LLM output
    format), then regex patterns as fallback.
    """
    import re

    recent = messages_history[-12:]  # only look at recent context

    # ── Strategy 1: Database-driven — scan message content for known recipe names ──
    # Check USER messages first (user explicitly names the recipe they want).
    # Only fall back to ASSISTANT messages — assistant responses often list many recipes,
    # so checking them last avoids returning the wrong one (longest match ≠ intended recipe).
    try:
        db, _, _ = _recipe_index()
        if not db.empty and 'name' in db.columns:
            # Sort longest-first so "Shepherd's Pie II" beats "Shepherd's Pie"
            names_sorted = sorted(
                [n for n in db['name'].dropna().tolist() if len(n) >= 4],
                key=len, reverse=True,
            )
            # Pass 1: user messages only (most recent first)
            for msg in reversed(recent):
                if msg.get("role") != "user":
                    continue
                content_lower = msg.get("content", "").lower()
                if not content_lower:
                    continue
                for name in names_sorted:
                    if name.lower() in content_lower:
                        return name
            # Pass 2: assistant messages (fallback — last resort)
            for msg in reversed(recent):
                if msg.get("role") != "assistant":
                    continue
                content_lower = msg.get("content", "").lower()
                if not content_lower:
                    continue
                for name in names_sorted:
                    if name.lower() in content_lower:
                        return name
    except Exception:
        pass

    # ── Strategy 2: Regex fallback (legacy patterns) ──────────────────────────
    for msg in reversed(recent):
        content = msg.get("content", "")
        role    = msg.get("role", "")

        if role == "assistant":
            # table rows: "- Name | ... | kcal | ..."
            for line in content.split("\n"):
                if "|" in line and "kcal" in line:
                    name = re.sub(r"^[-*\s]+", "", line).split("|")[0].strip()
                    if name:
                        return name
            # bold **Recipe Name**
            bold = re.findall(r'\*\*([A-Z][^*]{4,60})\*\*', content)
            if bold:
                return bold[0]
            # quoted names
            match = re.search(r"['\"]([A-Z][^'\"]{4,60})['\"]", content)
            if match:
                return match.group(1)
            # "ingredients for X are:" / "For the X recipe, the ingredients"
            match = re.search(
                r"(?:ingredients for|for the)\s+([A-Z][^\n.!?:]{4,60?})\s+(?:recipe\b|are\b)",
                content, re.IGNORECASE,
            )
            if match:
                return match.group(1).strip()

        if role == "user":
            match = re.search(
                r"(?:add|buy|make|cook)\s+(?:the\s+)?([A-Z][^\n.!?]{4,60?})"
                r"(?:\s+to\s+basket|\s+ingredients|\s+recipe)?",
                content, re.IGNORECASE,
            )
            if match:
                candidate = match.group(1).strip()
                if len(candidate.split()) >= 2:
                    return candidate
    return ""


def _merc_search_bilingual(ingredient: str, top_k: int = 2) -> str:
    """Search Mercadona for an ingredient with English→Spanish fallback."""
    from services.rag import search_products
    from core.ingredient_translations import ENGLISH_TO_SPANISH
    df = search_products(ingredient, top_k=top_k, min_score=0.1)
    if df.empty:
        spanish = ENGLISH_TO_SPANISH.get(ingredient.lower().strip())
        if spanish:
            df = search_products(spanish, top_k=top_k, min_score=0.1)
    if df.empty:
        return "  (no Mercadona match found)"
    lines = []
    for _, row in df.iterrows():
        price_str = f"€{row['price']:.2f}" if pd.notna(row.get("price")) else "price unknown"
        url = str(row.get("url", "")).strip()
        line = f"  - {row['name']} | {price_str}"
        if url:
            line += f" | {url}"
        lines.append(line)
    return "\n".join(lines)


def build_context(question: str, messages_history: list = None, top_k: int = 6) -> str:
    """Retrieve relevant context from all sources and return a combined string."""
    from services.rag import retrieve as _merc_retrieve
    messages_history = messages_history or []

    # Enrich vague follow-up queries with the last mentioned recipe name
    _VAGUE_FOLLOWUP_KWS = {"ingredient", "ingredients", "what", "tell me", "more about", "the recipe"}
    q_stripped = question.lower().strip().rstrip("?")
    if any(kw in q_stripped for kw in _VAGUE_FOLLOWUP_KWS):
        last_recipe = _extract_recipe_name_from_history(messages_history)
        if last_recipe:
            question = f"{question} {last_recipe}"

    q       = question.lower()
    parts   = []

    # Special case: user wants to add a recipe's ingredients to basket
    # → look up the recipe, find each ingredient, search Mercadona per ingredient
    is_add_basket = sum(1 for kw in _ADD_BASKET_KWS if kw in q) >= 2
    if is_add_basket:
        # Scan the current question first — the user may have named the recipe explicitly
        # (e.g. "add the ingredients for Bayrischer Leberkaese to my basket")
        recipe_name = _extract_recipe_name_from_history([{"role": "user", "content": question}])
        if not recipe_name:
            recipe_name = _extract_recipe_name_from_history(messages_history)
        if recipe_name:
            row = _get_recipe_row(recipe_name)
            if row is not None:
                raw_ing = str(row.get('ingredients', ''))
                ing_names = _parse_ingredient_names(raw_ing)
                if ing_names:
                    lines = [f"Full ingredients for '{row.get('name', recipe_name)}':"]
                    for ing in ing_names:
                        merc_match = _merc_search_bilingual(ing, top_k=2)
                        lines.append(f"\n  Ingredient: {ing}\n  Mercadona matches:\n{merc_match}")
                    parts.append(f"=== Recipe Ingredient → Mercadona Matches ===\n" + "\n".join(lines))
                    # Skip generic Mercadona search since we did per-ingredient above
                    rec = retrieve_recipes(question, top_k=min(top_k, 3))
                    if rec:
                        count = rec.count('\n') + 1
                        parts.append(f"=== Recipes in Your Database ({count} matches found) ===\n{rec}")
                    return '\n\n'.join(parts) if parts else "No relevant information found."

    # Detect intent to avoid mixing irrelevant context
    is_recipe_query   = any(kw in q for kw in _RECIPE_ONLY_KWS)
    is_product_query  = any(kw in q for kw in _PRODUCT_ONLY_KWS)

    # 1. Mercadona products — skip for pure recipe queries
    if not is_recipe_query or is_product_query:
        merc = _merc_retrieve(question, top_k=min(top_k, 5))
        if merc and merc != "No Mercadona product data available.":
            parts.append(f"=== Mercadona Products ===\n{merc}")

    # 2. Recipe database — skip for pure product queries
    if not is_product_query or is_recipe_query:
        rec = retrieve_recipes(question, top_k=top_k)
        if rec:
            count = rec.count('\n') + 1
            parts.append(f"=== Recipes in Your Database ({count} matches found) ===\n{rec}")

    # 3. YouTube videos — only when the question mentions video/tutorial
    if any(kw in q for kw in _YT_KEYWORDS):
        yt = search_youtube(question, max_results=3)
        if yt:
            parts.append(f"=== YouTube Recipe Videos ===\n{yt}")

    # 4. Web search — skip for pure price/stock look-ups
    if not any(kw in q for kw in _PRODUCT_ONLY_KWS):
        web = search_web(question, max_results=3)
        if web:
            parts.append(f"=== Web Search Results ===\n{web}")

    return '\n\n'.join(parts) if parts else "No relevant information found."
