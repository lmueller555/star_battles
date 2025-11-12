"""Ship stat definitions and aggregation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict


def _lookup(data: Dict[str, float], *keys: str, default: float) -> float:
    for key in keys:
        if key in data and data[key] is not None:
            return float(data[key])
    return float(default)


@dataclass
class ShipStats:
    hull_points: float
    hull_recovery_per_sec: float
    durability: float
    armor_value: float
    critical_defense: float
    avoidance: float
    avoidance_rating: float
    avoidance_fading: float
    speed: float
    boost_speed: float
    acceleration: float
    boost_acceleration: float
    strafe_speed: float
    strafe_acceleration: float
    turn_rate: float
    turn_accel: float
    pitch_speed: float
    yaw_speed: float
    roll_speed: float
    pitch_acceleration: float
    yaw_acceleration: float
    roll_acceleration: float
    inertial_compensation: float
    boost_cost: float
    power_points: float
    power_recovery_per_sec: float
    firewall_rating: float
    emitter_rating: float
    dradis_range_base: float
    dradis_range_max: float
    visual_range: float
    ftl_range: float
    ftl_charge_time: float
    ftl_cooldown: float
    ftl_cost: float
    transponder_power_cost: float
    durability_bonus: float
    max_radiation_level: float
    radioactive_decay: float
    radioresistance: float

    _ALIASES: ClassVar[Dict[str, str]] = {
        "hull_hp": "hull_points",
        "hull_regen": "hull_recovery_per_sec",
        "armor": "armor_value",
        "crit_defense": "critical_defense",
        "max_speed": "speed",
        "boost_drain": "boost_cost",
        "power_cap": "power_points",
        "power_regen": "power_recovery_per_sec",
        "firewall": "firewall_rating",
        "emitter": "emitter_rating",
        "dradis_range": "dradis_range_max",
        "ftl_charge": "ftl_charge_time",
        "ftl_threat_charge": "ftl_cooldown",
        "ftl_cost_per_ly": "ftl_cost",
        "inertia_comp": "inertial_compensation",
        "strafe_cap": "strafe_speed",
        "strafe_accel": "strafe_acceleration",
    }

    def __setattr__(self, key: str, value: float) -> None:
        target = self._ALIASES.get(key, key)
        object.__setattr__(self, target, value)

    def __getattr__(self, key: str) -> float:
        target = self._ALIASES.get(key)
        if target is None:
            raise AttributeError(key)
        return getattr(self, target)

    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "ShipStats":
        avoidance_value = _lookup(data, "avoidance_rating", "avoidance", default=0.05)
        if avoidance_value > 1.0:
            avoidance_rating = avoidance_value
            avoidance = avoidance_value / 1000.0
        else:
            avoidance_rating = avoidance_value * 1000.0
            avoidance = avoidance_value

        speed = _lookup(data, "speed", "max_speed", default=80.0)
        boost_speed = _lookup(data, "boost_speed", default=speed)
        acceleration = _lookup(data, "acceleration", default=55.0)
        boost_acceleration = _lookup(
            data, "boost_acceleration", default=_lookup(data, "boost_accel", default=acceleration)
        )
        strafe_speed = _lookup(data, "strafe_speed", "strafe_cap", default=0.0)
        strafe_accel = _lookup(data, "strafe_acceleration", "strafe_accel", default=0.0)
        turn_rate = _lookup(data, "turn_rate", default=90.0)
        turn_accel = _lookup(data, "turn_accel", default=180.0)
        pitch_speed = _lookup(data, "pitch_speed", default=turn_rate)
        yaw_speed = _lookup(data, "yaw_speed", default=turn_rate)
        roll_speed = _lookup(data, "roll_speed", default=turn_rate)
        pitch_accel = _lookup(data, "pitch_acceleration", default=turn_accel)
        yaw_accel = _lookup(data, "yaw_acceleration", default=turn_accel)
        roll_accel = _lookup(data, "roll_acceleration", default=turn_accel)
        dradis_max = _lookup(data, "dradis_range_max", "dradis_range", default=3000.0)
        dradis_base = _lookup(data, "dradis_range_base", default=dradis_max)

        return cls(
            hull_points=_lookup(data, "hull_points", "hull_hp", default=1000.0),
            hull_recovery_per_sec=_lookup(data, "hull_recovery_per_sec", "hull_regen", default=5.0),
            durability=_lookup(data, "durability", default=200.0),
            armor_value=_lookup(data, "armor_value", "armor", default=100.0),
            critical_defense=_lookup(data, "critical_defense", "crit_defense", default=0.05),
            avoidance=avoidance,
            avoidance_rating=avoidance_rating,
            avoidance_fading=_lookup(data, "avoidance_fading", default=0.75),
            speed=speed,
            boost_speed=boost_speed,
            acceleration=acceleration,
            boost_acceleration=boost_acceleration,
            strafe_speed=strafe_speed,
            strafe_acceleration=strafe_accel,
            turn_rate=turn_rate,
            turn_accel=turn_accel,
            pitch_speed=pitch_speed,
            yaw_speed=yaw_speed,
            roll_speed=roll_speed,
            pitch_acceleration=pitch_accel,
            yaw_acceleration=yaw_accel,
            roll_acceleration=roll_accel,
            inertial_compensation=_lookup(
                data, "inertial_compensation", "inertia_comp", default=0.8
            ),
            boost_cost=_lookup(data, "boost_cost", "boost_drain", default=18.0),
            power_points=_lookup(data, "power_points", "power_cap", default=150.0),
            power_recovery_per_sec=_lookup(
                data, "power_recovery_per_sec", "power_regen", default=45.0
            ),
            firewall_rating=_lookup(data, "firewall_rating", "firewall", default=120.0),
            emitter_rating=_lookup(data, "emitter_rating", "emitter", default=120.0),
            dradis_range_base=dradis_base,
            dradis_range_max=dradis_max,
            visual_range=_lookup(data, "visual_range", default=800.0),
            ftl_range=_lookup(data, "ftl_range", default=10.0),
            ftl_charge_time=_lookup(data, "ftl_charge_time", "ftl_charge", default=15.0),
            ftl_cooldown=_lookup(
                data, "ftl_cooldown", "ftl_threat_charge", default=30.0
            ),
            ftl_cost=_lookup(data, "ftl_cost", "ftl_cost_per_ly", default=25.0),
            transponder_power_cost=_lookup(
                data, "transponder_power_cost", default=0.0
            ),
            durability_bonus=_lookup(data, "durability_bonus", default=0.0),
            max_radiation_level=_lookup(data, "max_radiation_level", default=0.0),
            radioactive_decay=_lookup(data, "radioactive_decay", default=0.0),
            radioresistance=_lookup(data, "radioresistance", default=0.0),
        )

    @property
    def cruise_speed(self) -> float:
        """Alias for readability when referring to base speed."""

        return self.speed


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
