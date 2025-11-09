"""Docking station definitions and loader."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class DockingStation:
    """Represents a dockable station inside a star system."""

    id: str
    name: str
    system_id: str
    position: tuple[float, float, float]
    docking_radius: float


class StationDatabase:
    """Loads docking station metadata from JSON assets."""

    def __init__(self) -> None:
        self._stations: Dict[str, DockingStation] = {}

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return
        stations: Dict[str, DockingStation] = {}
        for entry in data:
            station = DockingStation(
                id=entry["id"],
                name=entry.get("name", entry["id"].title()),
                system_id=entry.get("system"),
                position=tuple(entry.get("position", (0.0, 0.0, 0.0))),
                docking_radius=float(entry.get("dockingRadius", 900.0)),
            )
            if station.system_id:
                stations[station.id] = station
        self._stations = stations

    def get(self, station_id: str) -> DockingStation:
        return self._stations[station_id]

    def in_system(self, system_id: str) -> Iterable[DockingStation]:
        return (station for station in self._stations.values() if station.system_id == system_id)

    def nearest_in_system(
        self, system_id: Optional[str], position: tuple[float, float, float]
    ) -> tuple[Optional[DockingStation], float]:
        if system_id is None:
            return None, float("inf")
        best: Optional[DockingStation] = None
        best_distance = float("inf")
        px, py, pz = position
        for station in self.in_system(system_id):
            sx, sy, sz = station.position
            distance = ((px - sx) ** 2 + (py - sy) ** 2 + (pz - sz) ** 2) ** 0.5
            if distance < best_distance:
                best = station
                best_distance = distance
        return best, best_distance


__all__ = ["DockingStation", "StationDatabase"]
