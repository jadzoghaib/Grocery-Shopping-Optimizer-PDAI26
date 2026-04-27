"""Fridge-to-recipe engine — Option C hybrid.

Flow:
  1. Join the user's fridge ingredients into a TF-IDF query.
  2. Search the existing recipe database (same index used by retrieve_recipes).
  3. If top cosine score >= TFIDF_THRESHOLD and at least MIN_DB_HITS recipes found
     → return those DB recipes as suggestions (fast, no LLM cost).
  4. Otherwise → call Groq to *generate* a brand-new recipe from the ingredients.

Public API:
    fridge_suggest(ingredients: list[str], api_key: str) -> dict
"""
from __future__ import annotations

import json as _json
import re
from sklearn.metrics.pairwise import cosine_similarity

# ── Tuning constants ───────────────────────────────────────────────────────────

TFIDF_THRESHOLD = 0.15   # minimum top-1 cosine score to trust DB results
MIN_DB_HITS     = 2      # minimum number of DB results required before skipping generation
TOP_K_DB        = 5      # how many DB recipes to return when DB path is taken
GROQ_MODEL      = "llama-3.3-70b-versatile"


# ── TF-IDF DB search ───────────────────────────────────────────────────────────

def _search_recipes_by_ingredients(ingredients: list[str], top_k: int = TOP_K_DB):
    """Search recipe DB with fridge ingredients as query. Returns (hits, top_score)."""
    from services.retrieval import _recipe_index, _parse_ingredient_names

    df, vec, mat = _recipe_index()
    if df.empty or vec is None:
        return [], 0.0

    query  = " ".join(ingredients)
    scores = cosine_similarity(vec.transform([query]), mat).flatten()
    top_idx = scores.argsort()[::-1][:top_k]
    top_idx = [i for i in top_idx if scores[i] >= TFIDF_THRESHOLD]

    if not top_idx:
        return [], 0.0

    hits = []
    for i in top_idx:
        row   = df.iloc[i]
        raw   = str(row.get("ingredients", ""))
        names = _parse_ingredient_names(raw)

        # How many fridge ingredients actually appear in this recipe?
        fridge_lower  = {ing.lower() for ing in ingredients}
        recipe_lower  = {n.lower() for n in names}
        matched       = sorted(fridge_lower & recipe_lower)
        overlap_count = len(matched)

        def _f(v):
            """Convert numpy scalar → Python float, None/NaN → None."""
            try:
                import math
                fv = float(v)
                return None if math.isnan(fv) else fv
            except Exception:
                return None

        hits.append({
            "source":         "database",
            "name":           str(row.get("name", "Unknown")),
            "category":       str(row.get("RecipeCategory", "")),
            "calories":       _f(row.get("calories")),
            "protein":        _f(row.get("protein")),
            "carbs":          _f(row.get("carbs")),
            "fat":            _f(row.get("fat")),
            "prep_time":      _f(row.get("prep_time")),
            "ingredients":    names,
            "matched_fridge": matched,
            "overlap_count":  int(overlap_count),
            "score":          float(scores[i]),
        })

    top_score = hits[0]["score"] if hits else 0.0
    # Re-sort by overlap_count (most fridge ingredients used first), then score
    hits.sort(key=lambda h: (-h["overlap_count"], -h["score"]))
    return hits, top_score


# ── Groq generation ────────────────────────────────────────────────────────────

_GENERATION_PROMPT = """\
You are a professional chef. The user has these ingredients at home:

{ingredients}

Create ONE complete recipe that uses as many of these ingredients as possible.
Respond with ONLY valid JSON in this exact format (no markdown, no extra text):

{{
  "name": "Recipe Name",
  "uses_from_fridge": ["ingredient1", "ingredient2"],
  "additional_ingredients": ["any extra ingredient needed"],
  "servings": 2,
  "prep_time_minutes": 20,
  "estimated_nutrition": {{"calories": 450, "protein_g": 30, "carbs_g": 40, "fat_g": 15}},
  "ingredients": [
    "200g chicken breast",
    "2 cloves garlic, minced"
  ],
  "instructions": [
    "Step 1: ...",
    "Step 2: ..."
  ],
  "tips": "Optional tip about substitutions or variations."
}}
"""


def _generate_with_groq(ingredients: list[str], api_key: str) -> dict | None:
    """Call Groq to generate a recipe. Returns parsed dict or None on failure."""
    from core.groq_client import make_groq_client
    client = make_groq_client(api_key)
    prompt = _GENERATION_PROMPT.format(ingredients="\n".join(f"- {i}" for i in ingredients))

    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,   # slightly creative for recipe generation
            max_tokens=1024,
        )
        raw = (resp.choices[0].message.content or "").strip()

        # Strip markdown fences if present
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

        data = _json.loads(raw)
        data["source"] = "generated"
        return data
    except Exception as e:
        print(f"[fridge/Groq] generation failed: {e}")
        return None


# ── Public entry point ─────────────────────────────────────────────────────────

def fridge_suggest(ingredients: list[str], api_key: str) -> dict:
    """Hybrid fridge-to-recipe suggestion.

    Returns:
        {
            "path": "database" | "generated" | "error",
            "recipes": [...]       # list of recipe dicts (database path)
            "recipe":  {...}       # single generated recipe (generated path)
            "tfidf_score": float   # top DB cosine score (always present)
            "ingredients_used": int
        }
    """
    ingredients = [i.strip() for i in ingredients if i.strip()]
    if not ingredients:
        return {"path": "error", "error": "No ingredients provided."}

    # ── Step 1: Try DB ─────────────────────────────────────────────────────────
    hits, top_score = _search_recipes_by_ingredients(ingredients)

    good_hits = [h for h in hits if h["overlap_count"] >= 1]
    if top_score >= TFIDF_THRESHOLD and len(good_hits) >= MIN_DB_HITS:
        print(f"[fridge] DB path: {len(good_hits)} hits, top score={top_score:.3f}")
        return {
            "path":           "database",
            "recipes":        good_hits[:TOP_K_DB],
            "tfidf_score":    top_score,
            "ingredients_used": max(h["overlap_count"] for h in good_hits),
        }

    # ── Step 2: Groq generation ────────────────────────────────────────────────
    print(f"[fridge] Groq generation path (top_score={top_score:.3f}, hits={len(good_hits)})")
    generated = _generate_with_groq(ingredients, api_key)

    if generated:
        return {
            "path":           "generated",
            "recipe":         generated,
            "tfidf_score":    top_score,
            "db_hits":        hits[:2],   # include near-misses for context
            "ingredients_used": len(generated.get("uses_from_fridge", [])),
        }

    # ── Step 3: Fallback — return whatever DB had, even if below threshold ─────
    if hits:
        return {
            "path":           "database",
            "recipes":        hits[:TOP_K_DB],
            "tfidf_score":    top_score,
            "ingredients_used": max(h["overlap_count"] for h in hits),
        }

    return {"path": "error", "error": "No recipes found and generation failed. Please try again."}
