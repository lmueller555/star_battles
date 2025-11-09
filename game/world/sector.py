"""Sector map data structures."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class StarSystem:
    """A single star system entry on the sector map."""

    id: str
    name: str
    position: tuple[float, float]
    threat: bool = False


class SectorMap:
    """Loads and queries two-dimensional sector data."""

    def __init__(self) -> None:
        self._systems: Dict[str, StarSystem] = {}
        self._default: Optional[str] = None

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return
        systems: Dict[str, StarSystem] = {}
        for entry in data:
            system = StarSystem(
                id=entry["id"],
                name=entry.get("name", entry["id"].title()),
                position=tuple(entry.get("position", (0.0, 0.0))),
                threat=bool(entry.get("threat", False)),
            )
            systems[system.id] = system
        self._systems = systems
        if self._systems and self._default not in self._systems:
            # Pick a stable default (first sorted id) to avoid platform-dependent ordering.
            self._default = sorted(self._systems.keys())[0]

    def all_systems(self) -> Iterable[StarSystem]:
        return self._systems.values()

    def get(self, system_id: str) -> StarSystem:
        return self._systems[system_id]

    def default_system(self) -> Optional[StarSystem]:
        return self._systems.get(self._default) if self._default else None

    def bounds(self) -> tuple[float, float, float, float]:
        if not self._systems:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [system.position[0] for system in self._systems.values()]
        ys = [system.position[1] for system in self._systems.values()]
        return (min(xs), min(ys), max(xs), max(ys))

    def distance(self, a_id: str, b_id: str) -> float:
        if a_id == b_id:
            return 0.0
        a = self.get(a_id)
        b = self.get(b_id)
        return hypot(b.position[0] - a.position[0], b.position[1] - a.position[1])

    def reachable(self, origin_id: str, range_ly: float) -> list[StarSystem]:
        return [
            system
            for system in self._systems.values()
            if system.id != origin_id and self.distance(origin_id, system.id) <= range_ly
        ]


__all__ = ["SectorMap", "StarSystem"]
