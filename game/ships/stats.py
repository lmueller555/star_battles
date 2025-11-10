"""Ship stat definitions and aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class ShipStats:
    hull_hp: float
    hull_regen: float
    armor: float
    durability: float
    avoidance: float
    avoidance_rating: float
    crit_defense: float
    max_speed: float
    boost_speed: float
    acceleration: float
    strafe_accel: float
    strafe_cap: float
    turn_rate: float
    turn_accel: float
    inertia_comp: float
    boost_drain: float
    power_cap: float
    power_regen: float
    firewall: float
    emitter: float
    dradis_range: float
    visual_range: float
    ftl_range: float
    ftl_charge: float
    ftl_threat_charge: float
    ftl_cost_per_ly: float

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "ShipStats":
        avoidance_value = data.get("avoidance", 0.05)
        if avoidance_value > 1.0:
            avoidance = avoidance_value / 1000.0
        else:
            avoidance = avoidance_value
        return cls(
            hull_hp=data.get("hull_hp", 1000.0),
            hull_regen=data.get("hull_regen", 5.0),
            armor=data.get("armor", 100.0),
            durability=data.get("durability", 200.0),
            avoidance=avoidance,
            avoidance_rating=avoidance_value,
            crit_defense=data.get("crit_defense", 0.05),
            max_speed=data.get("max_speed", 80.0),
            boost_speed=data.get("boost_speed", 140.0),
            acceleration=data.get("acceleration", 55.0),
            strafe_accel=data.get("strafe_accel", 35.0),
            strafe_cap=data.get("strafe_cap", 25.0),
            turn_rate=data.get("turn_rate", 90.0),
            turn_accel=data.get("turn_accel", 180.0),
            inertia_comp=data.get("inertia_comp", 0.8),
            boost_drain=data.get("boost_drain", 18.0),
            power_cap=data.get("power_cap", 150.0),
            power_regen=data.get("power_regen", 45.0),
            firewall=data.get("firewall", 120.0),
            emitter=data.get("emitter", 120.0),
            dradis_range=data.get("dradis_range", 3000.0),
            visual_range=data.get("visual_range", 800.0),
            ftl_range=data.get("ftl_range", 10.0),
            ftl_charge=data.get("ftl_charge", 15.0),
            ftl_threat_charge=data.get("ftl_threat_charge", 30.0),
            ftl_cost_per_ly=data.get("ftl_cost_per_ly", 25.0),
        )

    @property
    def cruise_speed(self) -> float:
        """Alias for readability when referring to base speed."""

        return self.max_speed


@dataclass
class ShipSlotLayout:
    weapon_families: Dict[str, int]
    hull: int
    engine: int
    computer: int
    utility: int

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "ShipSlotLayout":
        weapon_families: Dict[str, int] = {}
        if "weapons" in data and isinstance(data["weapons"], dict):
            weapon_families.update({str(key): int(value) for key, value in data["weapons"].items()})
        else:
            for key in ("cannon", "launcher", "gun", "guns", "defensive"):
                if key in data:
                    weapon_families[str(key)] = int(data[key])
        return cls(
            weapon_families=weapon_families,
            hull=int(data.get("hull", 0)),
            engine=int(data.get("engine", 0)),
            computer=int(data.get("computer", 0)),
            utility=int(data.get("utility", 0)),
        )

    def weapon_capacity(self, slot_type: str) -> int:
        return int(self.weapon_families.get(slot_type, 0))

    @property
    def cannon(self) -> int:
        return self.weapon_capacity("cannon")

    @property
    def launcher(self) -> int:
        return self.weapon_capacity("launcher")

    @property
    def guns(self) -> int:
        return self.weapon_capacity("guns") or self.weapon_capacity("gun")

    @property
    def defensive(self) -> int:
        return self.weapon_capacity("defensive")


__all__ = ["ShipStats", "ShipSlotLayout"]
