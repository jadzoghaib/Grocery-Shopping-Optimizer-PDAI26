"""Structured logging + content-addressed cache for Groq LLM calls.

Every LLM call is:
  1. Hashed on ``model + "\n" + prompt`` → ``prompt_hash``.
  2. Recorded as one line of JSONL under ``data/llm_logs/shopping_YYYY-MM-DD.jsonl``.
  3. Persisted as raw JSON at ``data/llm_logs/cache/<prompt_hash>.json``.

The cache is consumed by ``eval/replay_client.ReplayGroqClient`` to enable
fully-offline deterministic replay of the shopping pipeline. Any prompt
edit transparently invalidates its cache entry (because the hash changes).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
import time
from typing import Any

# Repo-root / data / llm_logs/
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_DIR = os.path.join(_REPO_ROOT, "data", "llm_logs")
_CACHE_DIR = os.path.join(_LOG_DIR, "cache")

_write_lock = threading.Lock()


def _ensure_dirs() -> None:
    os.makedirs(_CACHE_DIR, exist_ok=True)


def compute_prompt_hash(model: str, prompt: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\n")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()


def _today_jsonl() -> str:
    return os.path.join(_LOG_DIR, f"shopping_{_dt.date.today().isoformat()}.jsonl")


def write_cache(prompt_hash: str, payload: dict) -> None:
    _ensure_dirs()
    path = os.path.join(_CACHE_DIR, f"{prompt_hash}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except OSError as e:
        print(f"[llm_logger] cache write failed for {prompt_hash[:8]}: {e}")


def read_cache(prompt_hash: str) -> dict | None:
    path = os.path.join(_CACHE_DIR, f"{prompt_hash}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def log_event(record: dict) -> None:
    """Append one line to today's JSONL log."""
    _ensure_dirs()
    path = _today_jsonl()
    line = json.dumps(record, ensure_ascii=False, default=str)
    with _write_lock:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"[llm_logger] log write failed: {e}")


class LLMLogger:
    """Context manager wrapping one Groq LLM call.

    Usage::

        with LLMLogger(model, prompt, pass_name="pass1") as log:
            resp = client.chat.completions.create(...)
            log.record_response(resp.choices[0].message.content, ok=True)
    """

    def __init__(self, model: str, prompt: str, pass_name: str, metadata: dict | None = None):
        self.model = model
        self.prompt = prompt
        self.pass_name = pass_name
        self.metadata = metadata or {}
        self.prompt_hash = compute_prompt_hash(model, prompt)
        self._start = 0.0
        self._response: str | None = None
        self._ok = False
        self._error: str | None = None

    def __enter__(self) -> "LLMLogger":
        self._start = time.monotonic()
        return self

    def record_response(self, response_text: str, ok: bool = True) -> None:
        self._response = response_text
        self._ok = ok

    def record_error(self, err: str) -> None:
        self._ok = False
        self._error = err

    def __exit__(self, exc_type, exc, tb) -> bool:
        elapsed = time.monotonic() - self._start
        if exc is not None:
            self._ok = False
            self._error = f"{exc_type.__name__}: {exc}"
        # Write cache only if we got a response.
        if self._response is not None and self._ok:
            write_cache(self.prompt_hash, {
                "model": self.model,
                "prompt_hash": self.prompt_hash,
                "response": self._response,
            })
        log_event({
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "pass": self.pass_name,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "prompt_len": len(self.prompt),
            "response_len": len(self._response) if self._response else 0,
            "ok": self._ok,
            "error": self._error,
            "elapsed_s": round(elapsed, 3),
            "metadata": self.metadata,
        })
        # Never swallow exceptions.
        return False
