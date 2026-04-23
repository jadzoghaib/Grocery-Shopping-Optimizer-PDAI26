"""Runtime guards for Pass 1 and Pass 3 LLM outputs.

Each guard is a pure function returning ``(ok: bool, reason: str)`` so the
calling code can decide per-item whether to accept the LLM output or
substitute the deterministic rule-based fallback. The match-quality
classifier returns a tag rather than a boolean because its job is to
*label*, not accept/reject.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Literal, Tuple

from core.llm_config import (
    MATCH_QUALITY_THRESHOLD_ALT,
    MATCH_QUALITY_THRESHOLD_EXACT,
)

GuardResult = Tuple[bool, str]
MatchQuality = Literal["exact", "alternative", "none"]


# ── Pass 1 guards ─────────────────────────────────────────────────────────────

def check_unit_sanity(name: str, total: float, unit: str) -> GuardResult:
    """Reject obviously absurd quantity/unit combinations.

    Example of what this catches: ``{"name": "salt", "total": 50000, "unit": "g"}``
    (50 kg of salt for a weeknight dinner). Bounds are intentionally wide —
    this is a sanity net, not a tight range check.
    """
    if not math.isfinite(total) or total < 0:
        return False, f"non-finite or negative total: {total}"
    if unit not in {"g", "ml", "unit"}:
        return False, f"unknown unit: {unit!r}"
    # Loose upper bounds per unit.
    max_by_unit = {"g": 20_000, "ml": 20_000, "unit": 300}
    if total > max_by_unit[unit]:
        return False, f"total {total}{unit} exceeds sanity bound {max_by_unit[unit]}"
    return True, "ok"


def check_coverage(raw_lines: Iterable[str], consolidated: Iterable[dict]) -> GuardResult:
    """Cheap recall check: every non-empty raw line should map to at least one
    consolidated ingredient, by substring match on the canonical name.

    This is deliberately permissive — the real coverage metric lives in
    ``eval/metrics_pass1.py``. Here we only flag catastrophic drop-outs
    (e.g. LLM returned 2 items for a 40-line batch).
    """
    raw = [l for l in raw_lines if l and l.strip()]
    if not raw:
        return True, "empty input"
    consolidated_names = [str(c.get("name", "")).lower() for c in consolidated]
    if not consolidated_names:
        return False, "empty output"
    # At least 50% of raw lines should overlap with some consolidated name.
    hit = 0
    for line in raw:
        line_l = line.lower()
        if any(cn and cn in line_l for cn in consolidated_names):
            hit += 1
    ratio = hit / len(raw)
    if ratio < 0.5:
        return False, f"low coverage: {hit}/{len(raw)} raw lines overlap ({ratio:.0%})"
    return True, f"coverage {ratio:.0%}"


# ── Pass 3 guards ─────────────────────────────────────────────────────────────

def check_hallucination(product_name: str, candidates: Iterable[dict]) -> GuardResult:
    """The chosen SKU must appear verbatim (after stripping whitespace) in the
    candidate list. Rejects hallucinated SKUs."""
    if not product_name or product_name.strip().lower() == "not found":
        return True, "not-found is allowed"
    pn = product_name.strip().lower()
    cand_names = [str(c.get("name", "")).strip().lower() for c in candidates]
    if pn in cand_names:
        return True, "ok"
    return False, f"chosen SKU {product_name!r} not in candidates"


def check_price_consistency(
    packs: float, unit_price: float, total_price: float, tol: float = 0.02
) -> GuardResult:
    """``packs × unit_price`` should equal ``total_price`` within ``tol`` euros."""
    expected = float(packs) * float(unit_price)
    diff = abs(expected - float(total_price))
    if diff <= tol:
        return True, "ok"
    return False, f"price mismatch: {packs}×{unit_price}={expected:.2f} vs total={total_price:.2f} (Δ={diff:.2f})"


_PACK_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(g|kg|ml|l|ud|unit|units)", re.IGNORECASE)


def _parse_size(s: str) -> Tuple[float, str]:
    """Extract ``(value, canonical_unit)`` from a free-form size string.

    Returns ``(0.0, "")`` if nothing parseable was found.
    """
    if not s:
        return 0.0, ""
    m = _PACK_RE.search(s)
    if not m:
        return 0.0, ""
    val = float(m.group(1))
    unit_raw = m.group(2).lower()
    if unit_raw == "kg":
        return val * 1000.0, "g"
    if unit_raw == "l":
        return val * 1000.0, "ml"
    if unit_raw in {"ud", "unit", "units"}:
        return val, "unit"
    return val, unit_raw  # g or ml


def check_pack_sizing(total_needed: str, pack_size: str, people: int, packs: float) -> GuardResult:
    """Cross-check that ``packs >= ceil(total_needed × people / pack_size)``.

    Tolerates LLM unit mismatches silently (e.g. ``total`` in g but pack in
    units) because that would be caught by ``check_unit_sanity`` instead.
    """
    tn_val, tn_unit = _parse_size(total_needed)
    ps_val, ps_unit = _parse_size(pack_size)
    if tn_val <= 0 or ps_val <= 0:
        return True, "unparseable — skipped"
    if tn_unit != ps_unit:
        return True, f"unit mismatch ({tn_unit} vs {ps_unit}) — skipped"
    needed = tn_val * max(1, int(people or 1))
    expected = math.ceil(needed / ps_val)
    if int(packs) < expected:
        return False, f"under-packed: {packs} packs < expected {expected}"
    if int(packs) > expected + 2:  # allow small over-estimate, not gross
        return False, f"over-packed: {packs} packs >> expected {expected}"
    return True, "ok"


def check_url_integrity(url: str, candidates: Iterable[dict]) -> GuardResult:
    """If a URL is set, it must match one of the candidate URLs exactly."""
    if not url:
        return True, "empty url allowed"
    cand_urls = [str(c.get("url", "")).strip() for c in candidates]
    if url.strip() in cand_urls:
        return True, "ok"
    return False, f"url not in candidate set"


# ── Match-quality classifier ──────────────────────────────────────────────────

def classify_match_quality(
    ingredient_name: str,
    chosen_name: str,
    top1_tfidf_score: float,
    threshold_exact: float = MATCH_QUALITY_THRESHOLD_EXACT,
    threshold_alt: float = MATCH_QUALITY_THRESHOLD_ALT,
) -> MatchQuality:
    """Deterministic classifier used as a cross-check against the LLM's
    self-reported ``match_quality``. On disagreement, callers should trust
    this classifier.

    Rules:
      - no chosen product or explicit "not found" → ``"none"``
      - top-1 cosine ≥ threshold_exact → ``"exact"``
      - top-1 cosine ≥ threshold_alt  → ``"alternative"``
      - otherwise                     → ``"none"``
    """
    if not chosen_name or chosen_name.strip().lower() == "not found":
        return "none"
    try:
        score = float(top1_tfidf_score)
    except (TypeError, ValueError):
        score = 0.0
    if score >= threshold_exact:
        return "exact"
    if score >= threshold_alt:
        return "alternative"
    return "none"


# ── Aggregate runner (optional convenience) ───────────────────────────────────

def run_pass3_guards(
    product: dict, candidates: Iterable[dict], people: int
) -> Tuple[bool, list[str]]:
    """Run every Pass-3 guard and collect failure reasons.

    Returns ``(all_passed, reasons_failed)``.
    """
    candidates = list(candidates)
    failures: list[str] = []
    for ok, reason, label in [
        (*check_hallucination(product.get("product_name", ""), candidates), "hallucination"),
        (*check_price_consistency(
            product.get("packs_needed", 0),
            product.get("unit_price", 0),
            product.get("total_price", 0),
        ), "price"),
        (*check_pack_sizing(
            product.get("total_needed", ""),
            product.get("pack_size", ""),
            people,
            product.get("packs_needed", 0),
        ), "pack_sizing"),
        (*check_url_integrity(product.get("url", ""), candidates), "url"),
    ]:
        if not ok:
            failures.append(f"{label}: {reason}")
    return (len(failures) == 0, failures)
