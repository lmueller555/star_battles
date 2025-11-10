"""Ship frame data loading."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
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
    level_requirement: int = 1
    faction: str = "Neutral"
    counterpart: str | None = None
    upgrade_to: str | None = None
    purchase_cost: Dict[str, float] = field(default_factory=dict)
    upgrade_cost: Dict[str, float] = field(default_factory=dict)
    operating_costs: Dict[str, float] = field(default_factory=dict)
    role_bonuses: List[str] = field(default_factory=list)
    traits: List[str] = field(default_factory=list)
    default_modules: Dict[str, List[str]] = field(default_factory=dict)
    default_weapons: Dict[str, str] = field(default_factory=dict)
    notes: str = ""

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
        economy = data.get("economy", {})
        purchase_cost = economy.get("purchase", data.get("purchase_cost", {}))
        upgrade_cost = economy.get("upgrade", data.get("upgrade_cost", {}))
        operating_costs = economy.get("operating", data.get("operating_costs", {}))
        equipment = data.get("equipment", {})
        modules: Dict[str, List[str]] = {}
        weapons: Dict[str, str] = {}
        if isinstance(equipment, dict):
            module_data = equipment.get("modules", {})
            if isinstance(module_data, dict):
                for key, value in module_data.items():
                    if isinstance(value, (list, tuple)):
                        modules[key] = [str(item) for item in value]
                    else:
                        modules[key] = [str(value)] if value is not None else []
            weapon_data = equipment.get("weapons", {})
            if isinstance(weapon_data, dict):
                weapons = {key: str(value) for key, value in weapon_data.items()}
        size = data.get("size") or data.get("class") or "Strike"
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            role=data.get("role", "Interceptor"),
            size=size,
            stats=ShipStats.from_dict(data.get("stats", {})),
            slots=ShipSlotLayout.from_dict(data.get("slots", {})),
            hardpoints=hardpoints,
            level_requirement=int(data.get("level_requirement", 1)),
            faction=data.get("faction", "Neutral"),
            counterpart=data.get("counterpart"),
            upgrade_to=data.get("upgrade_to"),
            purchase_cost={k: float(v) for k, v in purchase_cost.items()},
            upgrade_cost={k: float(v) for k, v in upgrade_cost.items()},
            operating_costs={k: float(v) for k, v in operating_costs.items()},
            role_bonuses=list(data.get("role_bonuses", [])),
            traits=list(data.get("traits", [])),
            default_modules=modules,
            default_weapons=weapons,
            notes=data.get("notes", ""),
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
