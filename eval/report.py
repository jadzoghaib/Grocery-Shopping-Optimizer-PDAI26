"""Emit the Markdown + JSON evaluation report.

The three columns in the Markdown report are deliberate:

* **Raw LLM** — LLM output scored directly, before guards/fallback mask errors.
  This measures the LLM in isolation — the metric the reviewer cares about.
* **Post-fallback** — what actually ships to the UI. Measures the user
  experience after the robustness layer fires.
* **Baseline** — pure rule-based path. Sanity-check: how much does the LLM
  actually buy us over rules?

Every metric carries a Wilson 95% confidence interval so small-sample noise
doesn't get read as signal.
"""
from __future__ import annotations

import json
import os
from typing import Any

from eval.metrics_util import fmt_ci, fmt_pct


def _fmt_metric(m: Any) -> str:
    """Format a ``{value, n, ci95}`` dict as ``pct [CI] (n=…)``."""
    if not isinstance(m, dict) or "value" not in m:
        return str(m)
    val = fmt_pct(m["value"])
    ci = fmt_ci(m["ci95"]) if "ci95" in m else ""
    n = m.get("n", "?")
    return f"{val} {ci} (n={n})".strip()


def _three_col_row(label: str, raw: Any, post: Any, base: Any) -> str:
    return f"| {label} | {_fmt_metric(raw)} | {_fmt_metric(post)} | {_fmt_metric(base)} |"


def _confusion_md(confusion: dict) -> str:
    """Render a 3×3 match_quality confusion matrix as Markdown."""
    labels = ["exact", "alternative", "none"]
    lines = ["| predicted ↓ / expected → | " + " | ".join(labels) + " |"]
    lines.append("|" + "|".join(["---"] * (len(labels) + 1)) + "|")
    for p in labels:
        row = [p] + [str(confusion.get(p, {}).get(e, 0)) for e in labels]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def emit_report(
    out_dir: str,
    *,
    pass1_raw: dict,
    pass1_post: dict,
    pass1_baseline: dict,
    pass3_raw: dict,
    pass3_post: dict,
    pass3_baseline: dict,
    pass3_failures: list[dict],
    dataset_hash: str,
    model: str,
    mode: str,
) -> tuple[str, str]:
    """Write metrics.json and report.md. Returns (json_path, md_path)."""
    os.makedirs(out_dir, exist_ok=True)

    flat = {
        "meta": {"model": model, "mode": mode, "dataset_hash": dataset_hash},
        "pass1": {"raw": pass1_raw, "post_fallback": pass1_post, "baseline": pass1_baseline},
        "pass3": {"raw": pass3_raw, "post_fallback": pass3_post, "baseline": pass3_baseline},
    }
    json_path = os.path.join(out_dir, "metrics.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(flat, f, indent=2, ensure_ascii=False, default=str)

    md = []
    md.append(f"# Shopping pipeline — evaluation report")
    md.append("")
    md.append(f"- **Model**: `{model}`")
    md.append(f"- **Mode**: `{mode}`")
    md.append(f"- **Dataset SHA-256**: `{dataset_hash}`")
    md.append("")
    md.append("## Pass 1 — consolidation")
    md.append("")
    md.append("| Metric | Raw LLM | Post-fallback (ship) | Baseline (rules) |")
    md.append("|---|---|---|---|")
    for key in (
        "name_exact_match",
        "name_jaccard_pass_at_0_6",
        "unit_accuracy",
        "quantity_within_10pct",
        "coverage",
        "spurious_rate",
    ):
        md.append(_three_col_row(key, pass1_raw.get(key), pass1_post.get(key), pass1_baseline.get(key)))
    md.append("")
    md.append("## Pass 3 — SKU selection")
    md.append("")
    md.append("| Metric | Raw LLM | Post-fallback (ship) | Baseline (rules) |")
    md.append("|---|---|---|---|")
    for key in (
        "top1_sku_accuracy",
        "candidate_set_recall",
        "pack_size_accuracy",
        "packs_needed_exact",
        "price_consistency",
        "hallucination_rate",
        "fallback_trigger_rate",
        "match_quality_accuracy",
    ):
        md.append(_three_col_row(key, pass3_raw.get(key), pass3_post.get(key), pass3_baseline.get(key)))
    md.append("")

    # Confusion matrix (post-fallback — this is what the user sees).
    md.append("### Match-quality confusion matrix (post-fallback)")
    md.append("")
    md.append(_confusion_md(pass3_post.get("match_quality_confusion", {})))
    md.append("")

    # Ceiling note.
    csr = pass3_post.get("candidate_set_recall", {}).get("value", 0)
    md.append(
        f"**Retrieval ceiling**: Pass 3 top-1 accuracy is bounded by "
        f"`candidate_set_recall = {fmt_pct(csr)}`. Any remaining gap is "
        f"retrieval failure (Pass 2 TF-IDF), not LLM failure."
    )
    md.append("")

    # Top failures.
    md.append("## Top-10 failures (post-fallback)")
    md.append("")
    if not pass3_failures:
        md.append("_None — all predictions landed in their acceptable set._")
    else:
        md.append("| # | Ingredient | Predicted | Expected (any of) | Reason |")
        md.append("|---|---|---|---|---|")
        for i, f in enumerate(pass3_failures[:10], start=1):
            md.append(
                f"| {i} | {f.get('ingredient','')} | {f.get('predicted','')} "
                f"| {', '.join(f.get('expected', []))[:80]} | {f.get('reason','')} |"
            )
    md.append("")

    md_path = os.path.join(out_dir, "report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    return json_path, md_path
