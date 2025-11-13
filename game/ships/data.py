"""Ship frame data loading."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from pygame.math import Vector3

from .stats import ShipSlotLayout, ShipStats


_FACING_VECTORS = {
    "forward": (0.0, 0.0, 1.0),
    "front": (0.0, 0.0, 1.0),
    "left": (-1.0, 0.0, 0.0),
    "right": (1.0, 0.0, 0.0),
    "rear": (0.0, 0.0, -1.0),
    "back": (0.0, 0.0, -1.0),
}


def _normalise_facing(value: str | None) -> str:
    if not value:
        return "forward"
    key = value.strip().lower()
    if key in ("front", "forwards"):
        return "forward"
    if key in ("aft", "rear", "back"):
        return "rear"
    if key not in ("forward", "left", "right", "rear"):
        return "forward"
    return key


def _facing_to_vector(facing: str) -> Vector3:
    coords = _FACING_VECTORS.get(facing, _FACING_VECTORS["forward"])
    return Vector3(*coords)


@dataclass
class Hardpoint:
    id: str
    slot: str
    position: Vector3
    gimbal: float
    tracking_speed: float
    group: str = "primary"
    facing: str = "forward"
    orientation: Vector3 | None = None
    custom_facing: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.set_facing(self.facing, self.orientation)

    def set_facing(self, facing: str, orientation: Vector3 | None = None) -> None:
        normalised = _normalise_facing(facing)
        self.facing = normalised
        if orientation is not None and orientation.length_squared() > 0.0:
            vector = Vector3(orientation)
            vector.normalize_ip()
            self.orientation = vector
        else:
            self.orientation = _facing_to_vector(normalised)


_CLASS_FACING_RULES: Dict[str, Dict[str, int | str]] = {
    "escort": {"forward": 2, "left": 2, "right": 2, "extra": "forward"},
    "line": {"forward": 2, "left": 3, "right": 3, "extra": "forward"},
    "capital": {"forward": 3, "left": 3, "right": 3, "extra": "forward"},
}


def _select_front_indices(hardpoints: List[Hardpoint], indices: List[int], count: int) -> List[int]:
    if count <= 0:
        return []
    priority = {
        "launcher": 0,
        "missile": 0,
        "cannon": 1,
        "gun": 1,
    }
    sorted_indices = sorted(
        indices,
        key=lambda idx: (priority.get(hardpoints[idx].slot, 5), idx),
    )
    return sorted_indices[:count]


def _assign_outpost_facings(hardpoints: List[Hardpoint], indices: List[int]) -> None:
    id_to_index = {hardpoints[idx].id: idx for idx in indices}
    assigned: set[int] = set()

    def assign(ids: List[str], facing: str) -> None:
        for hp_id in ids:
            idx = id_to_index.get(hp_id)
            if idx is None or idx in assigned:
                continue
            hardpoints[idx].set_facing(facing)
            assigned.add(idx)

    front_ids = [
        "hp_outpost_launcher_port",
        "hp_outpost_launcher_starboard",
    ]
    left_ids = [
        "hp_outpost_west",
        "hp_outpost_pd_west",
        "hp_outpost_north",
        "hp_outpost_pd_south",
    ]
    right_ids = [
        "hp_outpost_east",
        "hp_outpost_pd_east",
        "hp_outpost_south",
        "hp_outpost_pd_north",
    ]

    assign(front_ids, "forward")
    assign(left_ids, "left")
    assign(right_ids, "right")

    for idx in indices:
        if idx in assigned:
            continue
        hardpoints[idx].set_facing("forward")


def _assign_default_facings(size: str, hardpoints: List[Hardpoint]) -> None:
    if not hardpoints:
        return
    indices = [i for i, hp in enumerate(hardpoints) if not hp.custom_facing]
    if not indices:
        return
    size_key = (size or "").lower()
    if size_key == "strike":
        for idx in indices:
            hardpoints[idx].set_facing("forward")
        return
    if size_key == "outpost":
        _assign_outpost_facings(hardpoints, indices)
        return
    rules = _CLASS_FACING_RULES.get(size_key)
    if not rules:
        for idx in indices:
            hardpoints[idx].set_facing("forward")
        return
    front_target = int(rules.get("forward", 0))
    front_indices = _select_front_indices(hardpoints, indices, min(front_target, len(indices)))
    assigned = set(front_indices)
    remaining = [idx for idx in indices if idx not in assigned]

    def _consume(target_count: int) -> List[int]:
        take = min(target_count, len(remaining))
        picked = remaining[:take]
        del remaining[:take]
        assigned.update(picked)
        return picked

    left_target = int(rules.get("left", 0))
    right_target = int(rules.get("right", 0))
    extra_facing = str(rules.get("extra", "forward"))

    left_indices = _consume(left_target)
    right_indices = _consume(right_target)

    for idx in front_indices:
        hardpoints[idx].set_facing("forward")
    for idx in left_indices:
        hardpoints[idx].set_facing("left")
    for idx in right_indices:
        hardpoints[idx].set_facing("right")
    for idx in remaining:
        hardpoints[idx].set_facing(extra_facing)


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
        hardpoints: List[Hardpoint] = []
        for item in data.get("hardpoints", []):
            orientation_data = item.get("orientation")
            orientation = (
                Vector3(*orientation_data)
                if isinstance(orientation_data, (list, tuple))
                and len(orientation_data) >= 3
                else None
            )
            facing_value = item.get("facing")
            hardpoint = Hardpoint(
                id=item["id"],
                slot=item["slot"],
                position=Vector3(*item.get("position", [0.0, 0.0, 0.0])),
                gimbal=float(item.get("gimbal", 20.0)),
                tracking_speed=float(item.get("tracking_speed", 180.0)),
                group=item.get("group", "primary"),
                facing=facing_value or "forward",
                orientation=orientation,
            )
            hardpoint.custom_facing = bool(facing_value) or orientation is not None
            hardpoints.append(hardpoint)
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
        _assign_default_facings(size, hardpoints)
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
