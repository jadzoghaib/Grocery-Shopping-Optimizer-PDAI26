"""Small statistics helpers shared by the Pass-1 and Pass-3 metric modules.

Pure stdlib — no numpy, no scipy. The Wilson interval is used instead of
the normal-approximation interval because it's well-behaved for small N
and proportions near 0/1, which is exactly where our eval results live.
"""
from __future__ import annotations

import math


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% confidence interval for a binomial proportion.

    Returns ``(lo, hi)``; ``(0.0, 0.0)`` when ``n == 0``.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def fmt_ci(ci: tuple[float, float]) -> str:
    lo, hi = ci
    return f"[{lo*100:.1f}%, {hi*100:.1f}%]"
