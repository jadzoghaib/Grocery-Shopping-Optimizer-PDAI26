"""Nutrition specialist tools for the LangGraph nutrition agent.

Three tools:
  1. calculate_macros  — deterministic TDEE + macro targets (Mifflin-St Jeor)
  2. lookup_food       — local USDA-derived food nutrition table
  3. search_nutrition_knowledge — TF-IDF RAG over data/nutrition_kb/ text files

URLs for nutrition_kb are supplied by the user; drop plain-text or .txt files
into data/nutrition_kb/ and they are indexed automatically on first call.
"""
from __future__ import annotations

import math
import os
import csv
import io
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool


# ── Paths ──────────────────────────────────────────────────────────────────────

_BASE = Path(__file__).parent.parent  # repo root
_FOODS_CSV = _BASE / "data" / "nutrition_kb" / "foods.csv"
_KB_DIR    = _BASE / "data" / "nutrition_kb"


# ── Tool 1: calculate_macros ───────────────────────────────────────────────────

# Activity multipliers (Mifflin-St Jeor PAL)
_ACTIVITY = {
    "sedentary":   1.2,
    "light":       1.375,
    "moderate":    1.55,
    "active":      1.725,
    "very_active": 1.9,
}

# Goal adjustments (kcal offset from TDEE)
_GOAL_OFFSET = {
    "lose":     -500,
    "maintain":    0,
    "gain":     +300,
}

# Default macro splits (% of total kcal)
_MACRO_SPLITS = {
    "lose":     {"protein_pct": 0.35, "fat_pct": 0.30, "carb_pct": 0.35},
    "maintain": {"protein_pct": 0.25, "fat_pct": 0.30, "carb_pct": 0.45},
    "gain":     {"protein_pct": 0.30, "fat_pct": 0.25, "carb_pct": 0.45},
}


@tool
def calculate_macros(
    weight_kg: float,
    height_cm: float,
    age: int,
    sex: Literal["male", "female"],
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"],
    goal: Literal["lose", "maintain", "gain"],
) -> str:
    """Calculate daily calorie target (TDEE) and macronutrient breakdown.

    Uses the Mifflin-St Jeor equation + PAL activity multiplier.
    Returns a structured text summary with kcal, protein (g), carbs (g), fat (g).

    Parameters:
        weight_kg: Body weight in kilograms
        height_cm: Height in centimetres
        age: Age in years
        sex: 'male' or 'female'
        activity_level: One of sedentary / light / moderate / active / very_active
        goal: One of lose / maintain / gain
    """
    # Mifflin-St Jeor BMR
    if sex == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    pal    = _ACTIVITY.get(activity_level, 1.55)
    tdee   = bmr * pal
    target = tdee + _GOAL_OFFSET.get(goal, 0)
    target = max(1200, round(target))  # floor at 1200 kcal

    split   = _MACRO_SPLITS.get(goal, _MACRO_SPLITS["maintain"])
    protein = round(target * split["protein_pct"] / 4)   # 4 kcal/g
    fat     = round(target * split["fat_pct"]     / 9)   # 9 kcal/g
    carbs   = round(target * split["carb_pct"]    / 4)

    goal_label = {"lose": "weight loss", "maintain": "maintenance", "gain": "muscle gain"}.get(goal, goal)

    return (
        f"TDEE: {round(tdee)} kcal/day | Target ({goal_label}): {target} kcal/day\n"
        f"Macros: Protein {protein}g | Carbs {carbs}g | Fat {fat}g\n"
        f"  (Protein {round(split['protein_pct']*100)}% | "
        f"Carbs {round(split['carb_pct']*100)}% | "
        f"Fat {round(split['fat_pct']*100)}%)\n"
        f"BMR: {round(bmr)} kcal | Activity: {activity_level} (×{pal})"
    )


# ── Tool 2: lookup_food ────────────────────────────────────────────────────────

def _load_foods() -> list[dict]:
    """Load foods.csv, return list of dicts. Returns empty list if file missing."""
    if not _FOODS_CSV.exists():
        return []
    with open(_FOODS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@tool
def lookup_food(food_name: str) -> str:
    """Look up nutritional values (per 100g) for a food or ingredient.

    Returns calories, protein, carbs, and fat per 100g from a local USDA-derived table.
    If the exact food is not found, returns the closest matches.

    Parameters:
        food_name: Name of the food or ingredient to look up (e.g. 'chicken breast', 'avocado')
    """
    foods = _load_foods()
    if not foods:
        return (
            "Food table not yet populated. "
            "Add foods.csv to data/nutrition_kb/ with columns: "
            "name, kcal_per_100g, protein_g, carbs_g, fat_g."
        )

    query = food_name.lower().strip()
    # Exact match first
    exact = [f for f in foods if query == f.get("name", "").lower().strip()]
    if exact:
        matches = exact[:1]
    else:
        # Fuzzy: any word in query appears in name
        words  = set(query.split())
        scored = []
        for f in foods:
            fname = f.get("name", "").lower()
            hits  = sum(1 for w in words if w in fname)
            if hits:
                scored.append((hits, f))
        scored.sort(key=lambda x: -x[0])
        matches = [s[1] for s in scored[:3]]

    if not matches:
        return f"No nutritional data found for '{food_name}'. Try a more generic name."

    lines = [f"Nutritional values per 100g for '{food_name}':"]
    for f in matches:
        lines.append(
            f"  {f.get('name','?')}: "
            f"{f.get('kcal_per_100g','?')} kcal | "
            f"Protein {f.get('protein_g','?')}g | "
            f"Carbs {f.get('carbs_g','?')}g | "
            f"Fat {f.get('fat_g','?')}g"
        )
    return "\n".join(lines)


# ── Tool 3: search_nutrition_knowledge ────────────────────────────────────────

_kb_index: tuple | None = None  # (vectorizer, matrix, docs) cached in memory


def _build_kb_index():
    """Build TF-IDF index over all .txt files in data/nutrition_kb/."""
    global _kb_index
    txt_files = list(_KB_DIR.glob("*.txt"))
    if not txt_files:
        _kb_index = None
        return

    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = []
    for fp in txt_files:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
            # Chunk into ~500-char paragraphs
            for para in text.split("\n\n"):
                para = para.strip()
                if len(para) > 80:
                    docs.append({"source": fp.name, "text": para})
        except Exception:
            pass

    if not docs:
        _kb_index = None
        return

    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as _np
    vec    = TfidfVectorizer(ngram_range=(1, 2), max_features=20000)
    matrix = vec.fit_transform([d["text"] for d in docs])
    _kb_index = (vec, matrix, docs)


@tool
def search_nutrition_knowledge(query: str, top_k: int = 4) -> str:
    """Search the nutrition knowledge base for diet and nutrition information.

    Covers specific diet programs (keto, Mediterranean, IF, DASH, bulking/cutting),
    general nutrition principles, and food science. Add reference .txt files to
    data/nutrition_kb/ to expand the knowledge base.

    Parameters:
        query: Topic or question to search for
        top_k: Number of result passages to return (default 4)
    """
    global _kb_index
    if _kb_index is None:
        _build_kb_index()

    if _kb_index is None:
        return (
            "Nutrition knowledge base is empty. "
            "To populate it, add plain-text reference files (.txt) to data/nutrition_kb/. "
            "In the meantime, I'll answer from my training knowledge."
        )

    from sklearn.metrics.pairwise import cosine_similarity
    vec, matrix, docs = _kb_index
    try:
        scores = cosine_similarity(vec.transform([query]), matrix).flatten()
    except Exception:
        _kb_index = None
        return "Knowledge base index error — please try again."

    top_idx = scores.argsort()[::-1][:int(top_k)]
    results = []
    for i in top_idx:
        if scores[i] < 0.05:
            break
        results.append(f"[{docs[i]['source']}]\n{docs[i]['text'][:600]}")

    if not results:
        return "No relevant passages found in nutrition knowledge base for that query."

    return "\n\n---\n\n".join(results)
