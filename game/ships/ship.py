"""Ship entity implementation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pygame.math import Vector3

from .data import Hardpoint, ShipFrame
from .stats import ShipStats


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

    def __init__(self, frame: ShipFrame, team: str = "player", modules: Optional[list[str]] = None) -> None:
        self.frame = frame
        self.team = team
        self.modules = set(modules or [])
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

    def tick_cooldowns(self, dt: float) -> None:
        for mount in self.mounts:
            if mount.cooldown > 0.0:
                mount.cooldown = max(0.0, mount.cooldown - dt)

    def assign_weapon(self, hardpoint_id: str, weapon_id: str) -> None:
        for mount in self.mounts:
            if mount.hardpoint.id == hardpoint_id:
                mount.weapon_id = weapon_id
                return
        raise KeyError(f"No hardpoint {hardpoint_id}")


__all__ = [
    "Ship",
    "ShipControlState",
    "ShipKinematics",
    "WeaponMount",
]
