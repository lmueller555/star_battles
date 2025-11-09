"""DRADIS sensor modelling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from pygame.math import Vector3

from game.ships.ship import Ship


@dataclass
class DradisContact:
    ship: Ship
    distance: float
    confidence: float


class DradisSystem:
    def __init__(self, owner: Ship) -> None:
        self.owner = owner
        self.contacts: Dict[int, DradisContact] = {}

    def update(self, ships: Iterable[Ship], dt: float) -> None:
        self.contacts.clear()
        for ship in ships:
            if ship is self.owner or not ship.is_alive():
                continue
            offset = ship.kinematics.position - self.owner.kinematics.position
            distance = offset.length()
            if distance > self.owner.stats.dradis_range:
                continue
            edge = self.owner.stats.dradis_range
            confidence = max(0.1, 1.0 - max(0.0, distance - edge * 0.7) / (edge * 0.3))
            self.contacts[id(ship)] = DradisContact(ship, distance, confidence)

    def nearest_hostile(self) -> Ship | None:
        best = None
        dist = float("inf")
        for contact in self.contacts.values():
            if contact.ship.team == self.owner.team:
                continue
            if contact.distance < dist:
                best = contact.ship
                dist = contact.distance
        return best


__all__ = ["DradisSystem", "DradisContact"]
