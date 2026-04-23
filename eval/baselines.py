"""Pure rule-based baseline paths for the shopping pipeline.

These functions exercise the same retrieval (Pass 2) as the live LLM path
but replace Passes 1 and 3 with the deterministic rules from
``core.shopping_fallback``. The eval harness uses them as a comparison
baseline to isolate how much the LLM actually buys us over rules.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from core.shopping import _search_bilingual_scored
from core.shopping_fallback import rule_based_consolidate, rule_based_select


def baseline_pass1(raw_lines: list[str]) -> list[dict]:
    """Wrap ``rule_based_consolidate`` — same signature & output shape."""
    return rule_based_consolidate(raw_lines)


def baseline_pass3_one(
    ingredient: dict, people_count: int = 1
) -> dict:
    """Run Pass 2 (TF-IDF) + rule-based Pass 3 for a single consolidated ingredient."""
    hits, _top = _search_bilingual_scored(ingredient.get("name", ""), top_k=5)
    cands = hits.to_dict("records") if not hits.empty else []
    return rule_based_select(cands, ingredient, people_count)


def baseline_shopping_list(
    all_items: list[dict], people_count: int = 1
) -> pd.DataFrame:
    """Full baseline: rule Pass 1 → TF-IDF Pass 2 → rule Pass 3."""
    raw_lines: list[str] = []
    for it in all_items:
        qty = str(it.get("Quantity", "")).strip()
        name = str(it.get("Ingredient", "")).strip()
        if name:
            raw_lines.append(f"- {(qty + ' ') if qty else ''}{name}")

    consolidated = baseline_pass1(raw_lines)
    rows: list[dict] = []
    for ing in consolidated:
        sel = baseline_pass3_one(ing, people_count)
        rows.append({
            "Ingredient": sel.get("ingredient", ""),
            "Qty Needed": sel.get("total_needed", ""),
            "SKU": sel.get("product_name", ""),
            "Pack Size": sel.get("pack_size", ""),
            "Count": int(sel.get("packs_needed", 0) or 0),
            "Unit Price": float(sel.get("unit_price", 0) or 0),
            "Total Price": float(sel.get("total_price", 0) or 0),
            "Link": str(sel.get("url", "") or ""),
            "match_quality": sel.get("match_quality", "exact"),
            "match_reason": sel.get("match_reason", ""),
            "_source": "baseline",
        })
    return pd.DataFrame(rows)
