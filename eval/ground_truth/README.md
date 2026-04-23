# Ground-Truth Labelling Protocol

This directory holds hand-labelled evaluation data for the LLM shopping
pipeline. The eval harness (`eval/run_eval.py`) scores each run against
these files. Labelling quality directly bounds the usefulness of every
metric downstream — read this document before adding or editing examples.

---

## Scope

Two files:

- `pass1_consolidation.jsonl` — one record per **meal-plan batch** of raw
  ingredient lines. Target: **80 labelled records**, stratified as:
    - 40 English-only raw lines
    - 20 mixed English + quantity-in-Spanish-unit records
    - 20 edge cases (empty quantities, unusual units, fractions, nested
      parentheticals)

- `pass3_sku_selection.jsonl` — one record per **ingredient → SKU selection**
  problem. Target: **100 labelled records**, stratified by category:
    - produce (20)
    - meat/poultry/fish (20)
    - dairy (15)
    - pantry (20)
    - spice (10)
    - liquid (10)
    - unavailable items / edge cases (5)
  Within that stratification, include:
    - ~70 `"exact"` matches
    - ~20 `"alternative"` cases (e.g. "fresh cilantro" when Mercadona
      only stocks dried; "boneless chicken breast" matched to "chicken
      breast fillets")
    - ~10 `"none"` cases (genuinely unstocked specialty items —
      "yuzu zest", "gochujang paste", etc.)

---

## Record formats

### `pass1_consolidation.jsonl`

```json
{
  "id": "gt_p1_001",
  "raw_lines": [
    "- 2 cups chopped onion",
    "- 1 lb ground beef",
    "- 1/2 cup diced onion"
  ],
  "expected": [
    {"name": "onion",       "total": 375, "unit": "g"},
    {"name": "ground beef", "total": 454, "unit": "g"}
  ]
}
```

- `expected.name` is the canonical lowercase English name (no adjectives
  like "fresh", "chopped", "boneless").
- `expected.total` is always in `g`, `ml`, or whole-number `unit`.
- Drop pantry negligibles (salt < 5 g, pepper < 2 g, vanilla < 5 ml) —
  the LLM is expected to drop them, and leaving them in the GT penalises
  correct behaviour.

### `pass3_sku_selection.jsonl`

```json
{
  "id": "gt_p3_001",
  "ingredient": {"name": "onion", "total": 900, "unit": "g"},
  "candidates": [
    {"name": "Cebolla troceada Hacendado ultracongelada 450g",
     "price": 0.95, "unit": "kg",
     "url": "https://...", "tfidf_score": 0.82},
    {"name": "Cebolla dulce bolsa 1kg",
     "price": 1.20, "unit": "kg",
     "url": "https://...", "tfidf_score": 0.71}
  ],
  "expected_sku":         "Cebolla troceada Hacendado ultracongelada 450g",
  "expected_pack_size":   {"value": 450, "unit": "g"},
  "expected_packs":       2,
  "acceptable_skus":      ["Cebolla troceada ...", "Cebolla dulce ..."],
  "expected_match_quality": "exact"
}
```

**The `acceptable_skus` tie set is the single biggest lever on the
measured Pass-3 accuracy.** When more than one SKU is a reasonable
answer (e.g. "onion 900 g" → either a 450 g bag ×2 or a 1 kg bag ×1),
list *every* reasonable SKU. Under-specifying this set makes the LLM
look worse than it is.

Rules of thumb for `acceptable_skus`:

- Same species / same cut / same unit semantics → include.
- Different pack size but same product → include.
- Frozen vs. fresh of the same thing → usually include (note in a
  labelling comment if you exclude).
- Different species (beef vs. pork) → exclude.

---

## Generating candidate lists

The `candidates` array for each Pass-3 record is the **frozen TF-IDF
top-5** from `services.rag.search_products`, snapshotted against a
pinned Mercadona catalog. Do **not** re-run TF-IDF when editing labels
— that would make historical eval runs incomparable. Re-snapshot only
when the catalog changes intentionally and record the new catalog
SHA-256 below.

Pinned catalog SHA-256 (update when re-snapshotting):
```
(fill in with `sha256sum data/mercadona_cache.csv`)
```

Pinned model snapshot date: `YYYY-MM-DD` (update when changing models)

---

## Labelling workflow (recommended)

1. Pull a batch of 10 raw ingredient lines (Pass 1) or 10 candidate
   sets (Pass 3) via `scripts/sample_ground_truth.py` (TODO).
2. For Pass 3: look at all 5 candidates, pick the best `expected_sku`,
   then list every other acceptable SKU. Assign `expected_match_quality`:
   - any candidate is the same species and unit semantics → `"exact"`
   - only loosely-related candidates (e.g. fresh→dried, or closely
     related species) → `"alternative"`
   - no reasonable candidate → `"none"` (leave `candidates: []` and
     `expected_sku: ""`).
3. Cross-check your assignment against the TF-IDF top-1 score: scores
   below 0.35 for an `"exact"` label are suspicious.

**Budget**: ~2 min per Pass-1 example, ~2.5 min per Pass-3 example ≈
4–6 h total for the full 80 + 100 corpus. Time spent on `acceptable_skus`
is the highest-leverage investment.

---

## Limitations (acknowledged)

- **Name similarity uses token Jaccard, not embeddings.** Deliberate
  choice to keep eval dependency-free. A sentence-transformer upgrade is
  a single-file swap in `eval/metrics_pass1.py::_jaccard` if needed.
- **Groq `seed` is not a true determinism guarantee.** Reproducibility
  rests on the cache in `data/llm_logs/cache/`, not on the seed.
- **Alternative thresholds (0.35 / 0.65) are heuristic**, calibrated
  against the Pass-3 corpus above. Re-calibrate if the catalog or
  ingredient distribution shifts.
