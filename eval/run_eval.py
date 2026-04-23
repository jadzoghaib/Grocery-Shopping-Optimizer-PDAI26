"""End-to-end evaluation runner.

Usage::

    # First, collect live LLM responses into the cache (requires a Groq key):
    python -m eval.run_eval --mode live --out eval/results/2025-01-15/

    # Then re-run deterministically, fully offline:
    python -m eval.run_eval --mode replay --out eval/results/2025-01-15/

Produces ``metrics.json`` + ``report.md`` in ``--out``. Exit code 2 on
regression vs ``--threshold-top1`` (default 0.70).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Any

# Make sure we're running from repo-root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.llm_config import SHOPPING_MODEL  # noqa: E402
from eval.baselines import baseline_pass1, baseline_shopping_list  # noqa: E402
from eval.metrics_pass1 import score_pass1  # noqa: E402
from eval.metrics_pass3 import score_pass3  # noqa: E402
from eval.report import emit_report  # noqa: E402


_GT_DIR = os.path.join(_REPO_ROOT, "eval", "ground_truth")
_MERCADONA_CSV = os.path.join(_REPO_ROOT, "data", "mercadona_cache.csv")


def _sha256_file(path: str) -> str:
    if not os.path.exists(path):
        return "file-missing"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _build_client(mode: str, api_key: str | None):
    if mode == "replay":
        from eval.replay_client import ReplayGroqClient
        return ReplayGroqClient()
    if mode == "live":
        from groq import Groq
        if not api_key:
            raise SystemExit("--mode live requires --groq-key or GROQ_API_KEY env var")
        return Groq(api_key=api_key)
    raise SystemExit(f"unknown mode: {mode}")


def _eval_pass1(gt_examples: list[dict], mode: str, api_key: str | None) -> tuple[dict, dict, dict]:
    """Run Pass-1 LLM (through the full pipeline) + baseline on N examples.
    Returns (raw_metrics, post_metrics, baseline_metrics).

    Because the pipeline's fallback runs under the hood, we score twice:
      raw  = score against the LLM output captured by LLMLogger
      post = score against the final consolidated list the pipeline ships
    """
    # Ground-truth schemas:
    #   raw_lines: list[str], expected: list[{name,total,unit}]
    from core.shopping import _run_pass1

    client = _build_client(mode, api_key)

    raw_preds: list[list[dict]] = []
    post_preds: list[list[dict]] = []
    base_preds: list[list[dict]] = []
    gts: list[list[dict]] = []

    for ex in gt_examples:
        items = [{"Ingredient": line.lstrip("-• ").strip(), "Quantity": ""}
                 for line in ex.get("raw_lines", [])]
        gts.append(ex.get("expected", []))

        # Post-fallback (shipping).
        post, _source = _run_pass1(items, client)
        post_preds.append(post)

        # Raw-LLM: try to replay the prompt from cache without guards/fallback.
        raw = _raw_pass1_from_cache(ex.get("raw_lines", []))
        raw_preds.append(raw if raw is not None else post)  # fall back to post if no cache

        # Baseline.
        base_preds.append(baseline_pass1(ex.get("raw_lines", [])))

    return (
        score_pass1(raw_preds, gts),
        score_pass1(post_preds, gts),
        score_pass1(base_preds, gts),
    )


def _raw_pass1_from_cache(raw_lines: list[str]) -> list[dict] | None:
    """Read the cached Pass-1 response directly (bypassing guards)."""
    from core.shopping import _build_pass1_prompt
    from core.shopping_logger import compute_prompt_hash, read_cache
    from core.shopping_schemas import ConsolidationResponse

    lines_formatted = [f"- {l.lstrip('-• ').strip()}" for l in raw_lines if l and l.strip()]
    prompt = _build_pass1_prompt(lines_formatted)
    cached = read_cache(compute_prompt_hash(SHOPPING_MODEL, prompt))
    if not cached or not cached.get("response"):
        return None
    try:
        return [c.model_dump() for c in ConsolidationResponse.model_validate_json(cached["response"]).ingredients]
    except Exception:
        return None


def _eval_pass3(gt_examples: list[dict], mode: str, api_key: str | None) -> tuple[dict, dict, dict, list[dict]]:
    """Run Pass-3 evaluation. Returns (raw, post, baseline, failures)."""
    from core.shopping import _build_pass3_prompt, _format_candidates
    from core.shopping_fallback import rule_based_select
    from core.shopping_guards import classify_match_quality, run_pass3_guards
    from core.shopping_logger import compute_prompt_hash, read_cache
    from core.shopping_schemas import SelectionResponse

    client = _build_client(mode, api_key)

    raw_preds: list[dict] = []
    post_preds: list[dict] = []
    base_preds: list[dict] = []
    failures: list[dict] = []

    # Score one ingredient per batch (keeps scoring simple).
    for ex in gt_examples:
        ingredient = ex.get("ingredient", {})
        cands = ex.get("candidates", [])
        top_score = float(cands[0].get("tfidf_score", 0.0)) if cands else 0.0

        # ── Raw LLM ────────────────────────────────────────────────────────
        # Re-emit the exact same prompt used by the pipeline and read the cache.
        batch = [{
            "name": ingredient.get("name", ""),
            "total": ingredient.get("total", 0),
            "unit": ingredient.get("unit", ""),
            "candidates": _format_candidates_from_list(cands),
            "top_score": top_score,
        }]
        prompt = _build_pass3_prompt(batch, people_count=1)
        cached = read_cache(compute_prompt_hash(SHOPPING_MODEL, prompt))

        raw_row = None
        if cached and cached.get("response"):
            try:
                sel = SelectionResponse.model_validate_json(cached["response"])
                if sel.products:
                    p = sel.products[0]
                    raw_row = _pred_row_from_product(p, cands, source="llm")
            except Exception:
                pass

        # ── Post-fallback (ship) ──────────────────────────────────────────
        # Run the full pipeline path for this single ingredient.
        post_row = _run_full_pass3_one(ingredient, cands, mode, api_key)

        # ── Baseline ──────────────────────────────────────────────────────
        # Normalise ground-truth `tfidf_score` -> the `_score` key that
        # `rule_based_select` expects (production uses `_score` via
        # `_search_bilingual_scored`).
        base_cands = [{**c, "_score": c.get("_score", c.get("tfidf_score", 0.0))} for c in cands]
        base_sel = rule_based_select(base_cands, ingredient, people=1)
        base_row = {
            "product_name": base_sel["product_name"],
            "pack_size_value": _pack_val(base_sel["pack_size"]),
            "pack_size_unit": _pack_unit(base_sel["pack_size"]),
            "packs_needed": base_sel["packs_needed"],
            "unit_price": base_sel["unit_price"],
            "total_price": base_sel["total_price"],
            "match_quality": base_sel["match_quality"],
            "_source": "baseline",
        }

        raw_preds.append(raw_row or post_row)
        post_preds.append(post_row)
        base_preds.append(base_row)

        # Failure tracker (based on post-ship row).
        acceptable = {s.strip().lower() for s in ex.get("acceptable_skus", []) if s}
        if (post_row.get("product_name") or "").strip().lower() not in acceptable:
            failures.append({
                "ingredient": ingredient.get("name", ""),
                "predicted": post_row.get("product_name", ""),
                "expected": ex.get("acceptable_skus", []),
                "reason": f"match_quality={post_row.get('match_quality','?')}, source={post_row.get('_source','?')}",
            })

    return (
        score_pass3(raw_preds, gt_examples),
        score_pass3(post_preds, gt_examples),
        score_pass3(base_preds, gt_examples),
        failures,
    )


def _format_candidates_from_list(cands: list[dict]) -> str:
    if not cands:
        return "  (no Mercadona match found)"
    return "\n".join(
        f"  - {c.get('name','')} | €{float(c.get('price', 0) or 0):.2f} "
        f"| ref_unit: {c.get('unit','')} | URL: {c.get('url','')}"
        for c in cands
    )


def _pack_val(s: str) -> float:
    import re
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else 0.0


def _pack_unit(s: str) -> str:
    import re
    m = re.search(r"([a-zA-Z]+)\s*$", (s or "").strip())
    return m.group(1).lower() if m else ""


def _pred_row_from_product(sp, cands: list[dict], source: str) -> dict:
    return {
        "product_name": sp.product_name,
        "pack_size_value": _pack_val(sp.pack_size),
        "pack_size_unit": _pack_unit(sp.pack_size),
        "packs_needed": int(sp.packs_needed),
        "unit_price": float(sp.unit_price),
        "total_price": float(sp.total_price),
        "match_quality": sp.match_quality,
        "_source": source,
    }


def _run_full_pass3_one(ingredient: dict, cands: list[dict], mode: str, api_key: str | None) -> dict:
    """Single-ingredient Pass-3 through the real pipeline with guards+fallback."""
    import pandas as pd
    from core.shopping import _run_pass3

    client = _build_client(mode, api_key)
    cand_df = pd.DataFrame(cands) if cands else pd.DataFrame(columns=["name", "price", "unit", "url"])
    if "_score" not in cand_df.columns and "tfidf_score" in cand_df.columns:
        cand_df["_score"] = cand_df["tfidf_score"]

    from core.shopping import _format_candidates
    top_score = float(cands[0].get("tfidf_score", 0.0)) if cands else 0.0
    ctx = [{
        "name": ingredient.get("name", ""),
        "total": ingredient.get("total", 0),
        "unit": ingredient.get("unit", ""),
        "candidates": _format_candidates(cand_df),
        "candidates_df": cand_df,
        "top_score": top_score,
        "ingredient": ingredient,
    }]
    rows = _run_pass3(ctx, client, people_count=1)
    if not rows:
        return {"product_name": "", "packs_needed": 0, "unit_price": 0, "total_price": 0,
                "match_quality": "none", "_source": "fallback"}
    r = rows[0]
    return {
        "product_name": r["SKU"],
        "pack_size_value": _pack_val(r["Pack Size"]),
        "pack_size_unit": _pack_unit(r["Pack Size"]),
        "packs_needed": int(r.get("Count", 0) or 0),
        "unit_price": float(r.get("Unit Price", 0) or 0),
        "total_price": float(r.get("Total Price", 0) or 0),
        "match_quality": r.get("match_quality", "exact"),
        "_source": r.get("_source", "llm"),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("live", "replay"), required=True)
    ap.add_argument("--out", required=True, help="Output directory for metrics.json + report.md")
    ap.add_argument("--groq-key", default=os.environ.get("GROQ_API_KEY"))
    ap.add_argument("--threshold-top1", type=float, default=0.70,
                    help="Minimum Pass-3 post-fallback top1_sku_accuracy before exit code 2.")
    args = ap.parse_args()

    p1_gt = _load_jsonl(os.path.join(_GT_DIR, "pass1_consolidation.jsonl"))
    p3_gt = _load_jsonl(os.path.join(_GT_DIR, "pass3_sku_selection.jsonl"))

    if not p1_gt and not p3_gt:
        print("WARNING: no ground-truth examples found — nothing to score.")
        print(f"  Expected: {os.path.join(_GT_DIR, 'pass1_consolidation.jsonl')}")
        print(f"            {os.path.join(_GT_DIR, 'pass3_sku_selection.jsonl')}")
        return 1

    # Empty stub dicts used when one set is missing.
    empty_p1 = {
        "n_batches": 0, "n_gt_items": 0, "n_pred_items": 0,
        **{k: {"value": 0.0, "n": 0, "ci95": (0.0, 0.0)} for k in (
            "name_exact_match", "name_jaccard_pass_at_0_6", "unit_accuracy",
            "quantity_within_10pct", "coverage", "spurious_rate",
        )},
        "name_token_jaccard_mean": {"value": 0.0, "n": 0},
    }
    empty_p3 = {
        "n": 0,
        **{k: {"value": 0.0, "n": 0, "ci95": (0.0, 0.0)} for k in (
            "top1_sku_accuracy", "candidate_set_recall", "pack_size_accuracy",
            "packs_needed_exact", "price_consistency", "hallucination_rate",
            "fallback_trigger_rate", "match_quality_accuracy",
        )},
        "match_quality_confusion": {},
    }

    if p1_gt:
        p1_raw, p1_post, p1_base = _eval_pass1(p1_gt, args.mode, args.groq_key)
    else:
        p1_raw = p1_post = p1_base = empty_p1

    if p3_gt:
        p3_raw, p3_post, p3_base, failures = _eval_pass3(p3_gt, args.mode, args.groq_key)
    else:
        p3_raw = p3_post = p3_base = empty_p3
        failures = []

    dataset_hash = _sha256_file(_MERCADONA_CSV)

    json_path, md_path = emit_report(
        args.out,
        pass1_raw=p1_raw, pass1_post=p1_post, pass1_baseline=p1_base,
        pass3_raw=p3_raw, pass3_post=p3_post, pass3_baseline=p3_base,
        pass3_failures=failures,
        dataset_hash=dataset_hash,
        model=SHOPPING_MODEL,
        mode=args.mode,
    )
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")

    post_top1 = p3_post.get("top1_sku_accuracy", {}).get("value", 0.0)
    if p3_gt and post_top1 < args.threshold_top1:
        print(f"FAIL: post-fallback top1={post_top1:.2%} < threshold {args.threshold_top1:.0%}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
