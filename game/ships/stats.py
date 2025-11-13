"""Ship stat definitions and aggregation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional, Tuple


@dataclass
class UpgradeValue:
    """Container for upgradeable stat values."""

    base: float
    advanced_delta: float = 0.0
    advanced_total: Optional[float] = None

    def __post_init__(self) -> None:
        if self.advanced_total is None:
            self.advanced_total = self.base + self.advanced_delta

    def as_tuple(self) -> Tuple[float, float, float]:
        total = self.advanced_total if self.advanced_total is not None else self.base + self.advanced_delta
        return (self.base, self.advanced_delta, total)


def _coerce_upgrade(value: Any, default: float) -> Tuple[float, Optional[UpgradeValue]]:
    if isinstance(value, dict):
        base_raw = value.get("base", value.get("value", default))
        base = float(base_raw) if base_raw is not None else float(default)
        delta_raw = value.get("advanced_delta", value.get("delta", 0.0))
        delta = float(delta_raw) if delta_raw is not None else 0.0
        total_raw = value.get("advanced_total")
        total = float(total_raw) if total_raw is not None else None
        upgrade = UpgradeValue(base=base, advanced_delta=delta, advanced_total=total)
        return base, upgrade
    if value is None:
        return float(default), None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return float(default), None


def _extract_stat(
    data: Dict[str, Any],
    field: str,
    *aliases: str,
    default: float,
) -> Tuple[float, Optional[UpgradeValue]]:
    for key in (field, *aliases):
        if key in data and data[key] is not None:
            return _coerce_upgrade(data[key], default)
    return float(default), None


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
    upgrades: Dict[str, UpgradeValue] = field(default_factory=dict, repr=False)

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
    def from_dict(cls, data: Dict[str, Any]) -> "ShipStats":
        upgrades: Dict[str, UpgradeValue] = {}

        hull_points, hull_points_up = _extract_stat(data, "hull_points", "hull_hp", default=1000.0)
        if hull_points_up:
            upgrades["hull_points"] = hull_points_up
        hull_regen, hull_regen_up = _extract_stat(
            data, "hull_recovery_per_sec", "hull_regen", default=5.0
        )
        if hull_regen_up:
            upgrades["hull_recovery_per_sec"] = hull_regen_up
        durability, durability_up = _extract_stat(data, "durability", default=200.0)
        if durability_up:
            upgrades["durability"] = durability_up
        armor_value, armor_up = _extract_stat(data, "armor_value", "armor", default=100.0)
        if armor_up:
            upgrades["armor_value"] = armor_up
        crit_defense, crit_up = _extract_stat(data, "critical_defense", "crit_defense", default=0.05)
        if crit_up:
            upgrades["critical_defense"] = crit_up

        avoidance_raw, avoidance_up = _extract_stat(
            data, "avoidance_rating", "avoidance", default=0.05
        )
        if avoidance_raw > 1.0:
            avoidance_rating = avoidance_raw
            avoidance = avoidance_raw / 1000.0
            rating_upgrade = avoidance_up
        else:
            avoidance_rating = avoidance_raw * 1000.0
            avoidance = avoidance_raw
            rating_upgrade = None
            if avoidance_up:
                # Convert avoidance upgrades (ratio-based) into rating space
                rating_base = avoidance_raw * 1000.0
                rating_delta = avoidance_up.advanced_delta * 1000.0
                rating_total = avoidance_up.advanced_total
                rating_total = (
                    rating_total * 1000.0
                    if rating_total is not None
                    else rating_base + rating_delta
                )
                rating_upgrade = UpgradeValue(
                    base=rating_base,
                    advanced_delta=rating_delta,
                    advanced_total=rating_total,
                )
        if rating_upgrade:
            upgrades["avoidance_rating"] = rating_upgrade
            advanced_total = rating_upgrade.advanced_total or (
                rating_upgrade.base + rating_upgrade.advanced_delta
            )
            new_avoidance = (
                advanced_total / 1000.0
                if advanced_total > 1.0
                else advanced_total
            )
            avoidance_delta = new_avoidance - avoidance
            upgrades["avoidance"] = UpgradeValue(
                base=avoidance,
                advanced_delta=avoidance_delta,
                advanced_total=avoidance + avoidance_delta,
            )

        avoidance_fading, avoidance_fading_up = _extract_stat(
            data, "avoidance_fading", default=0.75
        )
        if avoidance_fading_up:
            upgrades["avoidance_fading"] = avoidance_fading_up

        speed, speed_up = _extract_stat(data, "speed", "max_speed", default=80.0)
        if speed_up:
            upgrades["speed"] = speed_up
        boost_speed, boost_speed_up = _extract_stat(
            data, "boost_speed", default=speed
        )
        if boost_speed_up:
            upgrades["boost_speed"] = boost_speed_up
        acceleration, acceleration_up = _extract_stat(data, "acceleration", default=55.0)
        if acceleration_up:
            upgrades["acceleration"] = acceleration_up
        boost_acceleration, boost_accel_up = _extract_stat(
            data,
            "boost_acceleration",
            "boost_accel",
            default=acceleration,
        )
        if boost_accel_up:
            upgrades["boost_acceleration"] = boost_accel_up
        strafe_speed, strafe_speed_up = _extract_stat(
            data, "strafe_speed", "strafe_cap", default=0.0
        )
        if strafe_speed_up:
            upgrades["strafe_speed"] = strafe_speed_up
        strafe_accel, strafe_accel_up = _extract_stat(
            data, "strafe_acceleration", "strafe_accel", default=0.0
        )
        if strafe_accel_up:
            upgrades["strafe_acceleration"] = strafe_accel_up
        turn_rate, turn_rate_up = _extract_stat(data, "turn_rate", default=90.0)
        if turn_rate_up:
            upgrades["turn_rate"] = turn_rate_up
        turn_accel, turn_accel_up = _extract_stat(data, "turn_accel", default=180.0)
        if turn_accel_up:
            upgrades["turn_accel"] = turn_accel_up
        pitch_speed, pitch_speed_up = _extract_stat(
            data, "pitch_speed", default=turn_rate
        )
        if pitch_speed_up:
            upgrades["pitch_speed"] = pitch_speed_up
        yaw_speed, yaw_speed_up = _extract_stat(
            data, "yaw_speed", default=turn_rate
        )
        if yaw_speed_up:
            upgrades["yaw_speed"] = yaw_speed_up
        roll_speed, roll_speed_up = _extract_stat(
            data, "roll_speed", default=turn_rate
        )
        if roll_speed_up:
            upgrades["roll_speed"] = roll_speed_up
        pitch_accel, pitch_accel_up = _extract_stat(
            data, "pitch_acceleration", default=turn_accel
        )
        if pitch_accel_up:
            upgrades["pitch_acceleration"] = pitch_accel_up
        yaw_accel, yaw_accel_up = _extract_stat(
            data, "yaw_acceleration", default=turn_accel
        )
        if yaw_accel_up:
            upgrades["yaw_acceleration"] = yaw_accel_up
        roll_accel, roll_accel_up = _extract_stat(
            data, "roll_acceleration", default=turn_accel
        )
        if roll_accel_up:
            upgrades["roll_acceleration"] = roll_accel_up

        inertial_comp, inertial_comp_up = _extract_stat(
            data, "inertial_compensation", "inertia_comp", default=0.8
        )
        if inertial_comp_up:
            upgrades["inertial_compensation"] = inertial_comp_up

        boost_cost, boost_cost_up = _extract_stat(
            data, "boost_cost", "boost_drain", default=18.0
        )
        if boost_cost_up:
            upgrades["boost_cost"] = boost_cost_up
        power_points, power_points_up = _extract_stat(
            data, "power_points", "power_cap", default=150.0
        )
        if power_points_up:
            upgrades["power_points"] = power_points_up
        power_recovery, power_recovery_up = _extract_stat(
            data, "power_recovery_per_sec", "power_regen", default=45.0
        )
        if power_recovery_up:
            upgrades["power_recovery_per_sec"] = power_recovery_up
        firewall_rating, firewall_up = _extract_stat(
            data, "firewall_rating", "firewall", default=120.0
        )
        if firewall_up:
            upgrades["firewall_rating"] = firewall_up
        emitter_rating, emitter_up = _extract_stat(
            data, "emitter_rating", "emitter", default=120.0
        )
        if emitter_up:
            upgrades["emitter_rating"] = emitter_up

        dradis_max, dradis_max_up = _extract_stat(
            data, "dradis_range_max", "dradis_range", default=3000.0
        )
        if dradis_max_up:
            upgrades["dradis_range_max"] = dradis_max_up
        dradis_base, dradis_base_up = _extract_stat(
            data, "dradis_range_base", default=dradis_max
        )
        if dradis_base_up:
            upgrades["dradis_range_base"] = dradis_base_up

        visual_range, visual_up = _extract_stat(data, "visual_range", default=800.0)
        if visual_up:
            upgrades["visual_range"] = visual_up

        ftl_range, ftl_range_up = _extract_stat(data, "ftl_range", default=10.0)
        if ftl_range_up:
            upgrades["ftl_range"] = ftl_range_up
        ftl_charge, ftl_charge_up = _extract_stat(
            data, "ftl_charge_time", "ftl_charge", default=15.0
        )
        if ftl_charge_up:
            upgrades["ftl_charge_time"] = ftl_charge_up
        ftl_cooldown, ftl_cooldown_up = _extract_stat(
            data, "ftl_cooldown", "ftl_threat_charge", default=30.0
        )
        if ftl_cooldown_up:
            upgrades["ftl_cooldown"] = ftl_cooldown_up
        ftl_cost, ftl_cost_up = _extract_stat(
            data, "ftl_cost", "ftl_cost_per_ly", default=25.0
        )
        if ftl_cost_up:
            upgrades["ftl_cost"] = ftl_cost_up

        transponder_cost, transponder_cost_up = _extract_stat(
            data, "transponder_power_cost", default=0.0
        )
        if transponder_cost_up:
            upgrades["transponder_power_cost"] = transponder_cost_up
        durability_bonus, durability_bonus_up = _extract_stat(
            data, "durability_bonus", default=0.0
        )
        if durability_bonus_up:
            upgrades["durability_bonus"] = durability_bonus_up
        max_radiation, max_radiation_up = _extract_stat(
            data, "max_radiation_level", default=0.0
        )
        if max_radiation_up:
            upgrades["max_radiation_level"] = max_radiation_up
        radioactive_decay, radioactive_decay_up = _extract_stat(
            data, "radioactive_decay", default=0.0
        )
        if radioactive_decay_up:
            upgrades["radioactive_decay"] = radioactive_decay_up
        radioresistance, radioresistance_up = _extract_stat(
            data, "radioresistance", default=0.0
        )
        if radioresistance_up:
            upgrades["radioresistance"] = radioresistance_up

        stats = cls(
            hull_points=hull_points,
            hull_recovery_per_sec=hull_regen,
            durability=durability,
            armor_value=armor_value,
            critical_defense=crit_defense,
            avoidance=avoidance,
            avoidance_rating=avoidance_rating,
            avoidance_fading=avoidance_fading,
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
            inertial_compensation=inertial_comp,
            boost_cost=boost_cost,
            power_points=power_points,
            power_recovery_per_sec=power_recovery,
            firewall_rating=firewall_rating,
            emitter_rating=emitter_rating,
            dradis_range_base=dradis_base,
            dradis_range_max=dradis_max,
            visual_range=visual_range,
            ftl_range=ftl_range,
            ftl_charge_time=ftl_charge,
            ftl_cooldown=ftl_cooldown,
            ftl_cost=ftl_cost,
            transponder_power_cost=transponder_cost,
            durability_bonus=durability_bonus,
            max_radiation_level=max_radiation,
            radioactive_decay=radioactive_decay,
            radioresistance=radioresistance,
        )
        stats.upgrades = upgrades
        return stats

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
    upgrades: Dict[str, UpgradeValue] = field(default_factory=dict)
    weapon_upgrades: Dict[str, UpgradeValue] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ShipSlotLayout":
        upgrades: Dict[str, UpgradeValue] = {}
        weapon_upgrades: Dict[str, UpgradeValue] = {}

        def parse_slot(value: Any, default: int = 0) -> Tuple[int, Optional[UpgradeValue]]:
            base, upgrade = _coerce_upgrade(value, default)
            return int(base), upgrade

        weapon_families: Dict[str, int] = {}
        weapons_data = data.get("weapons")
        if isinstance(weapons_data, dict):
            for key, value in weapons_data.items():
                count, upgrade = parse_slot(value, 0)
                weapon_families[str(key)] = count
                if upgrade:
                    weapon_upgrades[str(key)] = upgrade
        else:
            for key in ("cannon", "launcher", "gun", "guns", "defensive"):
                if key in data:
                    count, upgrade = parse_slot(data[key], 0)
                    weapon_families[str(key)] = count
                    if upgrade:
                        weapon_upgrades[str(key)] = upgrade

        hull_count, hull_upgrade = parse_slot(data.get("hull", 0), 0)
        if hull_upgrade:
            upgrades["hull"] = hull_upgrade
        engine_count, engine_upgrade = parse_slot(data.get("engine", 0), 0)
        if engine_upgrade:
            upgrades["engine"] = engine_upgrade
        computer_count, computer_upgrade = parse_slot(data.get("computer", 0), 0)
        if computer_upgrade:
            upgrades["computer"] = computer_upgrade
        utility_count, utility_upgrade = parse_slot(data.get("utility", 0), 0)
        if utility_upgrade:
            upgrades["utility"] = utility_upgrade

        return cls(
            weapon_families=weapon_families,
            hull=hull_count,
            engine=engine_count,
            computer=computer_count,
            utility=utility_count,
            upgrades=upgrades,
            weapon_upgrades=weapon_upgrades,
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

    @property
    def special(self) -> int:
        return self.weapon_capacity("special")


__all__ = ["ShipStats", "ShipSlotLayout", "UpgradeValue"]
