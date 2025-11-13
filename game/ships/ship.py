"""Ship entity implementation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
import random
from typing import Dict, Iterable, List, Optional, TYPE_CHECKING

from pygame.math import Vector3

from game.assets.content import ItemData
from .data import Hardpoint, ShipFrame
from .stats import ShipStats
from game.render.state import RenderSpatialState
from game.engine.frame_clock import current_frame
from game.engine.telemetry import record_basis_hit, record_basis_miss


_PERCENT_STAT_TARGETS = {
    "max_speed_percent": "max_speed",
    "boost_speed_percent": "boost_speed",
    "acceleration_percent": "acceleration",
    "turn_rate_percent": "turn_rate",
    "turn_accel_percent": "turn_accel",
    "strafe_speed_percent": "strafe_speed",
    "boost_cost_percent": "boost_cost",
    "avoidance_percent": "avoidance_rating",
}


if TYPE_CHECKING:
    from game.assets.content import ContentManager


@dataclass
class ShipResources:
    tylium: float = 0.0
    titanium: float = 0.0
    water: float = 0.0
    cubits: float = 0.0
    merits: float = 0.0
    tuning_kits: float = 0.0

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
class ShipBasis:
    """Cached local orientation basis for a ship."""

    forward: Vector3 = field(default_factory=Vector3)
    right: Vector3 = field(default_factory=Vector3)
    up: Vector3 = field(default_factory=Vector3)
    revision: int = -1


@dataclass
class ShipKinematics:
    position: Vector3
    velocity: Vector3
    rotation: Vector3
    angular_velocity: Vector3
    _basis_forward: Vector3 = field(default_factory=Vector3, init=False, repr=False)
    _basis_right: Vector3 = field(default_factory=Vector3, init=False, repr=False)
    _basis_up: Vector3 = field(default_factory=Vector3, init=False, repr=False)
    _basis_rotation: Vector3 = field(default_factory=Vector3, init=False, repr=False)
    _basis_revision: int = field(default=-1, init=False, repr=False)
    _basis_view: ShipBasis = field(default_factory=ShipBasis, init=False, repr=False)

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

    @property
    def basis(self) -> ShipBasis:
        frame = current_frame()
        rotation_changed = (self.rotation - self._basis_rotation).length_squared() > 1e-6
        if self._basis_revision != frame or rotation_changed:
            forward, right, up = self._basis_vectors()
            self._basis_forward = forward
            self._basis_right = right
            self._basis_up = up
            self._basis_rotation = Vector3(self.rotation)
            self._basis_revision = frame
            record_basis_miss(frame, id(self))
        else:
            record_basis_hit(frame)
        self._basis_view.forward = self._basis_forward
        self._basis_view.right = self._basis_right
        self._basis_view.up = self._basis_up
        self._basis_view.revision = self._basis_revision
        return self._basis_view

    def forward(self) -> Vector3:
        return self.basis.forward

    def right(self) -> Vector3:
        return self.basis.right

    def up(self) -> Vector3:
        return self.basis.up


@dataclass
class WeaponMount:
    hardpoint: Hardpoint
    weapon_id: Optional[str] = None
    cooldown: float = 0.0
    lock_progress: float = 0.0
    level: int = 1
    effect_timer: float = 0.0
    effect_duration: float = 0.0
    effect_range: float = 0.0
    effect_gimbal: float = 0.0
    effect_type: str = ""
    effect_seed: int = field(default_factory=lambda: random.randrange(0, 1 << 30))


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
            tylium=1_000_000.0,
            titanium=180.0,
            water=40.0,
            cubits=1_000_000.0,
            merits=2_000.0,
            tuning_kits=50.0,
        )
        self.tylium_capacity = self.resources.tylium
        self.power = self.stats.power_points
        self.boost_meter = self.tylium_capacity
        self.hull = self.stats.hull_points
        self.durability = self.stats.durability
        self.hull_regen_cooldown = 0.0
        self.mounts: List[WeaponMount] = [WeaponMount(hp) for hp in self.frame.hardpoints]
        self.target_id: Optional[int] = None
        self.lock_progress: float = 0.0
        self.lock_decay_delay: float = 0.5
        self.lock_timer: float = 0.0
        self.modules_by_slot: Dict[str, list[ItemData]] = defaultdict(list)
        self.module_levels: Dict[str, List[int]] = defaultdict(list)
        self._module_stat_cache: Dict[str, float] = defaultdict(float)
        self.hold_items: Dict[str, int] = {}
        self.hold_item_levels: Dict[str, List[int]] = defaultdict(list)
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
        self.render_state = RenderSpatialState()
        self.render_state.ensure_current(self.kinematics.position, self.kinematics.rotation)

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

        for percent_key, target in _PERCENT_STAT_TARGETS.items():
            percent = self._module_stat_cache.get(percent_key, 0.0)
            if abs(percent) <= 1e-6:
                continue
            base_value = float(getattr(self.base_stats, target, 0.0))
            current_value = float(getattr(stats, target, base_value))
            setattr(stats, target, current_value + base_value * (percent / 100.0))

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

        self.hull = preserve_ratio(self.hull, previous.hull_points, stats.hull_points)
        self.durability = preserve_ratio(self.durability, previous.durability, stats.durability)
        self.power = preserve_ratio(self.power, previous.power_points, stats.power_points)

    def is_alive(self) -> bool:
        return self.hull > 0

    def reset(self) -> None:
        self.power = self.stats.power_points
        self.boost_meter = self.tylium_capacity
        self.hull = self.stats.hull_points
        self.durability = self.stats.durability
        self.kinematics.velocity = Vector3()
        self.kinematics.angular_velocity = Vector3()
        self.control = ShipControlState()
        self.resources.tylium = self.tylium_capacity
        for mount in self.mounts:
            mount.cooldown = 0.0
            mount.lock_progress = 0.0
            mount.effect_timer = 0.0
            mount.effect_duration = 0.0
            mount.effect_range = 0.0
            mount.effect_gimbal = 0.0
            mount.effect_type = ""
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
            if mount.effect_timer > 0.0:
                mount.effect_timer = max(0.0, mount.effect_timer - dt)
                if mount.effect_timer == 0.0:
                    mount.effect_duration = 0.0
                    mount.effect_range = 0.0
                    mount.effect_gimbal = 0.0
                    mount.effect_type = ""
        if self.countermeasure_cooldown > 0.0:
            self.countermeasure_cooldown = max(0.0, self.countermeasure_cooldown - dt)

    def assign_weapon(self, hardpoint_id: str, weapon_id: str) -> None:
        for mount in self.mounts:
            if mount.hardpoint.id == hardpoint_id:
                mount.weapon_id = weapon_id
                mount.level = 1
                return
        raise KeyError(f"No hardpoint {hardpoint_id}")

    def hardpoint_direction(self, hardpoint: Hardpoint | None) -> Vector3:
        basis = self.kinematics.basis
        if hardpoint is None:
            return Vector3(basis.forward)
        local = getattr(hardpoint, "orientation", None)
        if not isinstance(local, Vector3) or local.length_squared() <= 0.0:
            return Vector3(basis.forward)
        direction = basis.right * local.x + basis.up * local.y + basis.forward * local.z
        if direction.length_squared() <= 0.0:
            return Vector3(basis.forward)
        return direction.normalize()

    # Module helpers -----------------------------------------------------

    def equip_module(
        self, module: ItemData, level: int = 1, index: Optional[int] = None
    ) -> bool:
        """Equip a module if slot capacity allows."""

        capacity = getattr(self.frame.slots, module.slot_type, None)
        if capacity is None:
            raise ValueError(f"Unknown slot type {module.slot_type}")
        installed = self.modules_by_slot[module.slot_type]
        if len(installed) >= capacity:
            return False
        levels = self.module_levels[module.slot_type]
        level_value = max(1, int(level))
        if index is None:
            installed.append(module)
            levels.append(level_value)
        else:
            target = max(0, min(int(index), len(installed)))
            installed.insert(target, module)
            levels.insert(target, level_value)
        for key, value in module.stats.items():
            self._module_stat_cache[key] += float(value)
        self._recompute_stats()
        return True

    def unequip_module(self, slot_type: str, index: int) -> tuple[ItemData, int] | None:
        """Remove a module from the specified slot index."""

        modules = self.modules_by_slot.get(slot_type)
        if not modules or index < 0 or index >= len(modules):
            return None
        module = modules.pop(index)
        levels = self.module_levels.get(slot_type, [])
        level = 1
        if 0 <= index < len(levels):
            level = levels.pop(index)
        for key, value in module.stats.items():
            self._module_stat_cache[key] -= float(value)
        self._recompute_stats()
        return module, level

    def hold_item_count(self) -> int:
        return sum(self.hold_items.values())

    def can_store_in_hold(self, quantity: int = 1) -> bool:
        return self.hold_item_count() + max(0, quantity) <= self.hold_capacity

    def add_hold_item(self, item_id: str, quantity: int = 1, level: int = 1) -> bool:
        if quantity <= 0:
            return True
        if not self.can_store_in_hold(quantity):
            return False
        self.hold_items[item_id] = self.hold_items.get(item_id, 0) + quantity
        levels = self.hold_item_levels.setdefault(item_id, [])
        level_value = max(1, int(level))
        for _ in range(quantity):
            levels.append(level_value)
        return True

    def remove_hold_item(
        self, item_id: str, quantity: int = 1, *, index: Optional[int] = None
    ) -> List[int]:
        if quantity <= 0:
            return []
        current = self.hold_items.get(item_id, 0)
        if current < quantity:
            return []
        levels = self._ensure_hold_levels(item_id)
        removed: List[int] = []
        for i in range(quantity):
            if not levels:
                removed.append(1)
                continue
            if i == 0 and index is not None and 0 <= index < len(levels):
                removed.append(levels.pop(index))
            else:
                removed.append(levels.pop(0))
        remaining = current - quantity
        if remaining > 0:
            self.hold_items[item_id] = remaining
            # Trim any excess level entries beyond remaining quantity
            while len(levels) > remaining:
                levels.pop()
        else:
            self.hold_items.pop(item_id, None)
            self.hold_item_levels.pop(item_id, None)
        return removed

    def hold_item_level(self, item_id: str, index: int = 0) -> int:
        levels = self._ensure_hold_levels(item_id)
        if not levels:
            return 1
        if 0 <= index < len(levels):
            return levels[index]
        return levels[0]

    def set_hold_item_level(self, item_id: str, index: int, level: int) -> None:
        levels = self._ensure_hold_levels(item_id)
        target = max(0, int(index))
        level_value = max(1, int(level))
        while len(levels) <= target:
            levels.append(1)
            self.hold_items[item_id] = self.hold_items.get(item_id, 0) + 1
        levels[target] = level_value

    def module_level(self, slot_type: str, index: int) -> int:
        levels = self.module_levels.get(slot_type, [])
        if 0 <= index < len(levels):
            return levels[index]
        return 1

    def set_module_level(self, slot_type: str, index: int, level: int) -> None:
        levels = self.module_levels.setdefault(slot_type, [])
        target = max(0, int(index))
        level_value = max(1, int(level))
        while len(levels) <= target:
            levels.append(1)
        levels[target] = level_value

    def weapon_level(self, mount_index: int) -> int:
        if 0 <= mount_index < len(self.mounts):
            return max(1, int(self.mounts[mount_index].level))
        return 1

    def set_weapon_level(self, mount_index: int, level: int) -> None:
        if 0 <= mount_index < len(self.mounts):
            self.mounts[mount_index].level = max(1, int(level))

    def item_level(self, item_id: str) -> int:
        levels = self.hold_item_levels.get(item_id)
        if levels:
            return levels[0]
        for slot_type, modules in self.modules_by_slot.items():
            for index, module in enumerate(modules):
                if module.id == item_id:
                    return self.module_level(slot_type, index)
        for mount in self.mounts:
            if mount.weapon_id == item_id:
                return max(1, int(mount.level))
        return 1

    def set_item_level(self, item_id: str, level: int) -> None:
        level_value = max(1, int(level))
        levels = self.hold_item_levels.get(item_id)
        if levels:
            levels[0] = level_value
            return
        for slot_type, modules in self.modules_by_slot.items():
            for index, module in enumerate(modules):
                if module.id == item_id:
                    self.set_module_level(slot_type, index, level_value)
                    return
        for mount in self.mounts:
            if mount.weapon_id == item_id:
                mount.level = level_value
                return
        self.hold_item_levels[item_id] = [level_value]

    def _ensure_hold_levels(self, item_id: str) -> List[int]:
        quantity = self.hold_items.get(item_id, 0)
        levels = self.hold_item_levels.setdefault(item_id, [])
        if quantity <= 0:
            return []
        if len(levels) < quantity:
            levels.extend([1] * (quantity - len(levels)))
        elif len(levels) > quantity:
            del levels[quantity:]
        return levels

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

    def copy_loadout_from(self, source: "Ship") -> None:
        """Mirror the modules and weapons installed on another ship."""

        if source is self:
            return

        # Reset any existing equipment before copying.
        self.modules_by_slot.clear()
        self.module_levels.clear()
        self._module_stat_cache.clear()
        self._recompute_stats()
        for mount in self.mounts:
            mount.weapon_id = None
            mount.level = 1

        # Copy installed modules, preserving their upgrade levels.
        for slot_type, modules in source.modules_by_slot.items():
            levels = source.module_levels.get(slot_type, [])
            for index, module in enumerate(modules):
                level = levels[index] if index < len(levels) else 1
                self.equip_module(module, level=level)

        # Mirror weapon assignments by hardpoint identifier.
        source_mounts = {mount.hardpoint.id: mount for mount in source.mounts}
        for mount in self.mounts:
            source_mount = source_mounts.get(mount.hardpoint.id)
            if not source_mount or not source_mount.weapon_id:
                continue
            try:
                self.assign_weapon(mount.hardpoint.id, source_mount.weapon_id)
            except KeyError:
                continue
            mount.level = source_mount.level

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
            forward = self.kinematics.basis.forward
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
    "ShipBasis",
]
