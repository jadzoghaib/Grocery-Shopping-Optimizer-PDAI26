"""
core/groq_client.py
───────────────────
Server-side Groq key pool with automatic rotation on rate-limit (429) or
auth errors.  Keys are read from environment variables at startup:

    GROQ_API_KEY, GROQ_API_KEY_2, GROQ_API_KEY_3, GROQ_API_KEY_4

Usage
─────
# Drop-in replacement for groq.Groq — rotates automatically on 429/401:
client = make_groq_client(preferred_key="gsk_...")
resp   = client.chat.completions.create(model=..., messages=...)

# Low-level: run any callable(groq.Groq) with retry across all pool keys:
result = groq_with_rotation(lambda c: c.chat.completions.create(...))

If the caller supplies a preferred_key (e.g. from the browser Settings),
that key is tried first before falling back to the server pool.
"""

import os
import threading
import time
from groq import Groq

# ── Key pool ──────────────────────────────────────────────────────────────────
_SERVER_KEYS: list[str] = [
    k for k in [
        os.environ.get("GROQ_API_KEY", ""),
        os.environ.get("GROQ_API_KEY_2", ""),
        os.environ.get("GROQ_API_KEY_3", ""),
        os.environ.get("GROQ_API_KEY_4", ""),
    ] if k.strip()
]

_lock        = threading.Lock()
_key_idx     = 0          # pointer into _SERVER_KEYS
_cooldowns: dict[str, float] = {}   # key → epoch when it becomes usable again

RATE_LIMIT_COOLDOWN  = 60    # seconds to cool a key after 429
AUTH_ERROR_COOLDOWN  = 3600  # seconds to cool a key after 401


# ── Internal helpers ──────────────────────────────────────────────────────────
def _available_key() -> str:
    """Return the next server key that is not currently cooled-down."""
    global _key_idx
    if not _SERVER_KEYS:
        return ""
    with _lock:
        now = time.time()
        for i in range(len(_SERVER_KEYS)):
            idx  = (_key_idx + i) % len(_SERVER_KEYS)
            key  = _SERVER_KEYS[idx]
            if _cooldowns.get(key, 0) <= now:
                _key_idx = idx
                return key
        # All cooled-down → return the one that recovers soonest
        return min(_SERVER_KEYS, key=lambda k: _cooldowns.get(k, 0))


def _cool_down(key: str, seconds: int) -> None:
    with _lock:
        _cooldowns[key] = time.time() + seconds
    n = len(_SERVER_KEYS)
    print(f"[groq_client] key …{key[-6:]} cooled {seconds}s "
          f"({sum(1 for k in _SERVER_KEYS if _cooldowns.get(k,0) > time.time())}/{n} keys on cooldown)")


# ── Core rotation logic ───────────────────────────────────────────────────────
def groq_with_rotation(call_fn, preferred_key: str = ""):
    """
    Execute call_fn(groq.Groq) with automatic key rotation on 429 / auth errors.

    Parameters
    ----------
    call_fn       : callable(groq.Groq) → any
    preferred_key : user-supplied key (takes priority over server pool)

    Returns the result of call_fn, or raises the last error if all keys fail.
    """
    from groq import RateLimitError, AuthenticationError  # lazy import

    # Build the ordered list of keys to try
    user_key = preferred_key.strip()
    if user_key:
        # User key first, then server pool as fallback
        keys = [user_key] + [k for k in _SERVER_KEYS if k != user_key]
    else:
        if not _SERVER_KEYS:
            raise ValueError("No Groq API key available.")
        primary = _available_key()
        keys = [primary] + [k for k in _SERVER_KEYS if k != primary]

    last_err: Exception | None = None
    for key in keys:
        try:
            client = Groq(api_key=key)
            return call_fn(client)
        except RateLimitError as exc:
            print(f"[groq_client] 429 on …{key[-6:]}, rotating to next key")
            _cool_down(key, RATE_LIMIT_COOLDOWN)
            last_err = exc
        except AuthenticationError as exc:
            print(f"[groq_client] 401 on …{key[-6:]}, marking invalid")
            _cool_down(key, AUTH_ERROR_COOLDOWN)
            last_err = exc
        except Exception:
            raise   # non-rate-limit errors bubble up immediately

    raise last_err or RuntimeError("All Groq keys exhausted.")


# ── RotatingGroqClient — drop-in replacement for groq.Groq ───────────────────
class _RotatingCompletions:
    """Mimics groq.resources.chat.Completions — rotates keys on every .create()."""
    def __init__(self, preferred_key: str):
        self._preferred = preferred_key

    def create(self, **kwargs):
        return groq_with_rotation(
            lambda c: c.chat.completions.create(**kwargs),
            preferred_key=self._preferred,
        )


class _RotatingChat:
    """Mimics groq.resources.Chat."""
    def __init__(self, preferred_key: str):
        self.completions = _RotatingCompletions(preferred_key)


class RotatingGroqClient:
    """
    Drop-in replacement for groq.Groq that auto-rotates through all pool keys
    on 429 / auth errors.  Use exactly like groq.Groq:

        client = make_groq_client("gsk_...")
        resp   = client.chat.completions.create(model=..., messages=...)
    """
    def __init__(self, preferred_key: str = ""):
        self._preferred = preferred_key.strip()
        self.chat       = _RotatingChat(self._preferred)
        # Expose api_key for any compatibility checks (e.g. news_rag.py)
        self.api_key    = self._preferred


# ── Public API ────────────────────────────────────────────────────────────────
def make_groq_client(preferred_key: str = "") -> RotatingGroqClient:
    """
    Return a RotatingGroqClient.  If preferred_key is non-empty, it is tried
    first; on 429/401 the client transparently falls back through the server
    pool (GROQ_API_KEY_2 / _3 / _4).
    """
    key = preferred_key.strip() or _available_key()
    if not key:
        raise ValueError(
            "No Groq API key available. "
            "Add one in the app Settings or set GROQ_API_KEY on the server."
        )
    return RotatingGroqClient(key)


def resolve_key(user_key: str = "") -> str:
    """
    Return user_key if non-empty, otherwise the best available server key.
    Useful when you need the raw key string (e.g. to pass to a third-party lib).
    """
    return user_key.strip() or _available_key()


def pool_status() -> dict:
    """Return a snapshot of the key pool (for /api/debug/groq-pool if needed)."""
    now = time.time()
    return {
        "total_keys": len(_SERVER_KEYS),
        "available": sum(1 for k in _SERVER_KEYS if _cooldowns.get(k, 0) <= now),
        "cooldowns": {f"key_{i+1}": max(0.0, round(_cooldowns.get(k, 0) - now, 1))
                      for i, k in enumerate(_SERVER_KEYS)},
    }
