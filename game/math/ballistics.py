"""Math helpers for ballistics and targeting."""
from __future__ import annotations

from typing import Protocol


class VectorLike(Protocol):
    x: float
    y: float
    z: float

    def __sub__(self, other: "VectorLike") -> "VectorLike":
        ...

    def __add__(self, other: "VectorLike") -> "VectorLike":
        ...

    def __mul__(self, scalar: float) -> "VectorLike":
        ...

    def dot(self, other: "VectorLike") -> float:
        ...


def compute_lead(origin: VectorLike, target_pos: VectorLike, target_vel: VectorLike, projectile_speed: float) -> VectorLike:
    """Analytic intercept solution assuming constant velocity target."""

    if projectile_speed <= 0.0:
        return target_pos
    to_target = target_pos - origin
    a = target_vel.dot(target_vel) - projectile_speed ** 2
    b = 2 * target_vel.dot(to_target)
    c = to_target.dot(to_target)
    disc = b * b - 4 * a * c
    if disc < 0.0 or abs(a) < 1e-6:
        return target_pos
    sqrt_disc = disc ** 0.5
    t1 = (-b - sqrt_disc) / (2 * a)
    t2 = (-b + sqrt_disc) / (2 * a)
    t_candidates = [t for t in (t1, t2) if t > 0]
    if not t_candidates:
        return target_pos
    t = min(t_candidates)
    return target_pos + target_vel * t


__all__ = ["compute_lead", "VectorLike"]
