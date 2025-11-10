"""Ship entity implementation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from pygame.math import Vector3

from game.assets.content import ItemData
from .data import Hardpoint, ShipFrame
from .stats import ShipStats


@dataclass
class ShipResources:
    tylium: float = 0.0
    titanium: float = 0.0
    water: float = 0.0

    def spend(self, resource: str, amount: float) -> bool:
        current = getattr(self, resource)
        if current < amount:
            return False
        setattr(self, resource, current - amount)
        return True

    def add(self, resource: str, amount: float) -> None:
        setattr(self, resource, getattr(self, resource) + amount)


@dataclass
class ShipControlState:
    throttle: float = 0.0
    boost: bool = False
    brake: bool = False
    strafe: Vector3 = field(default_factory=Vector3)
    roll_input: float = 0.0
    look_delta: Vector3 = field(default_factory=Vector3)


@dataclass
class ShipKinematics:
    position: Vector3
    velocity: Vector3
    rotation: Vector3
    angular_velocity: Vector3

    def forward(self) -> Vector3:
        from math import cos, sin, radians

        pitch, yaw, roll = map(radians, (self.rotation.x, self.rotation.y, self.rotation.z))
        cy = cos(yaw)
        sy = sin(yaw)
        cp = cos(pitch)
        sp = sin(pitch)
        forward = Vector3(cp * sy, -sp, cp * cy)
        return forward.normalize() if forward.length_squared() > 0 else Vector3(0, 0, 1)

    def right(self) -> Vector3:
        from math import cos, sin, radians

        pitch, yaw, roll = map(radians, (self.rotation.x, self.rotation.y, self.rotation.z))
        cy = cos(yaw)
        sy = sin(yaw)
        cr = cos(roll)
        sr = sin(roll)
        right = Vector3(cy * cr + sy * sr, sy * cr - cy * sr, -sr)
        return right.normalize() if right.length_squared() > 0 else Vector3(1, 0, 0)

    def up(self) -> Vector3:
        return self.forward().cross(self.right())


@dataclass
class WeaponMount:
    hardpoint: Hardpoint
    weapon_id: Optional[str] = None
    cooldown: float = 0.0
    lock_progress: float = 0.0


class Ship:
    """Runtime ship instance."""

    def __init__(
        self,
        frame: ShipFrame,
        team: str = "player",
        modules: Optional[Iterable[ItemData]] = None,
    ) -> None:
        self.frame = frame
        self.team = team
        self.stats: ShipStats = frame.stats
        self.kinematics = ShipKinematics(
            position=Vector3(0.0, 0.0, 0.0),
            velocity=Vector3(0.0, 0.0, 0.0),
            rotation=Vector3(0.0, 0.0, 0.0),
            angular_velocity=Vector3(0.0, 0.0, 0.0),
        )
        self.control = ShipControlState()
        self.power = self.stats.power_cap
        self.boost_meter = self.stats.power_cap
        self.hull = self.stats.hull_hp
        self.durability = self.stats.durability
        self.hull_regen_cooldown = 0.0
        self.mounts: List[WeaponMount] = [WeaponMount(hp) for hp in self.frame.hardpoints]
        self.target_id: Optional[int] = None
        self.lock_progress: float = 0.0
        self.lock_decay_delay: float = 0.5
        self.lock_timer: float = 0.0
        self.resources = ShipResources(tylium=320.0, titanium=180.0, water=40.0)
        self.modules_by_slot: Dict[str, list[ItemData]] = defaultdict(list)
        self._module_stat_cache: Dict[str, float] = defaultdict(float)
        self.countermeasure_cooldown: float = 0.0
        self.auto_throttle_enabled: bool = False
        self.auto_throttle_ratio: float = 0.0
        self.auto_level_enabled: bool = True
        self.collision_recoil: float = 0.0
        if modules:
            for module in modules:
                self.equip_module(module)

    def is_alive(self) -> bool:
        return self.hull > 0

    def reset(self) -> None:
        self.power = self.stats.power_cap
        self.boost_meter = self.stats.power_cap
        self.hull = self.stats.hull_hp
        self.durability = self.stats.durability
        self.kinematics.velocity = Vector3()
        self.kinematics.angular_velocity = Vector3()
        self.control = ShipControlState()
        for mount in self.mounts:
            mount.cooldown = 0.0
            mount.lock_progress = 0.0
        self.countermeasure_cooldown = 0.0
        self.auto_throttle_enabled = False
        self.auto_throttle_ratio = 0.0
        self.collision_recoil = 0.0

    def tick_cooldowns(self, dt: float) -> None:
        for mount in self.mounts:
            if mount.cooldown > 0.0:
                mount.cooldown = max(0.0, mount.cooldown - dt)
        if self.countermeasure_cooldown > 0.0:
            self.countermeasure_cooldown = max(0.0, self.countermeasure_cooldown - dt)

    def assign_weapon(self, hardpoint_id: str, weapon_id: str) -> None:
        for mount in self.mounts:
            if mount.hardpoint.id == hardpoint_id:
                mount.weapon_id = weapon_id
                return
        raise KeyError(f"No hardpoint {hardpoint_id}")

    # Module helpers -----------------------------------------------------

    def equip_module(self, module: ItemData) -> bool:
        """Equip a module if slot capacity allows."""

        capacity = getattr(self.frame.slots, module.slot_type, None)
        if capacity is None:
            raise ValueError(f"Unknown slot type {module.slot_type}")
        installed = self.modules_by_slot[module.slot_type]
        if len(installed) >= capacity:
            return False
        installed.append(module)
        for key, value in module.stats.items():
            self._module_stat_cache[key] += float(value)
        return True

    def module_stat_total(self, key: str) -> float:
        return self._module_stat_cache.get(key, 0.0)

    def has_module_tag(self, tag: str) -> bool:
        tag_upper = tag.upper()
        for modules in self.modules_by_slot.values():
            for module in modules:
                if tag_upper in (t.upper() for t in module.tags):
                    return True
        return False

    def iter_modules(self) -> Iterable[ItemData]:
        for modules in self.modules_by_slot.values():
            yield from modules

    # Assist toggles ------------------------------------------------------

    def enable_auto_throttle(self, hold_current_speed: bool = True) -> None:
        """Lock throttle to the current forward speed ratio."""

        if hold_current_speed:
            forward = self.kinematics.forward()
            current_speed = max(0.0, self.kinematics.velocity.dot(forward))
            max_speed = max(1.0, self.stats.max_speed)
            self.auto_throttle_ratio = max(0.0, min(1.0, current_speed / max_speed))
        self.auto_throttle_enabled = True

    def disable_auto_throttle(self) -> None:
        self.auto_throttle_enabled = False
        self.auto_throttle_ratio = 0.0

    def toggle_auto_throttle(self) -> bool:
        if self.auto_throttle_enabled:
            self.disable_auto_throttle()
            return False
        self.enable_auto_throttle()
        return True

    def set_auto_level(self, enabled: bool) -> None:
        self.auto_level_enabled = enabled

    def toggle_auto_level(self) -> bool:
        self.auto_level_enabled = not self.auto_level_enabled
        return self.auto_level_enabled


__all__ = [
    "Ship",
    "ShipControlState",
    "ShipKinematics",
    "WeaponMount",
    "ShipResources",
]
