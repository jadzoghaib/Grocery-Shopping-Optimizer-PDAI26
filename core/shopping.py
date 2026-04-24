"""3-pass LLM shopping list pipeline with formal robustness layers.

Public API (unchanged): ``optimize_shopping_list_groq(items, client, people_count)``
→ ``pandas.DataFrame``.

The pipeline has always been:
    Pass 1 (LLM)  — consolidate & normalise quantities to g/ml/count
    Pass 2 (TF-IDF) — retrieve Mercadona candidates per canonical ingredient
    Pass 3 (LLM)  — pick best SKU, infer pack size, compute packs & total cost

This version wraps each LLM call with four cooperating layers:

  * ``core.shopping_logger.LLMLogger``   — structured JSONL + content-addressed cache
  * ``core.shopping_schemas``            — Pydantic v2 output validation
  * ``core.shopping_guards``             — runtime sanity guards (hallucination,
                                           price consistency, pack sizing,
                                           URL integrity, match-quality)
  * ``core.shopping_fallback``           — deterministic per-item fallback when
                                           the LLM fails validation or a guard

Adds two user-visible columns to the returned DataFrame:
  * ``match_quality`` — "exact" | "alternative" | "none"
  * ``match_reason``  — short human-readable justification (only non-empty
                       when ``match_quality != "exact"``)

And one hidden column:
  * ``_source`` — "llm" | "fallback" — for the eval harness to distinguish
                  which path produced each row.

Orchestration
─────────────
The pipeline is now driven by a **LangGraph ``StateGraph``** with five nodes:

    load_feedback_node → pass1_node → pass2_node → pass3_node → compile_node → END

State is carried in ``ShoppingState`` (a ``TypedDict``).  All guard and
fallback logic remains *inside* the individual pass functions — the graph
only wires them together and passes state through.
"""
from __future__ import annotations

import json
import math
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, TypedDict

import pandas as pd
from pydantic import ValidationError

from core.llm_config import (
    PASS1_TIMEOUT,
    PASS3_TIMEOUT,
    SHOPPING_MODEL,
    SHOPPING_SEED,
    SHOPPING_TEMPERATURE,
)
from core.shopping_fallback import rule_based_consolidate, rule_based_select
from core.shopping_guards import (
    check_coverage,
    check_unit_sanity,
    classify_match_quality,
    run_pass3_guards,
)
from core.shopping_logger import LLMLogger, read_cache
from core.shopping_schemas import (
    ConsolidationResponse,
    SelectedProduct,
    SelectionResponse,
)

# LangGraph imports are deferred inside _build_shopping_graph() so that
# importing this module at server startup does not load the large langgraph
# package before uvicorn can bind its port (avoids OOM on Render free tier).


# ══════════════════════════════════════════════════════════════════════════════
# LangGraph shared state definition
# ══════════════════════════════════════════════════════════════════════════════

class ShoppingState(TypedDict):
    """Mutable state bag passed between LangGraph nodes.

    Fields
    ------
    all_items    : raw ingredient dicts from the caller (read-only after init).
    people_count : number of people to scale quantities for.
    groq_client  : initialised Groq client (read-only after init).
    feedback     : pack-size feedback dict loaded by ``load_feedback_node``.
    raw_lines    : formatted raw ingredient lines derived in ``pass1_node``.
    consolidated : list of ``{name, total, unit}`` dicts from Pass 1.
    pass1_source : "llm" or "fallback" — records which path Pass 1 took.
    cand_ctx     : list of per-ingredient candidate dicts built in Pass 2.
    rows         : list of DataFrame-row dicts produced by Pass 3.
    error        : non-empty string when the pipeline aborts early.
    """

    all_items: list
    people_count: int
    groq_client: Any
    feedback: dict
    raw_lines: list[str]
    consolidated: list[dict]
    pass1_source: str
    cand_ctx: list[dict]
    rows: list[dict]
    error: str


# ══════════════════════════════════════════════════════════════════════════════
# Pass 2 helpers — kept at module level so eval/baselines.py can import them
# without triggering a circular import via the main optimiser function.
# ══════════════════════════════════════════════════════════════════════════════

def _get_tfidf_index():
    """Return (df, vectorizer, matrix) from services.rag without touching it."""
    from services.rag import _load_index  # intentionally internal import
    return _load_index()


_NON_FOOD_BLOCKLIST = frozenset([
    # ── Spanish hygiene / personal care ───────────────────────────────────────
    "toallita", "toallitas", "pañal", "pañales", "compresa", "compresas",
    "tampón", "tampones", "gel de ducha", "champú", "champu",
    "acondicionador", "pasta de dientes", "cepillo de dientes",
    "desodorante", "colonia", "perfume", "crema hidratante",
    "protector solar", "aftershave", "maquillaje", "loción", "serum",
    "jabón de manos", "jabon de manos", "espuma de afeitar", "cuchilla",
    "hilo dental", "enjuague bucal", "mascarilla facial", "contorno de ojos",
    "agua de colonia", "eau de toilette",
    # ── English hygiene / personal care (Mercadona catalog has bilingual names) ─
    "toothpaste", "whitening toothpaste", "toothbrush", "dental floss",
    "mouthwash", "shampoo", "conditioner", "shower gel", "body wash",
    "deodorant", "antiperspirant", "sunscreen", "sun cream", "face cream",
    "moisturiser", "moisturizer", "serum", "eye cream", "face mask",
    "makeup", "foundation", "mascara", "lipstick", "nail polish",
    "razor", "shaving foam", "aftershave lotion", "cologne",
    "sanitary pad", "tampon", "panty liner", "nappy", "diaper",
    "baby wipes", "wet wipes", "cotton pads", "cotton buds",
    # ── Spanish cleaning / household ──────────────────────────────────────────
    "detergente", "suavizante", "lejía", "lejia", "limpiador",
    "fregasuelos", "fregaplatos", "limpiacristales", "ambientador",
    "insecticida", "papel higiénico", "papel higienico",
    "papel de cocina", "papel absorbente", "esponja", "bayeta",
    "bolsa de basura", "bolsas de basura", "papel aluminio",
    "film transparente", "film cocina", "pastilla lavavajillas",
    "pastillas lavavajillas", "quitamanchas", "desengrasante",
    "abrillantador", "pastilla wc", "friegasuelos",
    # ── English cleaning / household ──────────────────────────────────────────
    "toilet paper", "kitchen roll", "kitchen paper", "paper towel",
    "bin bags", "trash bags", "garbage bags", "cling film", "cling wrap",
    "aluminium foil", "aluminum foil", "baking parchment",
    "dishwasher tablet", "dishwasher tablets", "dishwasher pod",
    "laundry detergent", "fabric softener", "bleach", "all-purpose cleaner",
    "glass cleaner", "floor cleaner", "toilet cleaner", "air freshener",
    "insect repellent", "pest control", "sponge", "cleaning cloth",
    # ── Baby non-food ─────────────────────────────────────────────────────────
    "crema de bebe", "crema bebé", "pañal bebé", "toallitas bebé",
    "toallitas bebe", "colonia bebe", "crema pañal",
    # ── Pharmacy / health ─────────────────────────────────────────────────────
    "ibuprofeno", "paracetamol", "vitamina", "suplemento", "probiótico",
    "antiácido", "tiritas", "venda", "termómetro",
    "ibuprofen", "paracetamol tablet", "vitamin tablet", "supplement tablet",
    # ── Pet non-food ─────────────────────────────────────────────────────────
    "arena para gatos", "arenero", "correa", "comedero",
    "cat litter", "pet collar", "dog lead",
    # ── Stationery / misc ────────────────────────────────────────────────────
    "bolígrafo", "cuaderno", "carpeta",
])

# URL slugs that indicate Mercadona non-food departments
_NON_FOOD_URL_SLUGS = frozenset([
    "/drogueria/", "/higiene/", "/bebe/cuidado", "/farmacia/",
    "/mascotas/accesorios", "/papeleria/",
])


def _is_non_food(product_name: str, url: str = "") -> bool:
    """Return True if the product is a non-food item.

    Checks both the product name against a keyword blocklist and the
    Mercadona URL path against known non-food department slugs.
    """
    name_lower = product_name.lower()
    if any(kw in name_lower for kw in _NON_FOOD_BLOCKLIST):
        return True
    if url:
        url_lower = url.lower()
        if any(slug in url_lower for slug in _NON_FOOD_URL_SLUGS):
            return True
    return False


# Confidence threshold above which we skip the LLM and use the
# rule-based result directly (Pass 3 fast-path).
_HIGH_CONF_THRESHOLD = 0.80

# Maps American/generic English ingredient names to how Mercadona's catalog
# actually names them.  Used as an additional search query on top of the
# ENGLISH_TO_SPANISH translation so that terms like "baking soda" can find
# "Bicarbonate of soda Hacendado" which would otherwise be missed.
_CATALOG_SYNONYMS: dict[str, list[str]] = {
    "baking soda":      ["bicarbonate", "bicarbonate of soda"],
    "sodium bicarbonate": ["bicarbonate", "bicarbonate of soda"],
    "hamburger":        ["burger", "beef burger"],
    "ground beef":      ["beef mince", "mince beef", "minced beef"],
    "cornstarch":       ["corn flour", "maizena", "cornflour"],
    "corn starch":      ["corn flour", "maizena", "cornflour"],
    "scallion":         ["spring onion"],
    "eggplant":         ["aubergine"],
    "zucchini":         ["courgette"],
    "cilantro":         ["coriander"],
    "arugula":          ["rocket"],
    "shrimp":           ["prawn", "prawns"],
    "heavy cream":      ["double cream", "whipping cream"],
    "half and half":    ["single cream"],
    "all-purpose flour": ["plain flour", "bread flour"],
    "whole milk":       ["full fat milk", "full cream milk"],
    "skimmed milk":     ["skim milk"],
    "semisweet chocolate": ["dark chocolate"],
    "powdered sugar":   ["icing sugar"],
    "confectioners sugar": ["icing sugar"],
    "molasses":         ["treacle"],
    "broiler":          ["grill"],
    "broiled":          ["grilled"],
    "scallion":         ["spring onion", "green onion"],
    "green onion":      ["spring onion"],
    "lemon juice":      ["lemon", "zumo limon"],
    "lime juice":       ["lime", "zumo lima"],
    "chicken broth":    ["chicken stock", "chicken stock cube"],
    "beef broth":       ["beef stock", "beef stock cube"],
    "vegetable broth":  ["vegetable stock"],
    "tomato paste":     ["tomato puree", "tomato concentrate"],
    "hot pepper":       ["chili pepper", "chilli"],
    "chili flakes":     ["crushed chilli", "red pepper flakes"],
    "red pepper flakes": ["crushed chilli", "chilli flakes"],
}


def _search_bilingual_scored(name: str, top_k: int = 5) -> tuple[pd.DataFrame, float]:
    """TF-IDF candidate retrieval — runs English AND Spanish queries, keeps best.

    Returns ``(candidates_df, top1_cosine_score)``. The candidates DataFrame
    contains an additional ``_score`` column with per-row cosine similarity
    (attached for downstream use by the eval harness and the match-quality
    classifier). ``top1_cosine_score`` is 0.0 when no candidates match.

    Strategy
    --------
    The catalog is in Spanish, so English queries often score low. The old
    approach returned English results immediately if *any* row cleared the 0.05
    floor — e.g. "baking soda" matched soda drinks, "spinach" matched unrelated
    items.  The fix: collect ALL candidate sets (English, Spanish exact, Spanish
    partial), then return whichever set has the highest top-1 score.

    Non-food products (cleaning supplies, hygiene items, etc.) are filtered
    out before returning.
    """
    from sklearn.metrics.pairwise import cosine_similarity

    try:
        from core.ingredient_translations import ENGLISH_TO_SPANISH as _E2S
    except ImportError:
        _E2S = {}

    df, vectorizer, matrix = _get_tfidf_index()
    if df.empty:
        return pd.DataFrame(), 0.0

    def _score(query: str) -> tuple[pd.DataFrame, float]:
        scores = cosine_similarity(vectorizer.transform([query]), matrix).flatten()
        idx = scores.argsort()[::-1][:top_k * 3]  # fetch extra to allow for filtering
        idx = [i for i in idx if scores[i] >= 0.05]
        if not idx:
            return pd.DataFrame(), 0.0
        hits = df.iloc[idx].copy().reset_index(drop=True)
        hits["_score"] = [float(scores[i]) for i in idx]
        # Filter out non-food products (check name + URL)
        hits = hits[~hits.apply(
            lambda r: _is_non_food(str(r["name"]), str(r.get("url", ""))), axis=1
        )].reset_index(drop=True)
        hits = hits.head(top_k)
        if hits.empty:
            return pd.DataFrame(), 0.0
        return hits, float(hits["_score"].iloc[0])

    # Collect all candidate sets; pick the one with the highest top-1 score.
    candidates: list[tuple[pd.DataFrame, float]] = []

    name_key = name.lower().strip()

    # 1. English query (original ingredient name)
    h, s = _score(name)
    if not h.empty:
        candidates.append((h, s))

    # 2. Catalog synonyms — maps American English to how Mercadona names things
    #    e.g. "baking soda" → "bicarbonate", "hamburger" → "burger"
    for syn in _CATALOG_SYNONYMS.get(name_key, []):
        h, s = _score(syn)
        if not h.empty:
            candidates.append((h, s))

    # 3. Exact Spanish translation
    es_exact = _E2S.get(name_key)
    if es_exact:
        h, s = _score(es_exact)
        if not h.empty:
            candidates.append((h, s))

    # 4. Partial key matches (e.g. "broth" inside "chicken broth")
    if not candidates:
        for key, es_val in _E2S.items():
            if key in name_key and key != name_key:
                h, s = _score(es_val)
                if not h.empty:
                    candidates.append((h, s))
                    break  # take first meaningful partial match

        # Also try partial catalog synonym matches
        for syn_key, syn_vals in _CATALOG_SYNONYMS.items():
            if syn_key in name_key and syn_key != name_key:
                for syn in syn_vals:
                    h, s = _score(syn)
                    if not h.empty:
                        candidates.append((h, s))
                        break
                if candidates:
                    break

    if not candidates:
        return pd.DataFrame(), 0.0

    # Return the result set whose best product scores highest.
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0]


# ══════════════════════════════════════════════════════════════════════════════
# Prompt builders (separated so the eval harness can hash stable prompts)
# ══════════════════════════════════════════════════════════════════════════════

def _build_pass1_prompt(raw_lines: list[str]) -> str:
    return (
        "You are a culinary ingredient expert.\n"
        "Below is a raw list of recipe ingredients (with raw quantities). "
        "Many are duplicates or variants of the same ingredient "
        "(e.g. 'onion', 'chopped onion', 'white onion' → all 'onion').\n\n"
        "Your tasks:\n"
        "1. Group all duplicates/variants under one canonical English name "
        "(lowercase, generic — drop adjectives like 'fresh', 'chopped', 'boneless').\n"
        "2. Sum ALL quantities for each group, converting to standard metric:\n"
        "   - Solid / powder / spice → grams (g)\n"
        "   - Liquid → millilitres (ml)\n"
        "   - Naturally counted items (eggs, whole fruits, whole vegetables, "
        "cloves of garlic) → count (units)\n\n"
        "   Key conversions:\n"
        "   1 cup flour=125 g | 1 cup sugar=200 g | 1 cup rice=185 g | "
        "1 cup liquid=240 ml | 1 cup chopped veg≈150 g\n"
        "   1 tbsp=15 g/ml | 1 tsp=5 g/ml | 1 lb=454 g | 1 oz=28 g\n"
        "   1 clove garlic≈5 g | 1 medium onion≈150 g | 1 medium carrot≈80 g\n"
        "   Spice with bare number → treat each as 1 tsp.\n"
        "3. Drop items whose total is negligible (e.g. salt <5 g, pepper <2 g, "
        "vanilla extract <5 ml) — they are pantry staples not worth buying.\n\n"
        "Raw ingredient list:\n"
        + "\n".join(raw_lines)
        + "\n\nReturn ONLY valid JSON (no markdown):\n"
        '{"ingredients": [{"name": "onion", "total": 900, "unit": "g"}, ...]}'
    )


def _load_pack_feedback() -> dict:
    """Load user pack-size feedback from data/pack_feedback.json.

    Returns a dict keyed by ingredient name (lowercase) with
    ``{"thumbs_up": int, "thumbs_down": int}`` values.
    """
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "pack_feedback.json")
    path = os.path.normpath(path)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _build_pass3_prompt(batch: list[dict], people_count: int, feedback: dict | None = None) -> str:
    batch_text = "".join(
        f"Ingredient: {it['name']}\n"
        f"Total needed: {it['total']} {it['unit']}\n"
        f"Top-1 retrieval score: {it.get('top_score', 0.0):.2f} "
        f"(0.0 = no match, 1.0 = perfect)\n"
        f"Mercadona candidates:\n{it['candidates']}\n---\n"
        for it in batch
    )

    # Inject user feedback for ingredients in this batch.
    feedback_lines: list[str] = []
    if feedback:
        for it in batch:
            key = it["name"].lower().strip()
            fb = feedback.get(key)
            if fb:
                up = fb.get("thumbs_up", 0)
                down = fb.get("thumbs_down", 0)
                if down > up:
                    feedback_lines.append(
                        f"- {it['name']}: users said pack size was TOO SMALL {down}x "
                        f"(vs {up}x correct) — consider rounding UP or adding an extra pack."
                    )
                elif up > 0:
                    feedback_lines.append(
                        f"- {it['name']}: users confirmed pack size was correct {up}x — your previous recommendation was good."
                    )
    feedback_block = (
        "\nUser feedback from previous shopping trips (adjust packs_needed accordingly):\n"
        + "\n".join(feedback_lines) + "\n"
        if feedback_lines else ""
    )

    return (
        "You are a smart Mercadona shopping assistant.\n"
        f"This shopping list is for {people_count} person(s).\n"
        "For each ingredient, select the best matching product and calculate packs to buy.\n\n"
        "Rules:\n"
        "1. Infer the pack size from the product name "
        "(e.g. '450g' → 450 g, '1 L' → 1000 ml, '12 ud' → 12 units, '500 ml' → 500 ml).\n"
        "   If no size in the name, use ref_unit: 'kg'→1000 g, 'L'→1000 ml, 'unit'→1 unit.\n"
        "   IMPORTANT: Eggs are always sold in cartons. If ref_unit='unit' and the product is eggs, "
        "the pack size is the number of eggs in the carton (e.g. 6 or 12), NOT 1.\n"
        "   Similarly, never let pack_size=1 unit for any egg product — look for '6 ud', '12 ud' "
        "in the product name or default to 6 if not stated.\n"
        "   For generic 'cheese' or 'queso', prefer a block or sliced cheese (queso tierno, "
        "queso semicurado) over specialty cheese (blue cheese spread, cheese with herbs).\n"
        "2. Convert pack_size to the SAME unit as total_needed before dividing.\n"
        f"3. packs_needed = ceil((total_needed × {people_count}) / pack_size). "
        "Always round UP. This scales the quantity for the number of people.\n"
        "4. total_price  = packs_needed × unit_price.\n"
        "5. Pick the product that is the CLOSEST match in type and unit "
        "(prefer weight-sold products for solid ingredients, volume for liquids).\n"
        "6. You MUST also set `match_quality` for each item:\n"
        "   - 'exact'       — Mercadona stocks the requested ingredient itself.\n"
        "   - 'alternative' — no exact match, but the chosen SKU is a reasonable substitute "
        "(e.g. fresh → frozen of same species, or closely related species).\n"
        "   - 'none'        — no candidate is a reasonable match at all.\n"
        "   Use the Top-1 retrieval score as a hint: < 0.35 usually means 'none' or "
        "'alternative'; 0.35-0.65 often means 'alternative'; > 0.65 usually means 'exact'.\n"
        "7. When match_quality is 'alternative' or 'none', write a short (≤ 20 words) "
        "`match_reason` explaining why (e.g. 'No fresh cilantro — suggesting dried coriander').\n"
        "   When match_quality is 'exact', `match_reason` should be empty.\n"
        "8. If match_quality='none', set product_name='Not found', packs_needed=0, "
        "total_price=0, url=''.\n"
        "9. Copy the URL EXACTLY from the candidate. Empty string if missing.\n"
        + feedback_block
        + "\n"
        + batch_text
        + "\nReturn ONLY valid JSON:\n"
        '{"products": [{"ingredient": "onion", "total_needed": "900 g", '
        '"product_name": "Cebolla troceada Hacendado ultracongelada 450g", '
        '"pack_size": "450 g", "packs_needed": 2, '
        '"unit_price": 0.95, "total_price": 1.90, "url": "https://...", '
        '"match_quality": "exact", "match_reason": ""}]}'
    )


# ══════════════════════════════════════════════════════════════════════════════
# LLM call helpers with caching
# ══════════════════════════════════════════════════════════════════════════════

def _llm_call(
    client, prompt: str, pass_name: str, timeout: int, metadata: dict | None = None
) -> tuple[str | None, bool]:
    """Run one Groq call, transparently hitting the local cache on repeat
    prompts. Returns ``(response_text, ok)``.

    On any exception the call is logged with ok=False and ``None`` is
    returned so the caller can invoke the deterministic fallback.
    """
    with LLMLogger(SHOPPING_MODEL, prompt, pass_name, metadata=metadata) as log:
        cached = read_cache(log.prompt_hash)
        if cached and cached.get("response"):
            log.record_response(cached["response"], ok=True)
            return cached["response"], True
        try:
            resp = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Return ONLY valid JSON, no markdown fences."},
                    {"role": "user", "content": prompt},
                ],
                model=SHOPPING_MODEL,
                temperature=SHOPPING_TEMPERATURE,
                seed=SHOPPING_SEED,
                response_format={"type": "json_object"},
                timeout=timeout,
            )
            text = resp.choices[0].message.content
            log.record_response(text, ok=True)
            return text, True
        except Exception as e:  # noqa: BLE001 — we catch & fall back by design
            log.record_error(f"{type(e).__name__}: {e}")
            return None, False


# ══════════════════════════════════════════════════════════════════════════════
# Pass 1 — consolidation with validation + fallback
# ══════════════════════════════════════════════════════════════════════════════

def _run_pass1(all_items: list, groq_client) -> tuple[list[dict], str]:
    """Return ``(consolidated, source)`` where ``source`` is ``"llm"`` or ``"fallback"``.

    The whole batch falls back together — it's not meaningful to run the LLM
    on only part of a consolidation batch because cross-line deduplication is
    the point.
    """
    raw_lines: list[str] = []
    for it in all_items:
        qty = str(it.get("Quantity", "")).strip()
        name = str(it.get("Ingredient", "")).strip()
        if name:
            raw_lines.append(f"- {(qty + ' ') if qty else ''}{name}")

    prompt = _build_pass1_prompt(raw_lines)
    text, ok = _llm_call(groq_client, prompt, pass_name="pass1", timeout=PASS1_TIMEOUT,
                         metadata={"raw_lines": len(raw_lines)})

    if not ok or not text:
        print("[shopping] Pass 1 LLM call failed -> rule-based consolidation")
        return rule_based_consolidate(raw_lines), "fallback"

    # Parse + validate.
    try:
        raw = json.loads(text)
        parsed = ConsolidationResponse.model_validate(raw)
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"[shopping] Pass 1 validation failed -> fallback. Error: {e}")
        return rule_based_consolidate(raw_lines), "fallback"

    consolidated = [c.model_dump() for c in parsed.ingredients]

    # Sanity guards.
    unit_failures = [
        f"{c['name']}" for c in consolidated
        if not check_unit_sanity(c["name"], c["total"], c["unit"])[0]
    ]
    if unit_failures:
        print(f"[shopping] Pass 1 unit-sanity failed for {unit_failures} -> fallback")
        return rule_based_consolidate(raw_lines), "fallback"

    cov_ok, cov_reason = check_coverage(raw_lines, consolidated)
    if not cov_ok:
        print(f"[shopping] Pass 1 coverage failed ({cov_reason}) -> fallback")
        return rule_based_consolidate(raw_lines), "fallback"

    return consolidated, "llm"


# ══════════════════════════════════════════════════════════════════════════════
# Pass 3 — SKU selection with validation + per-item fallback
# ══════════════════════════════════════════════════════════════════════════════

def _format_candidates(hits: pd.DataFrame) -> str:
    """Prompt-ready candidate block."""
    if hits.empty:
        return "  (no Mercadona match found)"
    return "\n".join(
        f"  - {r['name']} | €{float(r.get('price', 0)):.2f} "
        f"| ref_unit: {r.get('unit', '')} | URL: {r.get('url', '')}"
        for _, r in hits.iterrows()
    )


def _row_from_selected(sp: SelectedProduct) -> dict:
    """Convert a validated SelectedProduct into the shopping-list DataFrame row shape."""
    packs = min(10, int(math.ceil(float(sp.packs_needed or 1))))
    return {
        "Ingredient": sp.ingredient,
        "Qty Needed": sp.total_needed,
        "SKU": sp.product_name,
        "Pack Size": sp.pack_size,
        "Count": packs,
        "Unit Price": float(sp.unit_price),
        "Total Price": float(sp.total_price),
        "Link": sp.url,
        "match_quality": sp.match_quality,
        "match_reason": sp.match_reason,
    }


def _row_from_fallback(fb: dict) -> dict:
    return {
        "Ingredient": fb.get("ingredient", ""),
        "Qty Needed": fb.get("total_needed", ""),
        "SKU": fb.get("product_name", ""),
        "Pack Size": fb.get("pack_size", ""),
        "Count": min(10, int(fb.get("packs_needed", 0) or 0)),
        "Unit Price": float(fb.get("unit_price", 0) or 0),
        "Total Price": float(fb.get("total_price", 0) or 0),
        "Link": str(fb.get("url", "") or ""),
        "match_quality": fb.get("match_quality", "exact"),
        "match_reason": fb.get("match_reason", ""),
    }


def _reconcile_match_quality(llm_tag: str, deterministic_tag: str, reason: str, ingredient_name: str) -> tuple[str, str]:
    """Compare the LLM-reported match_quality against the deterministic classifier.

    When they disagree, trust the deterministic classifier; inject a reason
    if the LLM didn't supply one.
    """
    if llm_tag == deterministic_tag:
        return llm_tag, reason
    # Disagreement — trust deterministic.
    if not reason:
        if deterministic_tag == "alternative":
            reason = f"Closest Mercadona match for '{ingredient_name}' — not an exact stock item."
        elif deterministic_tag == "none":
            reason = f"No suitable Mercadona match for '{ingredient_name}'."
    return deterministic_tag, reason


def _process_pass3_batch(
    batch: list[dict], groq_client, people_count: int, feedback: dict | None
) -> SelectionResponse | None:
    """Run one Pass-3 LLM batch. Returns parsed SelectionResponse or None on failure."""
    prompt = _build_pass3_prompt(batch, people_count, feedback=feedback)
    text, ok = _llm_call(
        groq_client, prompt, pass_name="pass3", timeout=PASS3_TIMEOUT,
        metadata={"batch_size": len(batch)},
    )
    if not ok or not text:
        return None
    try:
        return SelectionResponse.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as e:
        print(f"[shopping] Pass 3 validation error: {e}")
        return None


def _rows_from_parsed_batch(
    parsed: SelectionResponse, batch: list[dict], people_count: int
) -> list[tuple[int, dict]]:
    """Convert a validated SelectionResponse into (original_idx, row) pairs."""
    by_name: dict[str, dict] = {it["name"].lower(): it for it in batch}
    covered: set[str] = set()
    result: list[tuple[int, dict]] = []

    for sp in parsed.products:
        key = (sp.ingredient or "").lower().strip()
        item = by_name.get(key)
        if item is None:
            continue
        covered.add(key)
        cand_records = item["candidates_df"].to_dict("records")
        ok_guards, reasons = run_pass3_guards(
            {
                "product_name": sp.product_name,
                "packs_needed": sp.packs_needed,
                "unit_price": sp.unit_price,
                "total_price": sp.total_price,
                "total_needed": sp.total_needed,
                "pack_size": sp.pack_size,
                "url": sp.url,
            },
            cand_records,
            people_count,
        )
        if not ok_guards:
            print(f"[shopping] Guards failed for '{sp.ingredient}': {reasons} -> fallback")
            fb = rule_based_select(cand_records, item["ingredient"], people_count)
            row = _row_from_fallback(fb)
            row["_source"] = "fallback"
            result.append((item["_orig_idx"], row))
            continue

        det_tag = classify_match_quality(sp.ingredient, sp.product_name, item.get("top_score", 0.0))
        final_tag, final_reason = _reconcile_match_quality(
            sp.match_quality, det_tag, sp.match_reason, sp.ingredient,
        )
        sp_patched = sp.model_copy(update={"match_quality": final_tag, "match_reason": final_reason})
        row = _row_from_selected(sp_patched)
        row["_source"] = "llm"
        result.append((item["_orig_idx"], row))

    # Fallback for items the LLM silently skipped
    for key, item in by_name.items():
        if key in covered:
            continue
        print(f"[shopping] Pass 3 missed '{key}' -> fallback")
        fb = rule_based_select(item["candidates_df"].to_dict("records"), item["ingredient"], people_count)
        row = _row_from_fallback(fb)
        row["_source"] = "fallback"
        result.append((item["_orig_idx"], row))

    return result


def _run_pass3(
    cand_ctx: list[dict], groq_client, people_count: int, feedback: dict | None = None
) -> list[dict]:
    """Pass 3 with two performance optimisations:

    1. **High-confidence fast path** — items where the TF-IDF top-1 score
       meets or exceeds ``_HIGH_CONF_THRESHOLD`` skip the LLM entirely and
       are resolved instantly with ``rule_based_select``.

    2. **Parallel LLM batches** — remaining items are split into batches of 5
       and submitted simultaneously to a thread pool, so Groq latency for
       batch N does not block batch N+1.

    Results are reassembled in the original ``cand_ctx`` order.
    """
    batch_size = 5
    # Tag each item with its position so we can restore order after parallel execution.
    for i, item in enumerate(cand_ctx):
        item["_orig_idx"] = i

    indexed_rows: list[tuple[int, dict]] = []

    # ── Fast path ─────────────────────────────────────────────────────────────
    llm_items: list[dict] = []
    for item in cand_ctx:
        if item.get("top_score", 0.0) >= _HIGH_CONF_THRESHOLD:
            fb = rule_based_select(item["candidates_df"].to_dict("records"), item["ingredient"], people_count)
            row = _row_from_fallback(fb)
            row["_source"] = "fast_path"
            indexed_rows.append((item["_orig_idx"], row))
            print(f"[shopping] Fast-path (score={item['top_score']:.2f}) for '{item['name']}'")
        else:
            llm_items.append(item)

    # ── Parallel LLM batches ──────────────────────────────────────────────────
    batches = [llm_items[i:i + batch_size] for i in range(0, len(llm_items), batch_size)]
    if batches:
        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            future_to_batch = {
                pool.submit(_process_pass3_batch, batch, groq_client, people_count, feedback): batch
                for batch in batches
            }
            for future in as_completed(future_to_batch):
                batch = future_to_batch[future]
                try:
                    parsed = future.result()
                except Exception as exc:
                    print(f"[shopping] Batch future raised: {exc}")
                    parsed = None

                if parsed is None:
                    print(f"[shopping] Pass 3 batch failed -> per-item fallback ({len(batch)} items)")
                    for it in batch:
                        fb = rule_based_select(it["candidates_df"].to_dict("records"), it["ingredient"], people_count)
                        row = _row_from_fallback(fb)
                        row["_source"] = "fallback"
                        indexed_rows.append((it["_orig_idx"], row))
                else:
                    indexed_rows.extend(_rows_from_parsed_batch(parsed, batch, people_count))

    # Restore original order
    indexed_rows.sort(key=lambda x: x[0])
    return [row for _, row in indexed_rows]


# ══════════════════════════════════════════════════════════════════════════════
# LangGraph node functions
# ══════════════════════════════════════════════════════════════════════════════

def load_feedback_node(state: ShoppingState) -> ShoppingState:
    """Node 1 — load pack-size feedback from disk.

    Populates ``state["feedback"]`` so all downstream nodes can access it
    without re-reading the file.  Errors are silently swallowed so a missing
    or corrupt feedback file never aborts the pipeline.
    """
    try:
        feedback = _load_pack_feedback()
    except Exception as e:  # noqa: BLE001
        print(f"[shopping:load_feedback_node] Could not load feedback: {e}")
        feedback = {}
    return {**state, "feedback": feedback}


def pass1_node(state: ShoppingState) -> ShoppingState:
    """Node 2 — Pass 1: LLM consolidation with Pydantic validation + guards + rule-based fallback.

    Calls ``_run_pass1`` which already handles all guard and fallback logic
    internally.  Writes ``consolidated`` and ``pass1_source`` into state.
    If consolidation produces an empty list the ``error`` field is set so
    the graph can return early.
    """
    consolidated, source = _run_pass1(state["all_items"], state["groq_client"])
    if not consolidated:
        return {**state, "consolidated": [], "pass1_source": source, "error": "Pass 1 produced no consolidated ingredients."}
    return {**state, "consolidated": consolidated, "pass1_source": source, "error": ""}


def pass2_node(state: ShoppingState) -> ShoppingState:
    """Node 3 — Pass 2: TF-IDF retrieval (no LLM).

    For each consolidated ingredient, retrieves the top-5 Mercadona candidates
    using ``_search_bilingual_scored`` and stores the full candidate context
    list in ``state["cand_ctx"]``.  This node is always deterministic.
    """
    # Abort propagation: if an earlier node already set an error, skip work.
    if state.get("error"):
        return state

    cand_ctx: list[dict] = []
    for ing in state["consolidated"]:
        name = ing.get("name", "")
        total = ing.get("total", 0)
        unit = ing.get("unit", "")
        # Skip items with zero or negligible quantity — they shouldn't appear in the basket.
        if total == 0 or (isinstance(total, float) and total < 0.01):
            continue
        hits, top_score = _search_bilingual_scored(name, top_k=5)
        cand_ctx.append({
            "name": name,
            "total": total,
            "unit": unit,
            "candidates": _format_candidates(hits),
            "candidates_df": hits if not hits.empty else pd.DataFrame(columns=["name", "price", "unit", "url", "_score"]),
            "top_score": top_score,
            # ``ingredient`` mirrors the top-level keys; _run_pass3 expects it
            # as a sub-dict for the fallback path.
            "ingredient": {"name": name, "total": total, "unit": unit},
        })
    return {**state, "cand_ctx": cand_ctx}


def pass3_node(state: ShoppingState) -> ShoppingState:
    """Node 4 — Pass 3: LLM SKU selection with per-item guards + fallback + match-quality reconciliation.

    Calls ``_run_pass3`` which already handles per-item guard failures and
    fallbacks internally.  Writes ``rows`` into state.
    """
    # Abort propagation.
    if state.get("error"):
        return state

    rows = _run_pass3(
        state["cand_ctx"],
        state["groq_client"],
        state["people_count"],
        feedback=state.get("feedback"),
    )
    return {**state, "rows": rows}


def compile_node(state: ShoppingState) -> ShoppingState:
    """Node 5 — compile the final DataFrame rows list.

    Annotates every row with ``_pass1_source`` so the eval harness can
    distinguish LLM-vs-fallback at the consolidation level.  The actual
    ``pd.DataFrame`` is *not* stored in state (TypedDicts should stay JSON-
    serialisable); it is assembled by the public entry point after the graph
    returns.
    """
    # Abort propagation.
    if state.get("error"):
        return state

    rows = state.get("rows", [])
    if not rows:
        return {**state, "error": "Pass 3 produced no rows."}

    # Stamp Pass 1 source on every row so callers can inspect it.
    source = state.get("pass1_source", "llm")
    stamped = [{**r, "_pass1_source": source} for r in rows]
    return {**state, "rows": stamped}


# ══════════════════════════════════════════════════════════════════════════════
# LangGraph graph builder
# ══════════════════════════════════════════════════════════════════════════════

def _build_shopping_graph():
    """Construct and compile the shopping-list StateGraph.

    Graph topology
    ──────────────
        load_feedback_node
              │
          pass1_node          ← LLM consolidation (+ guards + fallback)
              │
          pass2_node          ← TF-IDF retrieval (deterministic)
              │
          pass3_node          ← LLM SKU selection (+ per-item guards + fallback)
              │
         compile_node         ← stamp _pass1_source, detect empty output
              │
             END

    Returns the compiled graph object (callable as ``graph.invoke(state)``).
    """
    from langgraph.graph import StateGraph, END  # lazy — deferred to first use
    builder = StateGraph(ShoppingState)

    # Register nodes.
    builder.add_node("load_feedback", load_feedback_node)
    builder.add_node("pass1", pass1_node)
    builder.add_node("pass2", pass2_node)
    builder.add_node("pass3", pass3_node)
    builder.add_node("compile", compile_node)

    # Wire edges: linear flow, error propagation is handled inside each node.
    builder.set_entry_point("load_feedback")
    builder.add_edge("load_feedback", "pass1")
    builder.add_edge("pass1", "pass2")
    builder.add_edge("pass2", "pass3")
    builder.add_edge("pass3", "compile")
    builder.add_edge("compile", END)

    return builder.compile()


# Compiled graph — initialised lazily on first request so that importing this
# module at server startup does not trigger the langgraph compilation step.
_SHOPPING_GRAPH = None


def _get_shopping_graph():
    global _SHOPPING_GRAPH
    if _SHOPPING_GRAPH is None:
        _SHOPPING_GRAPH = _build_shopping_graph()
    return _SHOPPING_GRAPH


# ══════════════════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════════════════

def optimize_shopping_list_groq(
    all_items: list, groq_client, people_count: int = 1
) -> pd.DataFrame:
    """3-pass smart shopping list pipeline.

    Pass 1 – LLM consolidates duplicate/variant ingredients and normalises all
             quantities to standard metric units (g, ml, or count).
    Pass 2 – TF-IDF retrieves the top Mercadona candidates for each canonical
             ingredient, also exposing the top-1 cosine score so Pass 3 can see
             retrieval confidence.
    Pass 3 – LLM picks the best SKU, infers pack size, computes
             packs_needed = ceil(total / pack_size), and self-reports
             match_quality ∈ {exact, alternative, none}. A deterministic
             classifier cross-checks the tag.

    Failures at any layer (LLM error, schema violation, guard violation) fall
    back to pure-Python rules per-item. The final DataFrame has two extra
    columns `match_quality` / `match_reason` the UI can surface to the user.

    Orchestration is driven by the LangGraph ``_SHOPPING_GRAPH``; the public
    signature is unchanged — ``server.py`` calls this function directly.
    """
    if not all_items or not groq_client:
        return pd.DataFrame()

    try:
        # Build the initial state and invoke the graph.
        initial_state: ShoppingState = {
            "all_items": all_items,
            "people_count": people_count,
            "groq_client": groq_client,
            "feedback": {},
            "raw_lines": [],
            "consolidated": [],
            "pass1_source": "llm",
            "cand_ctx": [],
            "rows": [],
            "error": "",
        }

        final_state: ShoppingState = _get_shopping_graph().invoke(initial_state)

        # Surface any error that propagated through the graph.
        if final_state.get("error"):
            print(f"[shopping] Pipeline aborted: {final_state['error']}")
            return pd.DataFrame()

        rows = final_state.get("rows", [])
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        # Expose the Pass 1 source as a top-level column (backwards-compatible).
        # ``compile_node`` stamped ``_pass1_source`` on each row dict; rename it
        # so existing callers that check ``df["_pass1_source"]`` still work.
        if "_pass1_source" not in df.columns:
            df["_pass1_source"] = final_state.get("pass1_source", "llm")

        return df

    except Exception as e:  # noqa: BLE001
        print(f"[shopping] Error: {e}")
        traceback.print_exc()
        return pd.DataFrame()
