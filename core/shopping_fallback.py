"""Deterministic rule-based fallbacks for Pass 1 and Pass 3.

Activated per-item whenever the LLM output fails schema validation or any
guard, and run exclusively for the pure-baseline path in ``eval/baselines.py``.
The numbers here intentionally mirror the unit table in the Pass-1 LLM
prompt (see ``core/shopping.py``) so the two code paths stay comparable.
"""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import List, Tuple

# ── Unit dictionary (mirrors Pass-1 prompt conversions) ──────────────────────
# value = (grams_or_ml, unit)
#   unit="g"  → solid/powder/spice
#   unit="ml" → liquid
#   unit="unit" → naturally-counted item
_CUP_MAP = {
    "flour": 125, "sugar": 200, "rice": 185,
    "chopped": 150, "diced": 150, "sliced": 150,
    "default_solid": 150, "default_liquid": 240,
}

_UNITS = {
    "tbsp": 15, "tablespoon": 15, "tablespoons": 15,
    "tsp": 5, "teaspoon": 5, "teaspoons": 5,
    "lb": 454, "lbs": 454, "pound": 454, "pounds": 454,
    "oz": 28, "ounce": 28, "ounces": 28,
    "kg": 1000, "g": 1, "gram": 1, "grams": 1,
    "l": 1000, "ml": 1, "millilitre": 1, "millilitres": 1,
    "liter": 1000, "liters": 1000, "litre": 1000, "litres": 1000,
}

# Items that are "naturally counted"
_COUNT_ITEMS = {
    "egg", "eggs", "onion", "onions", "carrot", "carrots",
    "tomato", "tomatoes", "potato", "potatoes", "apple", "apples",
    "clove", "cloves", "lemon", "lemons", "lime", "limes",
    "banana", "bananas", "pepper", "peppers", "bell pepper",
    "garlic clove", "slice", "slices",
}

_LIQUID_HINTS = {"oil", "milk", "water", "juice", "stock", "broth", "vinegar", "sauce", "wine", "cream", "yogurt"}

# Per-unit weights for naturally-counted items (used when a user writes
# "2 onions" with no weight unit).
_UNIT_WEIGHTS = {
    "onion": 150, "carrot": 80, "clove": 5, "egg": 50, "tomato": 120,
    "potato": 200, "apple": 180, "lemon": 100, "lime": 70, "banana": 120,
    "pepper": 160, "bell pepper": 160, "garlic clove": 5, "slice": 30,
}

# Pantry items below these thresholds get dropped (pantry-staple heuristic).
_NEGLIGIBLE = [("salt", 5, "g"), ("pepper", 2, "g"), ("vanilla", 5, "ml")]

_QTY_RE = re.compile(r"^\s*-?\s*([\d./\s]+)?\s*([a-zA-Z]+)?\s*(.*)$")
_FRAC_RE = re.compile(r"(\d+)?\s*(\d+)\s*/\s*(\d+)")


def _parse_qty(num_str: str) -> float:
    """Parse ``"1/2"``, ``"1 1/2"``, ``"2"`` etc → float."""
    s = (num_str or "").strip()
    if not s:
        return 0.0
    m = _FRAC_RE.match(s)
    if m:
        whole = int(m.group(1)) if m.group(1) else 0
        return float(whole) + int(m.group(2)) / int(m.group(3))
    try:
        return float(Fraction(s))
    except Exception:
        try:
            return float(s)
        except Exception:
            return 0.0


def _canonical_name(raw: str) -> str:
    """Drop adjectives and normalise to lowercase singular-ish form."""
    s = raw.strip().lower()
    for adj in ("fresh", "chopped", "diced", "sliced", "minced",
                "boneless", "skinless", "raw", "cooked", "frozen",
                "ripe", "large", "small", "medium", "whole", "ground"):
        s = re.sub(rf"\b{adj}\b", "", s)
    # Drop parentheticals, extra whitespace.
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\s+", " ", s).strip(" ,.-")
    # Crude plural → singular for the most common words.
    if s.endswith("ies"):
        s = s[:-3] + "y"
    elif s.endswith("es") and not s.endswith("ses"):
        s = s[:-2]
    elif s.endswith("s") and not s.endswith("ss"):
        s = s[:-1]
    return s


def _classify_unit(name: str, explicit_unit: str) -> str:
    """Decide the target unit (g | ml | unit) for a canonical ingredient."""
    if explicit_unit in {"g", "grams", "gram", "kg", "lb", "lbs", "oz", "pound", "pounds", "ounce", "ounces"}:
        return "g"
    if explicit_unit in {"ml", "l", "liter", "liters", "litre", "litres", "millilitre", "millilitres"}:
        return "ml"
    if name in _COUNT_ITEMS or any(n in name for n in _COUNT_ITEMS):
        return "unit"
    if any(h in name for h in _LIQUID_HINTS):
        return "ml"
    return "g"


def _convert_one(qty: float, qty_unit: str, name: str) -> Tuple[float, str]:
    """Return (value_in_target_unit, target_unit) for a single raw line."""
    target = _classify_unit(name, qty_unit)

    # No explicit qty → assume 1 standard serving.
    if qty == 0:
        if target == "unit":
            return 1.0, "unit"
        if target == "ml":
            return 240.0, "ml"  # 1 cup default
        # Spice heuristic: bare ingredient → 1 tsp
        return 5.0, "g"

    unit_lc = (qty_unit or "").strip().lower()

    # Cup — context sensitive.
    if unit_lc in {"cup", "cups", "c"}:
        if target == "ml":
            return qty * _CUP_MAP["default_liquid"], "ml"
        # Solid
        for key, grams in _CUP_MAP.items():
            if key in name:
                return qty * grams, "g"
        return qty * _CUP_MAP["default_solid"], "g"

    # Known mass/volume units.
    if unit_lc in _UNITS:
        base = qty * _UNITS[unit_lc]
        # If the unit is volume but the ingredient is solid-by-default,
        # keep it ml → g via 1:1 (the LLM prompt does the same heuristic).
        if unit_lc in {"ml", "l", "liter", "liters", "litre", "litres"}:
            return base, "ml"
        return base, "g"

    # Count items.
    if target == "unit":
        return qty, "unit"

    # Unknown unit — assume "unit".
    return qty, "unit"


def rule_based_consolidate(raw_lines: List[str]) -> List[dict]:
    """Pure-Python consolidation of a batch of raw ingredient lines.

    Mirrors Pass-1 LLM behaviour: groups variants by canonical name,
    sums into the same target unit, drops negligible pantry staples.
    Returns a list of ``{"name": str, "total": float, "unit": str}``.
    """
    buckets: dict[str, Tuple[float, str]] = {}
    for line in raw_lines or []:
        s = (line or "").lstrip("-• ").strip()
        if not s:
            continue
        m = _QTY_RE.match(s)
        if not m:
            continue
        qty_s, maybe_unit, rest = m.group(1), m.group(2), m.group(3)
        # If the second token isn't a known unit word, it's actually part of the name.
        if maybe_unit and maybe_unit.lower() not in _UNITS and maybe_unit.lower() not in {"cup", "cups", "c"}:
            rest = f"{maybe_unit} {rest}".strip()
            maybe_unit = ""
        qty = _parse_qty(qty_s or "")
        name = _canonical_name(rest or (maybe_unit or ""))
        if not name:
            continue

        value, target_unit = _convert_one(qty, maybe_unit or "", name)

        if name in buckets:
            prev_val, prev_unit = buckets[name]
            if prev_unit != target_unit:
                # Keep the first unit; coarse — just skip the conflicting one.
                continue
            buckets[name] = (prev_val + value, prev_unit)
        else:
            buckets[name] = (value, target_unit)

    out: list[dict] = []
    for name, (val, unit) in buckets.items():
        # Drop pantry-staple negligibles.
        negligible = False
        for kw, lim, u in _NEGLIGIBLE:
            if kw in name and unit == u and val < lim:
                negligible = True
                break
        if negligible:
            continue
        # Round to sensible precision.
        if unit == "unit":
            val = int(round(val))
        else:
            val = int(round(val))
        out.append({"name": name, "total": float(val), "unit": unit})
    return out


# ── Pass 3 fallback ──────────────────────────────────────────────────────────

_CAND_SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|kg|ml|l|ud)\b", re.IGNORECASE)


def _extract_pack_size(candidate_name: str, ref_unit: str) -> Tuple[float, str]:
    """Infer pack size from candidate name; fall back to ``ref_unit``."""
    m = _CAND_SIZE_RE.search(candidate_name or "")
    if m:
        val = float(m.group(1).replace(",", "."))
        u = m.group(2).lower()
        if u == "kg":
            return val * 1000.0, "g"
        if u == "l":
            return val * 1000.0, "ml"
        if u == "ud":
            return val, "unit"
        return val, u
    ru = (ref_unit or "").lower().strip()
    if ru == "kg":
        return 1000.0, "g"
    if ru == "l":
        return 1000.0, "ml"
    return 1.0, "unit"


def rule_based_select(
    candidates: List[dict], ingredient: dict, people: int = 1
) -> dict:
    """Pick TF-IDF top-1, extract pack size, compute packs + total price.

    Returns the same dict shape as the LLM's Pass-3 output, plus
    ``match_quality`` (derived deterministically from the top-1 TF-IDF
    score if present in the candidate dict as ``_score``) and a
    ``match_reason`` for alternatives / missing items.
    """
    name = str(ingredient.get("name", ""))
    total = float(ingredient.get("total", 0) or 0)
    total_unit = str(ingredient.get("unit", ""))
    needed = total * max(1, int(people or 1))

    if not candidates:
        return {
            "ingredient": name,
            "total_needed": f"{int(needed)} {total_unit}",
            "product_name": "Not found",
            "pack_size": "",
            "packs_needed": 0,
            "unit_price": 0.0,
            "total_price": 0.0,
            "url": "",
            "match_quality": "none",
            "match_reason": "No Mercadona match found in catalog",
        }

    top = candidates[0]
    top_score = float(top.get("_score", 0.0) or 0.0)
    pack_val, pack_unit = _extract_pack_size(str(top.get("name", "")), str(top.get("unit", "")))
    if pack_val <= 0:
        pack_val = 1.0
        pack_unit = total_unit or "unit"

    # Convert needed into pack_unit if possible; otherwise treat 1:1.
    if total_unit != pack_unit and not (total_unit == "" or pack_unit == ""):
        # If we're mixing solids and volumes, assume 1:1 (same as the LLM prompt).
        pass

    packs = min(10, max(1, math.ceil(needed / pack_val))) if pack_val > 0 else 1
    unit_price = float(top.get("price", 0) or 0)
    total_price = round(packs * unit_price, 2)

    # Match-quality classification (same threshold logic used for LLM check).
    from core.shopping_guards import classify_match_quality
    mq = classify_match_quality(name, str(top.get("name", "")), top_score)
    reason = ""
    if mq == "alternative":
        reason = f"Closest Mercadona match for '{name}' — not an exact stock item."
    elif mq == "none":
        reason = f"No suitable Mercadona match for '{name}'."

    return {
        "ingredient": name,
        "total_needed": f"{int(needed)} {total_unit}",
        "product_name": str(top.get("name", "")),
        "pack_size": f"{int(pack_val)} {pack_unit}",
        "packs_needed": int(packs),
        "unit_price": float(unit_price),
        "total_price": float(total_price),
        "url": str(top.get("url", "") or ""),
        "match_quality": mq,
        "match_reason": reason,
    }
