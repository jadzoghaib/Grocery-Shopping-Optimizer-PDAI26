"""Simple in-memory caching layer — drop-in replacement for @st.cache_data."""

import threading

_store = {}
_lock = threading.RLock()  # RLock so nested @cache_data calls don't deadlock


def cache_data(func=None, *, ttl=None, show_spinner=True):
    def decorator(f):
        key = f"{f.__module__}.{f.__qualname__}"

        def wrapper(*args, **kwargs):
            with _lock:
                if key not in _store:
                    _store[key] = f(*args, **kwargs)
                return _store[key]

        wrapper.__wrapped__ = f
        wrapper.__name__ = f.__name__
        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


cache_resource = cache_data
