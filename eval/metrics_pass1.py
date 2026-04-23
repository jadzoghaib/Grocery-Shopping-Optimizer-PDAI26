"""Pass-1 (consolidation) metrics.

Given a list of predicted consolidations and a list of ground-truth
consolidations (both the ``list[dict]`` shape produced by the pipeline),
score the run on six metrics plus Wilson 95% confidence intervals.

Metrics are all pure-Python (no numpy/scipy) to keep the eval harness
dependency-free.
"""
from __future__ import annotations

import math
from typing import Iterable

from eval.metrics_util import wilson_interval


def _tokens(s: str) -> set[str]:
    return {t for t in (s or "").lower().replace("-", " ").split() if t}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _match_by_name(pred: list[dict], gt: list[dict]) -> list[tuple[dict | None, dict]]:
    """Greedy best-match: for each GT item find the best predicted item by
    token Jaccard ≥ 0.6. Returns [(pred_or_none, gt), …] in GT order.
    """
    used: set[int] = set()
    out: list[tuple[dict | None, dict]] = []
    for g in gt:
        best_j = 0.0
        best_i = -1
        for i, p in enumerate(pred):
            if i in used:
                continue
            j = _jaccard(str(g.get("name", "")), str(p.get("name", "")))
            if j > best_j:
                best_j = j
                best_i = i
        if best_i >= 0 and best_j >= 0.6:
            used.add(best_i)
            out.append((pred[best_i], g))
        else:
            out.append((None, g))
    return out


def score_pass1(predictions: list[list[dict]], ground_truth: list[list[dict]]) -> dict:
    """Score N batches. Both args are lists of length N; each element is a
    consolidation (list of ``{"name","total","unit"}`` dicts).
    """
    assert len(predictions) == len(ground_truth), "length mismatch"

    name_exact_hits = 0
    name_jaccard_sum = 0.0
    name_jaccard_n = 0
    name_jaccard_at60 = 0
    unit_hits = 0
    unit_n = 0
    qty_within_10pct = 0
    qty_n = 0

    total_gt = 0
    total_pred = 0
    total_matched = 0

    for pred, gt in zip(predictions, ground_truth):
        total_gt += len(gt)
        total_pred += len(pred)
        matched = _match_by_name(pred, gt)
        for p, g in matched:
            if p is None:
                continue
            total_matched += 1
            name_jaccard_n += 1
            j = _jaccard(str(g.get("name", "")), str(p.get("name", "")))
            name_jaccard_sum += j
            if j >= 0.6:
                name_jaccard_at60 += 1
            if str(g.get("name", "")).strip().lower() == str(p.get("name", "")).strip().lower():
                name_exact_hits += 1
            if str(g.get("unit", "")) == str(p.get("unit", "")):
                unit_hits += 1
            unit_n += 1
            gt_q, pr_q = float(g.get("total", 0) or 0), float(p.get("total", 0) or 0)
            if gt_q > 0:
                qty_n += 1
                if abs(gt_q - pr_q) / gt_q <= 0.10:
                    qty_within_10pct += 1

    coverage = total_matched / total_gt if total_gt else 1.0
    spurious = (total_pred - total_matched) / total_pred if total_pred else 0.0

    return {
        "n_batches": len(predictions),
        "n_gt_items": total_gt,
        "n_pred_items": total_pred,

        "name_exact_match": {
            "value": name_exact_hits / name_jaccard_n if name_jaccard_n else 0.0,
            "n": name_jaccard_n,
            "ci95": wilson_interval(name_exact_hits, name_jaccard_n),
        },
        "name_token_jaccard_mean": {
            "value": name_jaccard_sum / name_jaccard_n if name_jaccard_n else 0.0,
            "n": name_jaccard_n,
        },
        "name_jaccard_pass_at_0_6": {
            "value": name_jaccard_at60 / name_jaccard_n if name_jaccard_n else 0.0,
            "n": name_jaccard_n,
            "ci95": wilson_interval(name_jaccard_at60, name_jaccard_n),
        },
        "unit_accuracy": {
            "value": unit_hits / unit_n if unit_n else 0.0,
            "n": unit_n,
            "ci95": wilson_interval(unit_hits, unit_n),
        },
        "quantity_within_10pct": {
            "value": qty_within_10pct / qty_n if qty_n else 0.0,
            "n": qty_n,
            "ci95": wilson_interval(qty_within_10pct, qty_n),
        },
        "coverage": {
            "value": coverage,
            "n": total_gt,
            "ci95": wilson_interval(total_matched, total_gt),
        },
        "spurious_rate": {
            "value": spurious,
            "n": total_pred,
            "ci95": wilson_interval(total_pred - total_matched, total_pred),
        },
    }
