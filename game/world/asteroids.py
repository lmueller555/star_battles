"""Asteroid field generation and scanning state."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from pygame.math import Vector3

if TYPE_CHECKING:  # pragma: no cover - only used for typing
    from game.ships.ship import Ship


BROWN = (150, 110, 80)
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

    MIN_SIZE = 10.0
    MAX_SIZE = 100.0
    MIN_HEALTH = 250.0
    MAX_HEALTH = 5000.0
    SCAN_DURATION = 2.0
    SCAN_EFFECT_DURATION = 0.75

    def size(self) -> float:
        ratio = 0.0
        if self.MAX_HEALTH > self.MIN_HEALTH:
            ratio = (self.health - self.MIN_HEALTH) / (self.MAX_HEALTH - self.MIN_HEALTH)
        ratio = max(0.0, min(1.0, ratio))
        return self.MIN_SIZE + (self.MAX_SIZE - self.MIN_SIZE) * ratio

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


class AsteroidField:
    """Generates and manages asteroids per sector."""

    ASTEROID_COUNT = 150
    FIELD_RADIUS = 4000.0
    HEALTH_RANGE = (Asteroid.MIN_HEALTH, Asteroid.MAX_HEALTH)
    RESOURCE_OPTIONS: Tuple[Optional[str], ...] = (None, "water", "titanium", "tyllium")
    RESOURCE_RATIO_RANGE = (0.25, 0.35)
    SCAN_RANGE = 1600.0

    def __init__(self, rng: Optional[random.Random] = None) -> None:
        self._rng = rng or random.Random(1337)
        self._fields: Dict[str, List[Asteroid]] = {}
        self._current_system: Optional[str] = None
        self._current: List[Asteroid] = []

    def enter_system(self, system_id: Optional[str]) -> None:
        self._current_system = system_id
        if not system_id:
            self._current = []
            return
        if system_id not in self._fields:
            self._fields[system_id] = self._generate_field(system_id)
        self._current = self._fields[system_id]
        for asteroid in self._current:
            asteroid.halt_scan()

    def current_field(self) -> List[Asteroid]:
        return self._current

    def update(self, dt: float) -> None:
        for asteroid in self._current:
            asteroid.update(dt)

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
        if not self._current:
            return
        for asteroid in self._current:
            asteroid.halt_scan()
        position = ship.kinematics.position
        for asteroid in self._current:
            if asteroid.scanned:
                asteroid.update(dt)
                continue
            distance = asteroid.position.distance_to(position)
            if distance <= self.SCAN_RANGE:
                asteroid.scan(dt)

    def halt_scanning(self) -> None:
        for asteroid in self._current:
            asteroid.halt_scan()


__all__ = ["Asteroid", "AsteroidField"]
