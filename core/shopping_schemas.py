"""Pydantic v2 schemas for Pass 1 and Pass 3 LLM outputs.

Every LLM response is validated against these schemas before any downstream
logic consumes it. Validation failures cause that single item (not the whole
batch) to fall through to the deterministic rule-based path.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# Pass 1 — consolidation
# ══════════════════════════════════════════════════════════════════════════════

_ALLOWED_UNITS_P1 = {"g", "ml", "unit", "units"}


class ConsolidatedIngredient(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=80)
    total: float = Field(..., ge=0, le=100_000)
    unit: str

    @field_validator("unit")
    @classmethod
    def _unit_in_allowed(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _ALLOWED_UNITS_P1:
            raise ValueError(f"unit must be one of {_ALLOWED_UNITS_P1}, got {v!r}")
        # Normalise plural.
        return "unit" if v == "units" else v

    @field_validator("name")
    @classmethod
    def _name_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class ConsolidationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ingredients: List[ConsolidatedIngredient]


# ══════════════════════════════════════════════════════════════════════════════
# Pass 3 — SKU selection
# ══════════════════════════════════════════════════════════════════════════════

MatchQuality = Literal["exact", "alternative", "none"]


class SelectedProduct(BaseModel):
    """One row of Pass-3 output.

    ``match_quality`` is a new field introduced by the evaluation/robustness
    framework — the LLM is asked to self-report whether the chosen SKU is
    an exact match (Mercadona stocks the requested ingredient), an
    acceptable substitute, or nothing suitable. A deterministic guard
    (``core.shopping_guards.classify_match_quality``) cross-checks this
    tag against the TF-IDF top-1 cosine score and overrides the LLM on
    disagreement.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ingredient: str = Field(..., min_length=1)
    total_needed: str = Field(default="")
    product_name: str = Field(default="")
    pack_size: str = Field(default="")
    packs_needed: float = Field(default=0, ge=0, le=500)
    unit_price: float = Field(default=0, ge=0, le=1_000)
    total_price: float = Field(default=0, ge=0, le=10_000)
    url: str = Field(default="")
    match_quality: MatchQuality = Field(default="exact")
    match_reason: str = Field(default="", max_length=240)


class SelectionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    products: List[SelectedProduct]
