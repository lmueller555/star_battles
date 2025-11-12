"""Asteroid field generation and scanning state."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from pygame.math import Vector3

if TYPE_CHECKING:  # pragma: no cover - only used for typing
    from game.ships.ship import Ship

from game.render.state import RenderSpatialState


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
class AsteroidAccent:
    angle: float
    distance: float
    horizontal_scale: float
    vertical_scale: float
    highlight: bool


@dataclass
class AsteroidCrater:
    angle: float
    distance: float
    radius_scale: float


@dataclass
class AsteroidRenderProfile:
    point_angles: List[float]
    point_offsets: List[float]
    horizontal_scale: List[float]
    vertical_scale: List[float]
    accents: List[AsteroidAccent]
    craters: List[AsteroidCrater]


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
    render_state: RenderSpatialState = field(default_factory=RenderSpatialState, init=False, repr=False)
    _render_profile: AsteroidRenderProfile | None = field(default=None, init=False, repr=False)

    MIN_SIZE = 10.0
    MAX_SIZE = 100.0
    MIN_HEALTH = 250.0
    MAX_HEALTH = 5000.0
    SCAN_DURATION = 2.0
    SCAN_EFFECT_DURATION = 0.75

    def __post_init__(self) -> None:
        self._size = self._size_for_health(self.health)
        self.render_state.ensure_current(self.position)

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

    def render_profile(self) -> AsteroidRenderProfile:
        if self._render_profile is None:
            rng = random.Random(hash(self.id))
            point_count = rng.randint(8, 14)
            jaggedness = 0.45
            distortion = 0.75
            angles: List[float] = []
            offsets: List[float] = []
            horizontal_scale: List[float] = []
            vertical_scale: List[float] = []
            angle_step = (2.0 * math.pi) / point_count if point_count else 0.0
            for index in range(point_count):
                angle = index * angle_step
                angles.append(angle)
                offsets.append(1.0 - jaggedness + rng.random() * jaggedness * 2.0)
                horizontal_scale.append(distortion + rng.random() * (1.0 - distortion))
                vertical_scale.append(distortion + rng.random() * (1.0 - distortion))
            accents: List[AsteroidAccent] = []
            accent_count = rng.randint(3, 6)
            for _ in range(accent_count):
                accents.append(
                    AsteroidAccent(
                        angle=rng.uniform(0.0, 2.0 * math.pi),
                        distance=rng.uniform(0.1, 0.8),
                        horizontal_scale=rng.uniform(0.6, 1.0),
                        vertical_scale=rng.uniform(0.6, 1.0),
                        highlight=rng.random() > 0.5,
                    )
                )
            craters: List[AsteroidCrater] = []
            crater_count = rng.randint(2, 4)
            for _ in range(crater_count):
                craters.append(
                    AsteroidCrater(
                        angle=rng.uniform(0.0, 2.0 * math.pi),
                        distance=rng.uniform(0.15, 0.65),
                        radius_scale=rng.uniform(0.04, 0.12),
                    )
                )
            self._render_profile = AsteroidRenderProfile(
                point_angles=angles,
                point_offsets=offsets,
                horizontal_scale=horizontal_scale,
                vertical_scale=vertical_scale,
                accents=accents,
                craters=craters,
            )
        return self._render_profile

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


@dataclass
class AsteroidFieldState:
    system_id: Optional[str]
    field: List[Asteroid]


class AsteroidField:
    """Generates and manages asteroids per sector."""

    ASTEROID_COUNT = 225
    FIELD_RADIUS = 15000.0
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
        self._prune_destroyed()

    def current_field(self) -> List[Asteroid]:
        return self._current

    def suspend(self) -> AsteroidFieldState:
        """Capture the active asteroid field and clear it from the simulation."""

        state = AsteroidFieldState(system_id=self._current_system, field=list(self._current))
        self._current = []
        return state

    def resume(self, state: AsteroidFieldState) -> None:
        """Restore a previously captured asteroid field back into the simulation."""

        self._current_system = state.system_id
        if state.system_id:
            self._fields[state.system_id] = list(state.field)
            self._current = self._fields[state.system_id]
        else:
            self._current = []

    def clear_current(self) -> None:
        self._current = []

    def update(self, dt: float) -> None:
        for asteroid in self._current:
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
        if not self._current:
            return
        for asteroid in self._current:
            asteroid.halt_scan()
        position = ship.kinematics.position
        for asteroid in self._current:
            if asteroid.scanned or asteroid.is_destroyed():
                asteroid.update(dt)
                continue
            distance = asteroid.position.distance_to(position)
            if distance <= self.SCAN_RANGE:
                asteroid.scan(dt)

    def halt_scanning(self) -> None:
        for asteroid in self._current:
            asteroid.halt_scan()

    def prune_destroyed(self) -> None:
        self._prune_destroyed()

    def _prune_destroyed(self) -> None:
        if not self._current:
            return
        remaining = [asteroid for asteroid in self._current if not asteroid.is_destroyed()]
        if len(remaining) == len(self._current):
            return
        self._current[:] = remaining
        if self._current_system:
            self._fields[self._current_system] = self._current


__all__ = ["Asteroid", "AsteroidField", "AsteroidFieldState"]
