"""Ship frame data loading."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from pygame.math import Vector3

from .stats import ShipSlotLayout, ShipStats


@dataclass
class Hardpoint:
    id: str
    slot: str
    position: Vector3
    gimbal: float
    tracking_speed: float
    group: str = "primary"


@dataclass
class ShipFrame:
    id: str
    name: str
    role: str
    size: str
    stats: ShipStats
    slots: ShipSlotLayout
    hardpoints: List[Hardpoint]

    @classmethod
    def from_dict(cls, data: Dict) -> "ShipFrame":
        hardpoints = [
            Hardpoint(
                id=item["id"],
                slot=item["slot"],
                position=Vector3(*item.get("position", [0.0, 0.0, 0.0])),
                gimbal=float(item.get("gimbal", 20.0)),
                tracking_speed=float(item.get("tracking_speed", 180.0)),
                group=item.get("group", "primary"),
            )
            for item in data.get("hardpoints", [])
        ]
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            role=data.get("role", "Interceptor"),
            size=data.get("size", "Strike"),
            stats=ShipStats.from_dict(data.get("stats", {})),
            slots=ShipSlotLayout.from_dict(data.get("slots", {})),
            hardpoints=hardpoints,
        )


class ShipDatabase:
    """Loads ship frames from JSON assets."""

    def __init__(self) -> None:
        self.frames: Dict[str, ShipFrame] = {}

    def load_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                frame = ShipFrame.from_dict(entry)
                self.frames[frame.id] = frame

    def get(self, frame_id: str) -> ShipFrame:
        return self.frames[frame_id]


__all__ = ["ShipFrame", "ShipDatabase", "Hardpoint"]
