"""Ship entity implementation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, List, Optional, TYPE_CHECKING

from pygame.math import Vector3

from game.assets.content import ItemData
from .data import Hardpoint, ShipFrame
from .stats import ShipStats


if TYPE_CHECKING:
    from game.assets.content import ContentManager


@dataclass
class ShipResources:
    tylium: float = 0.0
    titanium: float = 0.0
    water: float = 0.0
    cubits: float = 0.0

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

    def _basis_vectors(self) -> tuple[Vector3, Vector3, Vector3]:
        from math import cos, sin, radians

        pitch, yaw, roll = map(radians, (self.rotation.x, self.rotation.y, self.rotation.z))
        cp = cos(pitch)
        sp = sin(pitch)
        cy = cos(yaw)
        sy = sin(yaw)
        cr = cos(roll)
        sr = sin(roll)

        forward = Vector3(sy * cp, -sp, cy * cp)
        right = Vector3(cy * cr + sy * sp * sr, cp * sr, -sy * cr + cy * sp * sr)
        up = Vector3(-cy * sr + sy * sp * cr, cp * cr, sy * sr + cy * sp * cr)

        # Ensure numerical stability when the ship is aligned with an axis.
        if forward.length_squared() == 0:
            forward = Vector3(0.0, 0.0, 1.0)
        if right.length_squared() == 0:
            right = Vector3(1.0, 0.0, 0.0)
        if up.length_squared() == 0:
            up = Vector3(0.0, 1.0, 0.0)

        return forward.normalize(), right.normalize(), up.normalize()

    def forward(self) -> Vector3:
        forward, _, _ = self._basis_vectors()
        return forward

    def right(self) -> Vector3:
        _, right, _ = self._basis_vectors()
        return right

    def up(self) -> Vector3:
        _, _, up = self._basis_vectors()
        return up


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
        self.base_stats: ShipStats = replace(frame.stats)
        self.stats: ShipStats = replace(frame.stats)
        self.kinematics = ShipKinematics(
            position=Vector3(0.0, 0.0, 0.0),
            velocity=Vector3(0.0, 0.0, 0.0),
            rotation=Vector3(0.0, 0.0, 0.0),
            angular_velocity=Vector3(0.0, 0.0, 0.0),
        )
        self.control = ShipControlState()
        self.resources = ShipResources(
            tylium=1_000_000.0, titanium=180.0, water=40.0, cubits=1_000_000.0
        )
        self.tylium_capacity = self.resources.tylium
        self.power = self.stats.power_cap
        self.boost_meter = self.tylium_capacity
        self.hull = self.stats.hull_hp
        self.durability = self.stats.durability
        self.hull_regen_cooldown = 0.0
        self.mounts: List[WeaponMount] = [WeaponMount(hp) for hp in self.frame.hardpoints]
        self.target_id: Optional[int] = None
        self.lock_progress: float = 0.0
        self.lock_decay_delay: float = 0.5
        self.lock_timer: float = 0.0
        self.modules_by_slot: Dict[str, list[ItemData]] = defaultdict(list)
        self._module_stat_cache: Dict[str, float] = defaultdict(float)
        self.hold_items: Dict[str, int] = {}
        self.hold_capacity: int = 30
        self.countermeasure_cooldown: float = 0.0
        self.auto_throttle_enabled: bool = False
        self.auto_throttle_ratio: float = 0.0
        self.auto_level_enabled: bool = True
        self.collision_recoil: float = 0.0
        self.flank_speed_ratio: float = 0.6
        self.thrusters_active: bool = False
        if modules:
            for module in modules:
                self.equip_module(module)

    # Internal helpers --------------------------------------------------

    def _recompute_stats(self) -> None:
        """Rebuild runtime stats from the frame baseline and module bonuses."""

        previous = self.stats
        stats = replace(self.base_stats)

        special_keys = {"avoidance", "avoidance_rating"}
        for key, bonus in self._module_stat_cache.items():
            if key in special_keys:
                continue
            if hasattr(stats, key):
                setattr(stats, key, getattr(stats, key) + bonus)

        # Avoidance is expressed both as a raw rating and a normalised 0-1 value.
        rating_bonus = self._module_stat_cache.get("avoidance_rating", 0.0)
        direct_avoidance_bonus = self._module_stat_cache.get("avoidance", 0.0)
        new_rating = stats.avoidance_rating + rating_bonus
        stats.avoidance_rating = new_rating
        normalised = new_rating / 1000.0 if new_rating > 1.0 else new_rating
        stats.avoidance = normalised + direct_avoidance_bonus

        self.stats = stats

        def preserve_ratio(current: float, previous_max: float, new_max: float) -> float:
            if new_max <= 0.0:
                return 0.0
            if previous_max <= 0.0:
                ratio = 1.0 if current > 0.0 else 0.0
            else:
                ratio = current / previous_max
            ratio = max(0.0, min(1.0, ratio))
            return new_max * ratio

        self.hull = preserve_ratio(self.hull, previous.hull_hp, stats.hull_hp)
        self.durability = preserve_ratio(self.durability, previous.durability, stats.durability)
        self.power = preserve_ratio(self.power, previous.power_cap, stats.power_cap)

    def is_alive(self) -> bool:
        return self.hull > 0

    def reset(self) -> None:
        self.power = self.stats.power_cap
        self.boost_meter = self.tylium_capacity
        self.hull = self.stats.hull_hp
        self.durability = self.stats.durability
        self.kinematics.velocity = Vector3()
        self.kinematics.angular_velocity = Vector3()
        self.control = ShipControlState()
        self.resources.tylium = self.tylium_capacity
        for mount in self.mounts:
            mount.cooldown = 0.0
            mount.lock_progress = 0.0
        self.countermeasure_cooldown = 0.0
        self.auto_throttle_enabled = False
        self.auto_throttle_ratio = 0.0
        self.collision_recoil = 0.0
        self.flank_speed_ratio = 0.6
        self.thrusters_active = False

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
        self._recompute_stats()
        return True

    def unequip_module(self, slot_type: str, index: int) -> ItemData | None:
        """Remove a module from the specified slot index."""

        modules = self.modules_by_slot.get(slot_type)
        if not modules or index < 0 or index >= len(modules):
            return None
        module = modules.pop(index)
        for key, value in module.stats.items():
            self._module_stat_cache[key] -= float(value)
        self._recompute_stats()
        return module

    def hold_item_count(self) -> int:
        return sum(self.hold_items.values())

    def can_store_in_hold(self, quantity: int = 1) -> bool:
        return self.hold_item_count() + max(0, quantity) <= self.hold_capacity

    def add_hold_item(self, item_id: str, quantity: int = 1) -> bool:
        if quantity <= 0:
            return True
        if not self.can_store_in_hold(quantity):
            return False
        self.hold_items[item_id] = self.hold_items.get(item_id, 0) + quantity
        return True

    def remove_hold_item(self, item_id: str, quantity: int = 1) -> bool:
        if quantity <= 0:
            return True
        current = self.hold_items.get(item_id, 0)
        if current < quantity:
            return False
        remaining = current - quantity
        if remaining > 0:
            self.hold_items[item_id] = remaining
        else:
            self.hold_items.pop(item_id, None)
        return True

    def apply_default_loadout(self, content: "ContentManager") -> None:
        """Equip the frame's default modules and weapons when available."""

        for slot_type, item_ids in self.frame.default_modules.items():
            for item_id in item_ids:
                try:
                    module = content.items.get(item_id)
                except KeyError:
                    continue
                self.equip_module(module)
        for hardpoint_id, weapon_id in self.frame.default_weapons.items():
            try:
                content.weapons.get(weapon_id)
            except KeyError:
                continue
            try:
                self.assign_weapon(hardpoint_id, weapon_id)
            except KeyError:
                continue

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
            max_speed = max(1.0, self.stats.max_speed * max(0.0, min(1.0, self.flank_speed_ratio)))
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

    def set_flank_speed_ratio(self, ratio: float) -> None:
        """Update the flank speed slider ratio and clamp the value."""

        clamped = max(0.0, min(1.0, ratio))
        if self.flank_speed_ratio != clamped:
            self.flank_speed_ratio = clamped
            if self.auto_throttle_enabled:
                self.enable_auto_throttle(hold_current_speed=True)

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
