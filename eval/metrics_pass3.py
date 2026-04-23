"""Pass-3 (SKU selection) metrics.

Each prediction is scored against the ground-truth ``acceptable_skus`` tie
set — the LLM gets credit if its choice is in that set, not only if it
matches ``expected_sku`` verbatim. This is critical: with ``temperature=0``
there's still ambiguity in equally-valid SKUs and the acceptable-set
captures that fairly.

Includes a ``match_quality`` metric + 3×3 confusion matrix comparing the
tag predicted by the pipeline against the expected tag from labelling.
"""
from __future__ import annotations

import math
from typing import Any

from eval.metrics_util import wilson_interval


def _same_size(a: dict, b: dict) -> bool:
    """Pack-size equality with 5% tolerance to absorb labelling slop."""
    av = float(a.get("value", 0) or 0)
    bv = float(b.get("value", 0) or 0)
    if a.get("unit") != b.get("unit"):
        return False
    if max(av, bv) == 0:
        return av == bv
    return abs(av - bv) / max(av, bv) <= 0.05


def score_pass3(predictions: list[dict], ground_truth: list[dict]) -> dict:
    """Score N predictions vs N ground-truth rows.

    Each prediction dict should have keys:
        ingredient, product_name, pack_size_value, pack_size_unit,
        packs_needed, unit_price, total_price, match_quality,
        top1_tfidf_score (optional — used for candidate_set_recall bound)

    Each ground-truth dict:
        id, ingredient, candidates, expected_sku, expected_pack_size,
        expected_packs, acceptable_skus, expected_match_quality
    """
    assert len(predictions) == len(ground_truth), "length mismatch"
    n = len(predictions)

    # Top-1 accuracy (predicted SKU in acceptable set).
    top1 = 0
    # Candidate-set recall: was the GT SKU in the TF-IDF top-5 at all?
    cand_recall = 0
    # Pack-size accuracy.
    ps_hits = 0
    ps_n = 0
    # Packs-needed exact match.
    packs_hits = 0
    packs_n = 0
    # Price consistency (packs × unit = total).
    price_hits = 0
    # Hallucination: predicted SKU not in candidates.
    halluc = 0
    # Fallback trigger rate (reported by the pipeline if "_source" is attached).
    fallback_n = 0
    # Match-quality.
    mq_hits = 0
    mq_confusion: dict[str, dict[str, int]] = {
        t: {u: 0 for u in ("exact", "alternative", "none")}
        for t in ("exact", "alternative", "none")
    }

    for pred, gt in zip(predictions, ground_truth):
        pred_sku = (pred.get("product_name") or "").strip().lower()
        acceptable = {s.strip().lower() for s in gt.get("acceptable_skus", []) if s}
        cand_names = {str(c.get("name", "")).strip().lower() for c in gt.get("candidates", [])}

        if pred_sku and pred_sku in acceptable:
            top1 += 1

        expected_sku_lc = (gt.get("expected_sku") or "").strip().lower()
        if expected_sku_lc in cand_names or any(s in cand_names for s in acceptable):
            cand_recall += 1

        # Hallucination: predicted SKU exists but not in candidates.
        if pred_sku and pred_sku not in cand_names and pred_sku != "not found":
            halluc += 1

        # Pack size.
        if gt.get("expected_pack_size"):
            ps_n += 1
            ps_pred = {
                "value": pred.get("pack_size_value", 0),
                "unit": pred.get("pack_size_unit", ""),
            }
            if _same_size(ps_pred, gt["expected_pack_size"]):
                ps_hits += 1

        # Packs-needed.
        if gt.get("expected_packs") is not None:
            packs_n += 1
            if int(pred.get("packs_needed", -1)) == int(gt["expected_packs"]):
                packs_hits += 1

        # Price consistency.
        try:
            expected = float(pred.get("packs_needed", 0)) * float(pred.get("unit_price", 0))
            if abs(expected - float(pred.get("total_price", 0))) <= 0.02:
                price_hits += 1
        except (TypeError, ValueError):
            pass

        # Fallback source.
        if str(pred.get("_source", "llm")) != "llm":
            fallback_n += 1

        # Match quality.
        pred_mq = pred.get("match_quality", "exact")
        exp_mq = gt.get("expected_match_quality", "exact")
        if pred_mq == exp_mq:
            mq_hits += 1
        if pred_mq in mq_confusion and exp_mq in mq_confusion[pred_mq]:
            # confusion[predicted][expected] — columns = expected, rows = predicted
            mq_confusion[pred_mq][exp_mq] += 1

    def _pack(k: int, total: int) -> dict:
        return {
            "value": k / total if total else 0.0,
            "n": total,
            "ci95": wilson_interval(k, total),
        }

    return {
        "n": n,
        "top1_sku_accuracy": _pack(top1, n),
        "candidate_set_recall": _pack(cand_recall, n),
        "pack_size_accuracy": _pack(ps_hits, ps_n),
        "packs_needed_exact": _pack(packs_hits, packs_n),
        "price_consistency": _pack(price_hits, n),
        "hallucination_rate": _pack(halluc, n),
        "fallback_trigger_rate": _pack(fallback_n, n),
        "match_quality_accuracy": _pack(mq_hits, n),
        "match_quality_confusion": mq_confusion,
    }
