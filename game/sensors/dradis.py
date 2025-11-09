"""DRADIS sensor modelling."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

from game.ships.ship import Ship


@dataclass
class DradisContact:
    ship: Ship
    distance: float
    confidence: float
    progress: float = 0.0
    detected: bool = False
    time_since_seen: float = 0.0


class DradisSystem:
    def __init__(self, owner: Ship) -> None:
        self.owner = owner
        self.contacts: Dict[int, DradisContact] = {}

    def update(self, ships: Iterable[Ship], dt: float) -> None:
        processed: set[int] = set()
        range_limit = self.owner.stats.dradis_range
        sensor_bonus = 1.0 + self.owner.module_stat_total("sensor_strength")
        for ship in ships:
            if ship is self.owner or not ship.is_alive():
                continue
            offset = ship.kinematics.position - self.owner.kinematics.position
            distance = offset.length()
            contact_id = id(ship)
            contact = self.contacts.get(contact_id)
            if distance <= range_limit:
                if contact is None:
                    contact = DradisContact(ship, distance, 0.0)
                    self.contacts[contact_id] = contact
                contact.ship = ship
                contact.distance = distance
                range_ratio = min(1.0, distance / max(1.0, range_limit))
                base_detection = 0.7 + 1.8 * (range_ratio ** 1.4)
                obfuscation = 1.0 + ship.module_stat_total("sensor_obfuscation")
                detection_rate = sensor_bonus / obfuscation
                contact.progress = min(1.0, contact.progress + dt * detection_rate / base_detection)
                confidence = max(0.1, 1.0 - max(0.0, distance - range_limit * 0.7) / (range_limit * 0.3))
                contact.confidence = confidence * max(0.25, contact.progress)
                contact.detected = contact.progress >= 1.0
                contact.time_since_seen = 0.0
            elif contact is not None:
                contact.time_since_seen += dt
                contact.progress = max(0.0, contact.progress - dt * 0.5)
                contact.confidence = max(0.0, contact.confidence - dt * 0.4)
                if contact.progress < 0.2:
                    contact.detected = False
            if contact_id in self.contacts:
                processed.add(contact_id)
        for contact_id in list(self.contacts.keys()):
            if contact_id in processed:
                continue
            contact = self.contacts[contact_id]
            contact.time_since_seen += dt
            contact.progress = max(0.0, contact.progress - dt * 0.5)
            contact.confidence = max(0.0, contact.confidence - dt * 0.4)
            if contact.progress < 0.2:
                contact.detected = False
            if contact.progress <= 0.0 and contact.time_since_seen > 2.0:
                del self.contacts[contact_id]

    def nearest_hostile(self) -> Ship | None:
        best = None
        dist = float("inf")
        for contact in self.contacts.values():
            if contact.ship.team == self.owner.team or not contact.detected:
                continue
            if contact.distance < dist:
                best = contact.ship
                dist = contact.distance
        return best


__all__ = ["DradisSystem", "DradisContact"]
