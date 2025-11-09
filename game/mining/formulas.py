"""Mining yield helpers."""
from __future__ import annotations


def compute_mining_yield(base: float, grade: float, bonus: float, stability: float) -> float:
    stability_factor = max(0.0, min(1.0, stability))
    return base * grade * (1.0 + bonus) * stability_factor


__all__ = ["compute_mining_yield"]
