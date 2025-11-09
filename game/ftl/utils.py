"""FTL helper formulas."""
from __future__ import annotations


def compute_ftl_cost(distance_ly: float, cost_per_ly: float) -> float:
    return max(0.0, distance_ly) * max(0.0, cost_per_ly)


def compute_ftl_charge(base_charge: float, threat_charge: float, in_threat: bool) -> float:
    return threat_charge if in_threat else base_charge


__all__ = ["compute_ftl_cost", "compute_ftl_charge"]
