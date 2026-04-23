"""Shared in-memory cache between FastAPI and the Dash app.

Both live in the same Python process, so a module-level dict
acts as a simple shared store with zero serialisation overhead.

Usage:
    from dashboards.cache import store, fetch

    store("meal_plan", list_of_records)
    data = fetch("meal_plan")          # returns [] if nothing stored yet
"""
from __future__ import annotations
from typing import Any

_data: dict[str, Any] = {
    "meal_plan":    [],   # list of meal-plan row dicts
    "shopping":     [],   # list of shopping-list row dicts
    "history":      [],   # list of history session dicts
    "plan_targets": {},   # nutrition targets used when generating the plan
}


def store(key: str, value: Any) -> None:
    """Store a value under *key*. Overwrites any previous value."""
    _data[key] = value


def fetch(key: str, default: Any = None):
    """Fetch the value stored under *key*, or *default* if not present."""
    return _data.get(key, default if default is not None else [])
