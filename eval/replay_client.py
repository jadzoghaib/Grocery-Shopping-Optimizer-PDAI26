"""Offline replay of Groq responses from the local content-addressed cache.

Mimics the subset of ``groq.Groq().chat.completions.create(...)`` that
``core.shopping`` relies on, so the entire pipeline can run fully offline,
deterministically, against a previously-collected cache.

If a required prompt is not cached, raises :class:`ReplayMiss`. Collect the
missing responses first with ``--mode live``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.shopping_logger import compute_prompt_hash, read_cache


class ReplayMiss(RuntimeError):
    """Raised when a replay request has no matching cached response."""


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Completion:
    choices: list[_Choice]


class _Completions:
    def create(
        self, *, messages: list[dict], model: str, **_: Any
    ) -> _Completion:
        # The user prompt is always messages[-1]["content"] in our pipeline.
        user_prompt = ""
        for m in messages:
            if m.get("role") == "user":
                user_prompt = m.get("content", "")
        prompt_hash = compute_prompt_hash(model, user_prompt)
        cached = read_cache(prompt_hash)
        if not cached or not cached.get("response"):
            raise ReplayMiss(
                f"No cached response for hash={prompt_hash[:12]} "
                f"(model={model}, prompt_len={len(user_prompt)}). "
                "Run --mode live first to populate the cache."
            )
        return _Completion(choices=[_Choice(message=_Message(content=cached["response"]))])


class _Chat:
    def __init__(self) -> None:
        self.completions = _Completions()


class ReplayGroqClient:
    """Drop-in replacement for ``groq.Groq(api_key=...)`` in replay mode."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self.chat = _Chat()
