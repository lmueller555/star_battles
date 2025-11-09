"""Target acquisition, lock handling, and gimbals."""
from __future__ import annotations

from math import radians
from typing import Iterable, Optional

try:  # pragma: no cover - optional dependency for type hints
    from pygame.math import Vector3
except ModuleNotFoundError:  # pragma: no cover
    class Vector3:  # type: ignore
        ...

from game.math.ballistics import compute_lead
from game.ships.ship import Ship, WeaponMount


LOCK_RATE = 1.2  # progress per second when criteria met
LOCK_DECAY = 1.0  # decay per second when broken


def pick_nearest_target(origin: Ship, candidates: Iterable[Ship]) -> Optional[Ship]:
    closest = None
    closest_dist = float("inf")
    for ship in candidates:
        if ship.team == origin.team or not ship.is_alive():
            continue
        distance = ship.kinematics.position.distance_to(origin.kinematics.position)
        if distance < closest_dist:
            closest = ship
            closest_dist = distance
    return closest


def _angle_to_target(mount: WeaponMount, ship: Ship, target: Ship) -> float:
    forward = ship.kinematics.forward()
    to_target = (target.kinematics.position - ship.kinematics.position).normalize()
    return forward.angle_to(to_target)


def is_within_gimbal(mount: WeaponMount, ship: Ship, target: Ship) -> bool:
    angle = _angle_to_target(mount, ship, target)
    return angle <= mount.hardpoint.gimbal


def update_lock(ship: Ship, target: Optional[Ship], dt: float) -> None:
    if not target or not target.is_alive():
        ship.lock_progress = max(0.0, ship.lock_progress - LOCK_DECAY * dt)
        return
    to_target = target.kinematics.position - ship.kinematics.position
    distance = to_target.length()
    if distance > ship.stats.dradis_range:
        ship.lock_progress = max(0.0, ship.lock_progress - LOCK_DECAY * dt)
        return
    forward = ship.kinematics.forward()
    angle = radians(forward.angle_to(to_target.normalize()))
    if angle > radians(40.0):
        ship.lock_progress = max(0.0, ship.lock_progress - LOCK_DECAY * dt)
        return
    ship.lock_progress = min(1.0, ship.lock_progress + LOCK_RATE * dt)

__all__ = [
    "pick_nearest_target",
    "update_lock",
    "is_within_gimbal",
]
