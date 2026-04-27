"""Body Optimization service — health news aggregator + micronutrient gap analysis.

Three public entry points:
  fetch_health_news(max_items)       → list[dict]  (cached 6 h)
  analyze_nutrients(meal_plan, meas) → dict        (nutrient coverage vs DRI)
  get_supplement_gaps(coverage, meas)→ list[dict]  (ranked supplement recommendations)
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

# ── Paths ──────────────────────────────────────────────────────────────────────

_SVC_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT     = os.path.normpath(os.path.join(_SVC_DIR, ".."))
_DATA_DIR = os.path.join(_ROOT, "data")
_KB_DIR   = os.path.join(_DATA_DIR, "nutrition_kb")

_NEWS_CACHE_PATH = os.path.join(_DATA_DIR, "body_news_cache.json")
_DRI_PATH        = os.path.join(_KB_DIR, "dri_table.json")
_BLUEPRINT_PATH  = os.path.join(_KB_DIR, "blueprint_stack.json")
_FOODS_PATH      = os.path.join(_KB_DIR, "foods_micronutrients.csv")

_NEWS_TTL_SECONDS = 6 * 3600   # refresh cache every 6 hours
_REQUEST_TIMEOUT  = 8           # seconds per HTTP request

# Nutrient display metadata  (key, label, unit, colour)
NUTRIENT_META: list[tuple[str, str, str, str]] = [
    ("vitamin_d_iu",   "Vitamin D",   "IU",  "#f59e0b"),
    ("vitamin_b12_mcg","Vitamin B12", "mcg", "#6366f1"),
    ("magnesium_mg",   "Magnesium",   "mg",  "#059669"),
    ("zinc_mg",        "Zinc",        "mg",  "#3b82f6"),
    ("omega3_g",       "Omega-3",     "g",   "#8b5cf6"),
    ("iron_mg",        "Iron",        "mg",  "#ef4444"),
    ("calcium_mg",     "Calcium",     "mg",  "#f97316"),
    ("vitamin_c_mg",   "Vitamin C",   "mg",  "#10b981"),
    ("folate_mcg",     "Folate",      "mcg", "#06b6d4"),
    ("vitamin_k_mcg",  "Vitamin K",   "mcg", "#84cc16"),
    ("selenium_mcg",   "Selenium",    "mcg", "#ec4899"),
    ("potassium_mg",   "Potassium",   "mg",  "#64748b"),
]

NUTRIENT_KEYS = [k for k, *_ in NUTRIENT_META]


# ══════════════════════════════════════════════════════════════════════════════
# Full USDA DRI tables (2020 National Academies DRI)
# ══════════════════════════════════════════════════════════════════════════════

_PAL_MAP: dict[str, float] = {
    "sedentary":  1.2,
    "light":      1.375,
    "moderate":   1.55,
    "active":     1.725,
    "very_active": 1.9,
}

# Columns: (male_19_30, male_31_50, male_51plus, female_19_30, female_31_50, female_51plus)
_FULL_DRI: dict[str, tuple] = {
    # ── Fiber & Water ─────────────────────────────────────────────────────────
    "fiber_g":         (38,    38,    30,    25,    25,    21),
    "water_l":         (3.7,   3.7,   3.7,   2.7,   2.7,   2.7),
    # ── Vitamins ──────────────────────────────────────────────────────────────
    "vit_a_mcg":       (900,   900,   900,   700,   700,   700),
    "vit_b1_mg":       (1.2,   1.2,   1.2,   1.1,   1.1,   1.1),
    "vit_b2_mg":       (1.3,   1.3,   1.3,   1.1,   1.1,   1.1),
    "vit_b3_mg":       (16,    16,    16,    14,    14,    14),
    "vit_b5_mg":       (5,     5,     5,     5,     5,     5),
    "vit_b6_mg":       (1.3,   1.3,   1.7,   1.3,   1.3,   1.5),
    "vit_b7_mcg":      (30,    30,    30,    30,    30,    30),
    "vit_b9_mcg":      (400,   400,   400,   400,   400,   400),
    "vit_b12_mcg":     (2.4,   2.4,   2.4,   2.4,   2.4,   2.4),
    "vit_c_mg":        (90,    90,    90,    75,    75,    75),
    "vit_d_mcg":       (15,    15,    20,    15,    15,    20),
    "vit_e_mg":        (15,    15,    15,    15,    15,    15),
    "vit_k_mcg":       (120,   120,   120,   90,    90,    90),
    "choline_mg":      (550,   550,   550,   425,   425,   425),
    # ── Minerals ──────────────────────────────────────────────────────────────
    "calcium_mg":      (1000,  1000,  1000,  1000,  1000,  1200),
    "chromium_mcg":    (35,    35,    30,    25,    25,    20),
    "copper_mcg":      (900,   900,   900,   900,   900,   900),
    "fluoride_mg":     (4,     4,     4,     3,     3,     3),
    "iodine_mcg":      (150,   150,   150,   150,   150,   150),
    "iron_mg":         (8,     8,     8,     18,    18,    8),
    "magnesium_mg":    (400,   420,   420,   310,   320,   320),
    "manganese_mg":    (2.3,   2.3,   2.3,   1.8,   1.8,   1.8),
    "molybdenum_mcg":  (45,    45,    45,    45,    45,    45),
    "phosphorus_mg":   (700,   700,   700,   700,   700,   700),
    "potassium_mg":    (3400,  3400,  3400,  2600,  2600,  2600),
    "selenium_mcg":    (55,    55,    55,    55,    55,    55),
    "sodium_mg":       (1500,  1500,  1300,  1500,  1500,  1300),
    "zinc_mg":         (11,    11,    11,    8,     8,     8),
}

_DRI_TYPE: dict[str, str] = {
    "fiber_g":        "AI",  "water_l":        "AI",
    "vit_a_mcg":      "RDA", "vit_b1_mg":      "RDA",
    "vit_b2_mg":      "RDA", "vit_b3_mg":      "RDA",
    "vit_b5_mg":      "AI",  "vit_b6_mg":      "RDA",
    "vit_b7_mcg":     "AI",  "vit_b9_mcg":     "RDA",
    "vit_b12_mcg":    "RDA", "vit_c_mg":       "RDA",
    "vit_d_mcg":      "RDA", "vit_e_mg":       "RDA",
    "vit_k_mcg":      "AI",  "choline_mg":     "AI",
    "calcium_mg":     "RDA", "chromium_mcg":   "AI",
    "copper_mcg":     "RDA", "fluoride_mg":    "AI",
    "iodine_mcg":     "RDA", "iron_mg":        "RDA",
    "magnesium_mg":   "RDA", "manganese_mg":   "AI",
    "molybdenum_mcg": "RDA", "phosphorus_mg":  "RDA",
    "potassium_mg":   "AI",  "selenium_mcg":   "RDA",
    "sodium_mg":      "AI",  "zinc_mg":        "RDA",
}

# Protein multiplier by activity (g per kg body weight)
_PROTEIN_FACTOR: dict[str, float] = {
    "sedentary":   0.8,
    "light":       0.9,
    "moderate":    1.1,
    "active":      1.3,
    "very_active": 1.6,
}


def compute_full_dri(
    sex: str,
    age: int,
    weight_kg: float,
    height_cm: float,
    activity: str,
) -> dict:
    """Compute complete USDA DRI targets for this person plus TDEE and macro targets.

    Returns a dict with::

        {
          "tdee":       2300,          # kcal/day (Mifflin-St Jeor × PAL)
          "protein_g":  82.5,          # g/day (activity-adjusted)
          "carbs_g":    288,           # g/day (50% of TDEE)
          "fat_g":      71,            # g/day (28% of TDEE)
          "nutrients":  {key: value},  # all DRI nutrients
          "dri_type":   {key: "RDA"|"AI"},
          "sex": ..., "age": ..., ...  # echo inputs
        }
    """
    s = "male" if str(sex).lower() in ("male", "m") else "female"

    # Column index into _FULL_DRI tuples
    if s == "male":
        col = 0 if age < 31 else (1 if age < 51 else 2)
    else:
        col = 3 if age < 31 else (4 if age < 51 else 5)

    nutrients = {key: vals[col] for key, vals in _FULL_DRI.items()}

    # TDEE — Mifflin–St Jeor
    if s == "male":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161

    pal  = _PAL_MAP.get(activity, 1.55)
    tdee = round(bmr * pal)

    protein_g = round(weight_kg * _PROTEIN_FACTOR.get(activity, 0.8), 1)
    carbs_g   = round(tdee * 0.50 / 4)   # 50% of calories from carbs
    fat_g     = round(tdee * 0.28 / 9)   # 28% of calories from fat

    return {
        "tdee":       tdee,
        "protein_g":  protein_g,
        "carbs_g":    carbs_g,
        "fat_g":      fat_g,
        "nutrients":  nutrients,
        "dri_type":   _DRI_TYPE,
        "sex":        s,
        "age":        age,
        "weight_kg":  weight_kg,
        "height_cm":  height_cm,
        "activity":   activity,
    }


# ══════════════════════════════════════════════════════════════════════════════
# News fetching
# ══════════════════════════════════════════════════════════════════════════════

def _load_news_cache() -> list[dict] | None:
    if not os.path.exists(_NEWS_CACHE_PATH):
        return None
    try:
        with open(_NEWS_CACHE_PATH, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if time.time() - cached.get("_ts", 0) < _NEWS_TTL_SECONDS:
            return cached.get("articles", [])
    except Exception:
        pass
    return None


def _save_news_cache(articles: list[dict]) -> None:
    try:
        with open(_NEWS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"_ts": time.time(), "articles": articles}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _fetch_rss(url: str, source_label: str, limit: int = 6) -> list[dict]:
    """Generic RSS fetcher. Returns list of article dicts."""
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT,
                            headers={"User-Agent": "GroceryAI/1.0 (health news aggregator)"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link") or "").strip()
            desc    = _strip_html(item.findtext("description") or "")[:240]
            pub     = (item.findtext("pubDate") or "").strip()
            if title:
                articles.append({
                    "title":   title,
                    "url":     link,
                    "summary": desc,
                    "source":  source_label,
                    "date":    pub,
                })
        return articles
    except Exception:
        return []


def _fetch_ddg_news(query: str, limit: int = 5) -> list[dict]:
    """DuckDuckGo news search fallback."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.news(query, max_results=limit):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("url", ""),
                    "summary": (r.get("body") or "")[:240],
                    "source":  r.get("source", "Web"),
                    "date":    r.get("date", ""),
                })
        return results
    except Exception:
        return []


def fetch_health_news(max_items: int = 30, force_refresh: bool = False) -> list[dict]:
    """Fetch and cache health / longevity news.

    RSS  — Huberman Lab, Peter Attia MD, FoundMyFitness, Lifespan.io,
           Buck Institute, Blue Zones, Longevity.Technology, NIA,
           Fight Aging!, InsideTracker, NOVOS Labs
    DDG  — Examine.com, Bryan Johnson (blueprint / longevity)

    Results are cached for 6 hours. Pass ``force_refresh=True`` to bypass cache.
    """
    if not force_refresh:
        cached = _load_news_cache()
        if cached:
            return cached[:max_items]

    articles: list[dict] = []

    # ── RSS feeds ──────────────────────────────────────────────────────────────
    rss_sources = [
        ("https://feeds.megaphone.fm/hubermanlab",          "Huberman Lab",              5),
        ("https://peterattiamd.com/feed/",                  "Peter Attia MD",            5),
        ("https://www.foundmyfitness.com/feed",             "FoundMyFitness",            5),
        ("https://www.lifespan.io/feed/",                   "Lifespan.io",               5),
        ("https://www.buckinstitute.org/feed/",             "Buck Institute",            4),
        ("https://www.bluezones.com/feed/",                 "Blue Zones",                4),
        ("https://www.longevity.technology/feed/",          "Longevity.Technology",      5),
        ("https://www.nia.nih.gov/news/rss.xml",            "National Institute on Aging", 4),
        ("https://www.fightaging.org/feed/",                "Fight Aging!",              5),
        ("https://www.insidetracker.com/feed/",             "InsideTracker",             4),
        ("https://novoslabs.com/feed/",                     "NOVOS Labs",                4),
    ]
    for url, source, limit in rss_sources:
        articles += _fetch_rss(url, source, limit=limit)

    # ── DuckDuckGo — Examine.com + Bryan Johnson only ─────────────────────────
    for query in [
        "examine.com supplement research",
        "bryan johnson blueprint longevity protocol",
    ]:
        articles += _fetch_ddg_news(query, limit=5)

    # ── Deduplicate by title prefix (first 60 chars) ──────────────────────────
    seen: set[str] = set()
    unique: list[dict] = []
    for a in articles:
        key = (a.get("title") or "")[:60].lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(a)

    _save_news_cache(unique)
    return unique[:max_items]


# ══════════════════════════════════════════════════════════════════════════════
# DRI helpers
# ══════════════════════════════════════════════════════════════════════════════

def _load_dri() -> dict:
    try:
        with open(_DRI_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _dri_key(sex: str, age: int) -> str:
    s = "male" if sex.lower() in ("male", "m") else "female"
    if age < 31:
        bracket = "19_30"
    elif age < 51:
        bracket = "31_50"
    else:
        bracket = "51plus"
    return f"{s}_{bracket}"


def get_dri(sex: str, age: int) -> dict:
    """Return DRI dict for the given demographic."""
    dri_table = _load_dri()
    key = _dri_key(sex, age)
    return dri_table.get(key, dri_table.get("male_31_50", {}))


# ══════════════════════════════════════════════════════════════════════════════
# Micronutrient analysis from meal plan
# ══════════════════════════════════════════════════════════════════════════════

def _load_foods() -> list[dict]:
    """Load the USDA-based micronutrient CSV as a list of dicts."""
    import csv
    if not os.path.exists(_FOODS_PATH):
        return []
    foods = []
    try:
        with open(_FOODS_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                foods.append(row)
    except Exception:
        pass
    return foods


def _match_food(ingredient_str: str, foods: list[dict]) -> dict | None:
    """Find the best food entry for a raw ingredient string using substring matching."""
    ingredient_lower = ingredient_str.lower().strip()
    # Exact substring match (food name in ingredient, or ingredient in food name)
    best: dict | None = None
    best_len = 0
    for food in foods:
        fname = food["food_name"].lower()
        # Score by how much of the food name appears in the ingredient string
        if fname in ingredient_lower:
            if len(fname) > best_len:
                best = food
                best_len = len(fname)
        elif any(word in ingredient_lower for word in fname.split() if len(word) > 3):
            candidate_len = max(
                (len(w) for w in fname.split() if w in ingredient_lower and len(w) > 3),
                default=0,
            )
            if candidate_len > best_len:
                best = food
                best_len = candidate_len
    return best


def _parse_ingredients(meal_plan: list[dict]) -> list[str]:
    """Extract ingredient strings from meal plan records."""
    raw: list[str] = []
    for meal in meal_plan:
        ing_field = meal.get("ingredients") or meal.get("RecipeIngredientParts") or ""
        if isinstance(ing_field, str) and ing_field:
            # Split on commas or semicolons; strip list markers
            parts = re.split(r"[,;|]", ing_field)
            for p in parts:
                p = re.sub(r"^[\s\-\*\d\.]+", "", p).strip()
                if len(p) > 2:
                    raw.append(p)
        elif isinstance(ing_field, list):
            raw.extend([str(i).strip() for i in ing_field if str(i).strip()])
    return raw


def analyze_nutrients(meal_plan: list[dict], measurements: dict) -> dict:
    """Compute estimated daily micronutrient intake from meal plan.

    Returns::

        {
          "daily_intake":   {"vitamin_d_iu": 320, ...},   # estimated per-day
          "dri":            {"vitamin_d_iu": 600, ...},   # target for this user
          "coverage_pct":   {"vitamin_d_iu": 53, ...},    # % of DRI met
          "meal_days":      7,
          "matched_foods":  ["salmon", "spinach", ...],
        }
    """
    sex = measurements.get("sex", "male")
    age = int(measurements.get("age", 30))
    days = max(1, len(set(m.get("Day", "Day 1") for m in meal_plan)) if meal_plan else 7)

    dri = get_dri(sex, age)
    foods = _load_foods()
    if not foods:
        return {"daily_intake": {}, "dri": dri, "coverage_pct": {}, "meal_days": days, "matched_foods": []}

    ingredient_strings = _parse_ingredients(meal_plan)

    # Sum nutrients across all matched foods (over the full plan period)
    totals: dict[str, float] = {k: 0.0 for k in NUTRIENT_KEYS}
    matched_names: list[str] = []

    for ing_str in ingredient_strings:
        food = _match_food(ing_str, foods)
        if food is None:
            continue
        fname = food["food_name"]
        if fname not in matched_names:
            matched_names.append(fname)
        portion = float(food.get("default_portion_g") or 100) / 100.0
        for key in NUTRIENT_KEYS:
            try:
                totals[key] += float(food.get(key) or 0) * portion
            except (ValueError, TypeError):
                pass

    # Divide by number of days → daily average
    daily: dict[str, float] = {k: round(v / days, 2) for k, v in totals.items()}

    # Coverage %
    coverage: dict[str, float] = {}
    for key in NUTRIENT_KEYS:
        target = float(dri.get(key) or 1)
        coverage[key] = round(min(daily.get(key, 0) / target * 100, 200), 1)

    return {
        "daily_intake":  daily,
        "dri":           dri,
        "coverage_pct":  coverage,
        "meal_days":     days,
        "matched_foods": matched_names[:20],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Extended nutrient estimation — USDA FoodData Central API + Groq fallback
#
# Flow per ingredient:
#   1. Parse ingredient string → (food_name, portion_grams)
#   2. Query USDA FDC API → nutrient values per 100 g  (measured lab data)
#   3. Scale: actual_intake = value_per_100g × (portion_g / 100)
#   4. Sum all meals, divide by plan days → daily average
#   5. Groq fallback for any ingredient the USDA can't match
# ══════════════════════════════════════════════════════════════════════════════

_USDA_API_BASE  = "https://api.nal.usda.gov/fdc/v1"
_USDA_DEMO_KEY  = "DEMO_KEY"          # 30 req/hour, no registration needed
_USDA_CACHE: dict[str, dict | None] = {}  # in-memory per-session cache

# USDA FoodData Central nutrient IDs for the 13 extended nutrients
# Source: https://fdc.nal.usda.gov/data-documentation.html
_USDA_NUTRIENT_IDS: dict[str, int] = {
    "vit_a_mcg_rae": 1106,   # Vitamin A, RAE
    "vit_b1_mg":     1165,   # Thiamin
    "vit_b2_mg":     1166,   # Riboflavin
    "vit_b3_mg_ne":  1167,   # Niacin
    "vit_b5_mg":     1170,   # Pantothenic acid
    "vit_b6_mg":     1175,   # Vitamin B6
    "vit_b7_mcg":    1176,   # Biotin
    "vit_e_mg":      1109,   # Vitamin E (alpha-tocopherol)
    "choline_mg":    1180,   # Choline
    "copper_mcg":    1098,   # Copper
    "iodine_mcg":    1100,   # Iodine
    "manganese_mg":  1101,   # Manganese
    "phosphorus_mg": 1091,   # Phosphorus
}

# ── Unit → grams conversion table ────────────────────────────────────────────
_UNIT_TO_G: dict[str, float] = {
    "cup": 240, "cups": 240,
    "tbsp": 15, "tablespoon": 15, "tablespoons": 15,
    "tsp": 5,   "teaspoon": 5,   "teaspoons": 5,
    "oz": 28.35, "ounce": 28.35, "ounces": 28.35,
    "lb": 453.6, "pound": 453.6, "pounds": 453.6,
    "g": 1,      "gram": 1,      "grams": 1,
    "kg": 1000,
    "ml": 1,     "milliliter": 1, "milliliters": 1,
    "l": 1000,   "liter": 1000,   "liters": 1000,
    "slice": 30, "slices": 30,
    "clove": 5,  "cloves": 5,
    "piece": 100, "pieces": 100,
    "handful": 30,
    "can": 400,
    "bunch": 150,
    "fillet": 150,
}

# ── Default portion sizes (grams) when no quantity/unit is given ─────────────
_DEFAULT_PORTIONS: dict[str, float] = {
    # proteins
    "egg": 50, "eggs": 50,
    "chicken": 120, "beef": 120, "pork": 120, "lamb": 120,
    "salmon": 120, "tuna": 120, "fish": 120, "shrimp": 100,
    "turkey": 120, "ham": 80,
    # dairy
    "milk": 240, "cheese": 30, "yogurt": 170, "butter": 14,
    "cream": 30, "mozzarella": 30,
    # grains
    "rice": 45, "pasta": 56, "bread": 30, "oats": 40,
    "flour": 30, "quinoa": 45, "couscous": 45,
    # vegetables
    "onion": 80, "garlic": 5, "tomato": 100, "spinach": 30,
    "carrot": 60, "potato": 150, "sweet potato": 130,
    "pepper": 80, "broccoli": 80, "mushroom": 70,
    "lettuce": 30, "cucumber": 100, "zucchini": 100,
    # fruits
    "apple": 180, "banana": 120, "orange": 140,
    "lemon": 60, "avocado": 70, "berries": 80,
    # fats / condiments
    "olive oil": 13, "oil": 13,
    "salt": 2, "pepper": 1,
    # fallback
    "_default": 100,
}


def _parse_ingredient(raw: str) -> tuple[str, float]:
    """Parse an ingredient string into (food_name, portion_grams).

    Examples
    --------
    "2 cups rice"         → ("rice", 480.0)
    "1/2 cup diced onion" → ("diced onion", 120.0)
    "3 oz salmon"         → ("salmon", 85.0)
    "eggs"                → ("eggs", 50.0)   ← default portion
    "100 g spinach"       → ("spinach", 100.0)
    """
    s = raw.strip().lower()
    # Remove parenthetical notes like "(chopped)" or "(optional)"
    s = re.sub(r"\(.*?\)", "", s).strip()

    # Pattern: optional number(s) + optional unit + food name
    # Handles: "2 cups", "1/2 cup", "1.5 oz", "½ tsp", etc.
    m = re.match(
        r"^([\d/.\s½¼¾⅓⅔⅛⅜⅝⅞]+)\s*"    # quantity (group 1)
        r"([a-z]+\.?)?\s*"               # unit (group 2, optional)
        r"(.+)$",                         # food name (group 3)
        s,
    )
    if m:
        qty_str  = m.group(1).strip()
        unit_str = (m.group(2) or "").strip().rstrip(".")
        food_raw = (m.group(3) or "").strip()

        # Parse quantity, handle fractions
        qty_str = (qty_str
                   .replace("½", "0.5").replace("¼", "0.25")
                   .replace("¾", "0.75").replace("⅓", "0.333")
                   .replace("⅔", "0.667").replace("⅛", "0.125"))
        try:
            # e.g. "1 1/2" → 1.5,  "3/4" → 0.75
            parts = qty_str.split()
            qty = sum(eval(p) for p in parts)  # noqa: S307  (safe: only digits / /)
        except Exception:
            qty = 1.0

        if unit_str and unit_str in _UNIT_TO_G:
            return food_raw, qty * _UNIT_TO_G[unit_str]

        # unit not recognised → treat as part of food name
        food_raw = f"{unit_str} {food_raw}".strip() if unit_str else food_raw

    else:
        # No leading number — entire string is the food name
        food_raw = s
        qty = 1.0

    # Look up default portion for this food
    for key, grams in _DEFAULT_PORTIONS.items():
        if key != "_default" and key in food_raw:
            return food_raw, float(grams)
    return food_raw, float(_DEFAULT_PORTIONS["_default"])


def _usda_lookup(food_name: str) -> dict[str, float] | None:
    """Query USDA FoodData Central for *food_name*.

    Returns ``{nutrient_key: value_per_100g}`` using measured Foundation/SR
    Legacy data, or ``None`` if no match is found.
    Results are cached in ``_USDA_CACHE`` for the server lifetime.
    """
    cache_key = food_name.lower().strip()
    if cache_key in _USDA_CACHE:
        return _USDA_CACHE[cache_key]

    try:
        resp = requests.get(
            f"{_USDA_API_BASE}/foods/search",
            params={
                "query":    food_name,
                "api_key":  _USDA_DEMO_KEY,
                "dataType": "Foundation,SR Legacy",
                "pageSize": 3,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            _USDA_CACHE[cache_key] = None
            return None

        foods = resp.json().get("foods", [])
        if not foods:
            _USDA_CACHE[cache_key] = None
            return None

        # Build nutrient_id → value map from the best-ranked result
        best = foods[0]
        id_to_val: dict[int, float] = {
            n["nutrientId"]: float(n.get("value") or 0)
            for n in best.get("foodNutrients", [])
            if n.get("value") is not None
        }

        result = {
            key: id_to_val[nid]
            for key, nid in _USDA_NUTRIENT_IDS.items()
            if nid in id_to_val
        }

        _USDA_CACHE[cache_key] = result or None
        return result or None

    except Exception as exc:
        print(f"[body] USDA lookup failed for '{food_name}': {exc}")
        _USDA_CACHE[cache_key] = None
        return None


# ── Groq fallback prompt (only for USDA-unmatched ingredients) ───────────────

_GROQ_FALLBACK_PROMPT = """\
You are a nutrition scientist with access to USDA FoodData Central values.

These ingredients could NOT be found in the USDA database (they may be brand names
or regional foods): {ingredients}

For each, estimate the average contribution to DAILY nutrient intake based on a
typical serving size and standard food composition values.

Return ONLY a valid JSON object with these keys (float values, no units):
{{
  "vit_a_mcg_rae": 0, "vit_b1_mg": 0, "vit_b2_mg": 0,
  "vit_b3_mg_ne": 0,  "vit_b5_mg": 0, "vit_b6_mg": 0,
  "vit_b7_mcg": 0,    "vit_e_mg": 0,  "choline_mg": 0,
  "copper_mcg": 0,    "iodine_mcg": 0,"manganese_mg": 0,
  "phosphorus_mg": 0
}}
Return ONLY the JSON, no other text."""


def _groq_fallback(unmatched_foods: list[str], api_key: str) -> dict[str, float]:
    """Ask Groq to estimate nutrients for USDA-unmatched ingredients only."""
    if not unmatched_foods or not api_key:
        return {}
    ing_text = ", ".join(unmatched_foods[:20])
    try:
        from core.groq_client import make_groq_client
        client = make_groq_client(api_key)
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{
                "role": "user",
                "content": _GROQ_FALLBACK_PROMPT.format(ingredients=ing_text),
            }],
            temperature=0,
            max_tokens=300,
        )
        raw = resp.choices[0].message.content or ""
        hit = re.search(r"\{[\s\S]*\}", raw)
        if not hit:
            return {}
        data = json.loads(hit.group())
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except Exception as exc:
        print(f"[body] Groq fallback error: {exc}")
        return {}


def estimate_extended_nutrients(meal_plan: list[dict], api_key: str = "") -> dict:
    """Estimate 13 extended nutrients using USDA FoodData Central + Groq fallback.

    Algorithm
    ---------
    For every ingredient in the meal plan:

      1. Parse string → (food_name, portion_grams)
            "2 cups rice"  →  ("rice", 480 g)
            "salmon"       →  ("salmon", 120 g)  [default portion]

      2. USDA FDC API → nutrients per 100 g  (measured lab values)

      3. Scale to actual portion:
            intake = nutrient_per_100g × (portion_g / 100)

      4. Sum across all meals, divide by plan days → daily average

    Any ingredient the USDA can't match is handed to Groq as a last resort.

    Returns ``{nutrient_key: daily_float}``  — same keys the frontend DRI table expects.
    """
    days = max(1, len({m.get("Day", "Day 1") for m in meal_plan}))

    # Collect all raw ingredient strings across the full plan
    all_ingredients: list[str] = []
    for meal in meal_plan:
        raw = meal.get("ingredients", "")
        if raw:
            for part in str(raw).split(","):
                s = part.strip()
                if s:
                    all_ingredients.append(s)

    if not all_ingredients:
        return {}

    totals: dict[str, float] = {k: 0.0 for k in _USDA_NUTRIENT_IDS}
    unmatched_foods: list[str] = []

    for ing_str in all_ingredients:
        food_name, portion_g = _parse_ingredient(ing_str)
        nutrients_per_100g = _usda_lookup(food_name)

        if nutrients_per_100g:
            scale = portion_g / 100.0
            for key, val in nutrients_per_100g.items():
                totals[key] = totals.get(key, 0.0) + val * scale
            print(f"[body] USDA OK  {food_name!r:30s}  {portion_g:.0f}g")
        else:
            unmatched_foods.append(food_name)
            print(f"[body] USDA --  {food_name!r:30s}  -> Groq fallback")

    # Daily averages from USDA data
    daily: dict[str, float] = {k: round(v / days, 2) for k, v in totals.items() if v > 0}

    # Groq fills in nutrients for unmatched ingredients (additive, not replacing USDA)
    if unmatched_foods:
        groq_extras = _groq_fallback(list(set(unmatched_foods)), api_key)
        for key, val in groq_extras.items():
            if val and val > 0:
                daily[key] = round(daily.get(key, 0.0) + val, 2)

    return daily


# ══════════════════════════════════════════════════════════════════════════════
# Supplement gap analysis
# ══════════════════════════════════════════════════════════════════════════════

def _load_blueprint() -> dict:
    try:
        with open(_BLUEPRINT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def get_supplement_gaps(nutrient_coverage: dict, measurements: dict) -> list[dict]:
    """Return ranked list of supplement recommendations based on DRI gaps.

    Each recommendation dict::

        {
          "name":        "Vitamin D3",
          "dose":        "2000 IU",
          "priority":    "high" | "medium" | "low",
          "gap_pct":     47,         # how far below DRI (%)
          "rationale":   "...",
          "blueprint":   True,       # whether Bryan Johnson recommends it
        }
    """
    blueprint = _load_blueprint()
    bp_by_key: dict[str, dict] = {
        s["nutrient_key"]: s
        for s in blueprint.get("supplements", [])
        if s.get("nutrient_key")
    }

    coverage = nutrient_coverage.get("coverage_pct", {})
    recs: list[dict] = []

    # Blueprint supplements with no nutrient key (creatine, lycopene)
    for supp in blueprint.get("supplements", []):
        if supp.get("nutrient_key"):
            continue
        recs.append({
            "name":      supp["name"],
            "dose":      supp["dose"],
            "priority":  "medium",
            "gap_pct":   None,
            "rationale": supp.get("rationale", ""),
            "blueprint": True,
        })

    # Nutrient-keyed supplements — sorted by gap severity
    nutrient_recs: list[dict] = []
    for key in NUTRIENT_KEYS:
        pct = float(coverage.get(key, 100))
        if pct >= 90:
            continue  # sufficiently covered by diet

        gap = round(100 - pct, 0)
        bp = bp_by_key.get(key, {})

        if gap >= 60:
            priority = "high"
        elif gap >= 30:
            priority = "medium"
        else:
            priority = "low"

        # Get display name from meta
        label = next((lbl for k, lbl, *_ in NUTRIENT_META if k == key), key)
        nutrient_recs.append({
            "name":         bp.get("name") or label,
            "dose":         bp.get("dose") or "per DRI",
            "priority":     priority,
            "gap_pct":      gap,
            "rationale":    bp.get("rationale") or f"Diet provides only {round(pct)}% of daily requirement.",
            "blueprint":    key in bp_by_key,
            "nutrient_key": key,   # NUTRIENT_META key — used by frontend to map dose → DRI column
        })

    # Sort by gap severity desc
    nutrient_recs.sort(key=lambda r: r.get("gap_pct") or 0, reverse=True)

    all_recs = nutrient_recs + recs
    # Attach Amazon search URL to every supplement
    for rec in all_recs:
        query = rec["name"].replace(" ", "+")
        rec["amazon_url"] = f"https://www.amazon.com/s?k={query}+supplement"
    return all_recs


# ══════════════════════════════════════════════════════════════════════════════
# Body Coach — context-aware nutrition assistant embedded in Body Optimizer tab
# ══════════════════════════════════════════════════════════════════════════════

_COACH_SYSTEM_TEMPLATE = """\
You are a personal nutrition and health coach embedded in a Grocery Shopping Optimizer app.
You have DIRECT ACCESS to this user's real health data — use it in every reply.

USER PROFILE:
  Sex: {sex} | Age: {age} | Weight: {weight_kg} kg | Height: {height_cm} cm
  Activity: {activity} | BMI: {bmi:.1f} | TDEE: {tdee} kcal/day

CURRENT NUTRIENT COVERAGE (% of DRI met by their meal plan):
{coverage_summary}

TOP SUPPLEMENT GAPS (ranked by severity):
{supplement_summary}

RULES:
1. Be concise — 2-5 sentences or a short bullet list unless asked for more.
2. Reference the user's ACTUAL numbers above (don't invent values).
3. If you suggest a supplement, always include an Amazon link using this format:
   [Buy on Amazon](https://www.amazon.com/s?k=PRODUCT+NAME+supplement)
4. If you recommend adding a food to the meal plan or buying a Mercadona product, end your
   response with:
---ACTIONS---
[{{"type":"amazon","label":"Buy <supplement name>","url":"https://www.amazon.com/s?k=<query>+supplement"}},
 {{"type":"add","label":"Add <product> to basket","query":"<mercadona search term>"}}]

   Only include actions that directly follow from your recommendation.
5. NEVER repeat analysis you already gave in this conversation — answer the specific question.
6. NEVER invent nutrient values — only cite numbers from the USER PROFILE section above.
"""


def _build_coach_system(profile: dict, nutrient_data: dict, supplements: list[dict]) -> str:
    """Render the Body Coach system prompt with real user data injected."""
    sex        = profile.get("sex", "male")
    age        = int(profile.get("age", 30))
    weight_kg  = float(profile.get("weight_kg", 75))
    height_cm  = float(profile.get("height_cm", 175))
    activity   = profile.get("activity", "moderate")

    # Mifflin–St Jeor BMR
    if sex == "female":
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5

    _ACT = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55,
            "active": 1.725, "very_active": 1.9}
    tdee = round(bmr * _ACT.get(activity, 1.55))
    bmi  = weight_kg / ((height_cm / 100) ** 2)

    # Coverage summary — show all nutrients with their %
    coverage = (nutrient_data or {}).get("coverage_pct", {})
    if coverage:
        lines = []
        for key, pct in sorted(coverage.items(), key=lambda x: x[1]):
            label = next((lbl for k, lbl, *_ in NUTRIENT_META if k == key), key)
            status = "LOW" if pct < 60 else ("OK" if pct >= 90 else "moderate")
            lines.append(f"  {label}: {pct:.0f}% [{status}]")
        coverage_summary = "\n".join(lines) if lines else "  (Run 'Analyze My Nutrients' first)"
    else:
        coverage_summary = "  (Run 'Analyze My Nutrients' first to populate real data)"

    # Supplement summary
    if supplements:
        supp_lines = [
            f"  {s['name']} — {s['dose']} (gap: {s.get('gap_pct') or 'N/A'}%, priority: {s['priority']})"
            for s in supplements[:8]
        ]
        supplement_summary = "\n".join(supp_lines)
    else:
        supplement_summary = "  (No significant gaps detected, or analysis not yet run)"

    return _COACH_SYSTEM_TEMPLATE.format(
        sex=sex, age=age, weight_kg=weight_kg, height_cm=height_cm,
        activity=activity, bmi=bmi, tdee=tdee,
        coverage_summary=coverage_summary,
        supplement_summary=supplement_summary,
    )


def body_coach_chat(
    message: str,
    history: list[dict],
    profile: dict,
    nutrient_data: dict,
    supplements: list[dict],
    api_key: str,
) -> str:
    """Run one turn of the Body Coach agent.

    Args:
        message:      Latest user message.
        history:      Previous turns [{role, content}, ...].
        profile:      User measurements dict (sex, age, weight_kg, height_cm, activity).
        nutrient_data: Output of ``analyze_nutrients()`` (coverage_pct, daily_intake, …).
        supplements:  Output of ``get_supplement_gaps()`` (list of supplement dicts).
        api_key:      Groq API key.

    Returns:
        Raw assistant reply (may contain ``---ACTIONS---`` block).
    """
    if not api_key:
        return "Please enter your Groq API key in Settings to use the Body Coach."

    system_prompt = _build_coach_system(profile, nutrient_data, supplements)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    # Include up to last 20 history turns
    for turn in (history or [])[-20:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    try:
        from core.groq_client import make_groq_client
        client = make_groq_client(api_key)
        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.4,
            max_tokens=600,
        )
        return resp.choices[0].message.content or "(no response)"
    except Exception as exc:
        return f"Coach error: {exc}"
