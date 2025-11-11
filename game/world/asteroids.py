"""Asteroid field generation and scanning state."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from pygame.math import Vector3

if TYPE_CHECKING:  # pragma: no cover - only used for typing
    from game.ships.ship import Ship


BROWN = (130, 132, 138)
SCAN_GLOW = (255, 240, 200)
RESOURCE_COLORS: Dict[str, Tuple[int, int, int]] = {
    "none": (210, 60, 60),  # Red
    "water": (90, 150, 255),  # Blue
    "titanium": (180, 120, 255),  # Purple
    "tyllium": (255, 210, 90),  # Gold
}


def _lerp_color(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(av + (bv - av) * t)) for av, bv in zip(a, b))


INVENTORY_RESOURCE_OVERRIDES: Dict[str, str] = {"tyllium": "tylium"}


@dataclass
class Asteroid:
    """Single asteroid instance within a sector."""

    id: str
    position: Vector3
    health: float
    resource: Optional[str]
    resource_amount: float
    scan_progress: float = 0.0
    scanned: bool = False
    scanning: bool = False
    _scan_effect_timer: float = field(default=0.0, repr=False)
    _size: float = field(init=False, repr=False)

    MIN_SIZE = 10.0
    MAX_SIZE = 100.0
    MIN_HEALTH = 250.0
    MAX_HEALTH = 5000.0
    SCAN_DURATION = 2.0
    SCAN_EFFECT_DURATION = 0.75

    def __post_init__(self) -> None:
        self._size = self._size_for_health(self.health)

    @classmethod
    def _size_for_health(cls, health: float) -> float:
        ratio = 0.0
        if cls.MAX_HEALTH > cls.MIN_HEALTH:
            ratio = (health - cls.MIN_HEALTH) / (cls.MAX_HEALTH - cls.MIN_HEALTH)
        ratio = max(0.0, min(1.0, ratio))
        return cls.MIN_SIZE + (cls.MAX_SIZE - cls.MIN_SIZE) * ratio

    def size(self) -> float:
        return self._size

    @property
    def radius(self) -> float:
        return self.size() * 0.5

    @property
    def resource_key(self) -> str:
        return "none" if not self.resource else self.resource

    @property
    def resource_color(self) -> Tuple[int, int, int]:
        return RESOURCE_COLORS[self.resource_key]

    @property
    def display_color(self) -> Tuple[int, int, int]:
        if not self.scanned:
            if self.scanning:
                return _lerp_color(BROWN, SCAN_GLOW, min(1.0, self.scan_progress))
            return BROWN
        if self._scan_effect_timer > 0.0:
            blend = 1.0 - min(1.0, self._scan_effect_timer / self.SCAN_EFFECT_DURATION)
            return _lerp_color(SCAN_GLOW, self.resource_color, blend)
        return self.resource_color

    @property
    def inventory_resource_key(self) -> Optional[str]:
        if not self.resource:
            return None
        return INVENTORY_RESOURCE_OVERRIDES.get(self.resource, self.resource)

    def begin_scan(self) -> None:
        self.scanning = True

    def halt_scan(self) -> None:
        self.scanning = False

    def scan(self, dt: float) -> None:
        if self.scanned:
            self.scanning = False
            return
        if not self.scanning:
            self.begin_scan()
        if dt <= 0.0:
            return
        self.scan_progress = min(1.0, self.scan_progress + dt / self.SCAN_DURATION)
        if self.scan_progress >= 1.0:
            self.scanned = True
            self.scanning = False
            self._scan_effect_timer = self.SCAN_EFFECT_DURATION

    def update(self, dt: float) -> None:
        if self._scan_effect_timer > 0.0:
            self._scan_effect_timer = max(0.0, self._scan_effect_timer - dt)

    def take_damage(self, amount: float) -> float:
        """Apply damage to the asteroid and return the effective amount."""

        if amount <= 0.0 or self.is_destroyed():
            return 0.0
        applied = min(self.health, amount)
        self.health = max(0.0, self.health - applied)
        if self.is_destroyed():
            self.halt_scan()
        return applied

    def is_destroyed(self) -> bool:
        return self.health <= 0.0


class AsteroidField:
    """Generates and manages asteroids per sector."""

    ASTEROID_COUNT = 225
    FIELD_RADIUS = 20000.0
    HEALTH_RANGE = (Asteroid.MIN_HEALTH, Asteroid.MAX_HEALTH)
    RESOURCE_OPTIONS: Tuple[Optional[str], ...] = (None, "water", "titanium", "tyllium")
    RESOURCE_RATIO_RANGE = (0.25, 0.35)
    SCAN_RANGE = 1600.0
    ACTIVE_RADIUS = 4000.0
    ACTIVE_REFRESH_DISTANCE = 500.0

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random(1337)
        self._fields: Dict[str, List[Asteroid]] = {}
        self._current_system: Optional[str] = None
        self._current_all: List[Asteroid] = []
        self._active: List[Asteroid] = []
        self._last_focus: Optional[Vector3] = None

    def enter_system(self, system_id: Optional[str]) -> None:
        self._current_system = system_id
        self._active = []
        self._last_focus = None
        if not system_id:
            self._current_all = []
            return
        if system_id not in self._fields:
            self._fields[system_id] = self._generate_field(system_id)
        self._current_all = self._fields[system_id]
        for asteroid in self._current_all:
            asteroid.halt_scan()
        self._prune_destroyed()
        self._ensure_active_initialized()

    def current_field(self) -> List[Asteroid]:
        self._ensure_active_initialized()
        return self._active

    def all_in_current_field(self) -> List[Asteroid]:
        return self._current_all

    def update(self, dt: float, focus: Optional[Vector3] = None) -> None:
        if focus is not None:
            self._update_active_set(focus)
        else:
            self._ensure_active_initialized()
        for asteroid in self._active:
            asteroid.update(dt)
        self._prune_destroyed()

    def _generate_field(self, system_id: str) -> List[Asteroid]:
        asteroids: List[Asteroid] = []
        for index in range(self.ASTEROID_COUNT):
            health = self._rng.uniform(*self.HEALTH_RANGE)
            resource = self._rng.choice(self.RESOURCE_OPTIONS)
            if resource:
                ratio = self._rng.uniform(*self.RESOURCE_RATIO_RANGE)
                resource_amount = ratio * health
            else:
                resource_amount = 0.0
            position = self._random_position()
            asteroid = Asteroid(
                id=f"{system_id}-asteroid-{index}",
                position=position,
                health=health,
                resource=resource,
                resource_amount=resource_amount,
            )
            asteroids.append(asteroid)
        return asteroids

    def _random_position(self) -> Vector3:
        radius = self._rng.uniform(0.0, self.FIELD_RADIUS)
        u = self._rng.uniform(-1.0, 1.0)
        theta = self._rng.uniform(0.0, 2.0 * math.pi)
        sqrt_term = math.sqrt(max(0.0, 1.0 - u * u))
        x = radius * sqrt_term * math.cos(theta)
        y = radius * sqrt_term * math.sin(theta)
        z = radius * u
        return Vector3(x, y, z)

    def scan_step(self, ship: "Ship", dt: float) -> None:
        if not self._current_all:
            return
        position = ship.kinematics.position
        self._update_active_set(position)
        for asteroid in self._active:
            asteroid.halt_scan()
        for asteroid in self._active:
            if asteroid.scanned or asteroid.is_destroyed():
                asteroid.update(dt)
                continue
            distance = asteroid.position.distance_to(position)
            if distance <= self.SCAN_RANGE:
                asteroid.scan(dt)

    def halt_scanning(self) -> None:
        for asteroid in self._active:
            asteroid.halt_scan()

    def prune_destroyed(self) -> None:
        self._prune_destroyed()

    def _prune_destroyed(self) -> None:
        if not self._current_all:
            return
        remaining = [asteroid for asteroid in self._current_all if not asteroid.is_destroyed()]
        if len(remaining) == len(self._current_all):
            return
        self._current_all[:] = remaining
        if self._current_system:
            self._fields[self._current_system] = self._current_all
        if self._active:
            self._active = [asteroid for asteroid in self._active if not asteroid.is_destroyed()]

    def _ensure_active_initialized(self) -> None:
        if self._active or not self._current_all:
            return
        if self._last_focus is None:
            self._last_focus = Vector3()
        self._update_active_set(self._last_focus, force=True)

    def _update_active_set(self, focus: Optional[Vector3], *, force: bool = False) -> None:
        if not self._current_all or focus is None:
            return
        if self._last_focus is not None and not force:
            delta = focus - self._last_focus
            if delta.length_squared() < self.ACTIVE_REFRESH_DISTANCE ** 2:
                return
        previous_active = self._active
        self._last_focus = Vector3(focus)
        radius_sq = self.ACTIVE_RADIUS ** 2
        active: List[Asteroid] = []
        for asteroid in self._current_all:
            if asteroid.is_destroyed():
                continue
            offset = asteroid.position - focus
            if offset.length_squared() <= radius_sq:
                active.append(asteroid)
        new_ids = {asteroid.id for asteroid in active}
        removed_ids = {asteroid.id for asteroid in previous_active if asteroid.id not in new_ids}
        if removed_ids:
            for asteroid in previous_active:
                if asteroid.id in removed_ids:
                    asteroid.halt_scan()
        self._active = active


__all__ = ["Asteroid", "AsteroidField"]
