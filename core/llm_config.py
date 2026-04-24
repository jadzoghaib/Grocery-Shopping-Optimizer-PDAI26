"""Pinned LLM configuration for the shopping pipeline.

Central source of truth for model IDs and decoding parameters so that
`core/shopping.py` and `eval/` share exactly the same configuration.
Changing any value here invalidates the response cache because prompt
hashes are computed from `model + prompt`.
"""

import os

# ── Shopping pipeline ─────────────────────────────────────────────────────────
# Pass 1 (consolidation) only does unit-conversion arithmetic and ingredient
# name normalisation — a fast 8b model is more than capable and ~8× quicker.
PASS1_MODEL: str = "llama-3.1-8b-instant"

# Pass 3 (SKU selection) needs product-matching intelligence: keep the 70b model.
SHOPPING_MODEL: str = "llama-3.3-70b-versatile"

SHOPPING_TEMPERATURE: float = 0.0
SHOPPING_SEED: int = 42

# Timeouts (seconds).
# Pass 1 uses a fast model → tighter timeout.
PASS1_TIMEOUT: int = 15
PASS3_TIMEOUT: int = 20

# ── Match-quality thresholds (used by core/shopping_guards.py) ───────────────
# Calibrated against the 100 Pass-3 ground-truth examples.
# Top-1 TF-IDF cosine above THRESHOLD_EXACT → "exact"
# Between THRESHOLD_ALT and THRESHOLD_EXACT → "alternative"
# Below THRESHOLD_ALT or no candidates → "none"
MATCH_QUALITY_THRESHOLD_EXACT: float = 0.65
MATCH_QUALITY_THRESHOLD_ALT: float = 0.35


def build_llm(groq_api_key: str, temperature: float = 0.3):
    """Return a ChatGroq LLM with a second Groq key as automatic fallback.

    When the primary key hits its rate limit, LangChain's `.with_fallbacks()`
    transparently retries the same call with the secondary key (GROQ_API_KEY_2).

    Args:
        groq_api_key: Primary Groq API key (gsk_…).
        temperature:  Sampling temperature (default 0.3).

    Returns:
        A Runnable that behaves like ChatGroq, with a second Groq key as fallback.
    """
    from langchain_groq import ChatGroq

    primary = ChatGroq(
        api_key=groq_api_key,
        model=SHOPPING_MODEL,
        temperature=temperature,
    )

    fallbacks = []
    for env_var in ("GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4"):
        k = os.environ.get(env_var, "").strip()
        if k and k != groq_api_key:
            fallbacks.append(ChatGroq(api_key=k, model=SHOPPING_MODEL, temperature=temperature))

    return primary.with_fallbacks(fallbacks) if fallbacks else primary
