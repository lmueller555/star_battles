"""Deterministic procedural generation for sector content."""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple


Vector3 = Tuple[float, float, float]


def _hash_seed(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _distance(a: Vector3, b: Vector3) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _segment_distance(point: Vector3, start: Vector3, end: Vector3) -> float:
    segment = (end[0] - start[0], end[1] - start[1], end[2] - start[2])
    length_sq = segment[0] ** 2 + segment[1] ** 2 + segment[2] ** 2
    if length_sq <= 1e-9:
        return _distance(point, start)
    to_point = (point[0] - start[0], point[1] - start[1], point[2] - start[2])
    t = max(0.0, min(1.0, (to_point[0] * segment[0] + to_point[1] * segment[1] + to_point[2] * segment[2]) / length_sq))
    closest = (
        start[0] + segment[0] * t,
        start[1] + segment[1] * t,
        start[2] + segment[2] * t,
    )
    return _distance(point, closest)


def _random_point_on_ring(rng: "random.Random", min_radius: float, max_radius: float) -> Vector3:
    radius = rng.uniform(min_radius, max_radius)
    angle = rng.uniform(0.0, 2.0 * math.pi)
    return (radius * math.cos(angle), 0.0, radius * math.sin(angle))


def _random_point_in_sphere(rng: "random.Random", min_radius: float, max_radius: float) -> Vector3:
    radius = rng.uniform(min_radius, max_radius)
    u = rng.uniform(-1.0, 1.0)
    theta = rng.uniform(0.0, 2.0 * math.pi)
    sqrt_term = math.sqrt(max(0.0, 1.0 - u * u))
    x = radius * sqrt_term * math.cos(theta)
    y = radius * u
    z = radius * sqrt_term * math.sin(theta)
    return (x, y, z)


@dataclass(frozen=True)
class ThemeProfile:
    id: str
    name: str
    palette: Tuple[str, str, str]
    primary_elements: Tuple[str, ...]
    secondary_elements: Tuple[str, ...]
    lore: str


# Sector Theme Profiles
THEMES: Tuple[ThemeProfile, ...] = (
    ThemeProfile(
        id="ringed_planet_orbit",
        name="Ringed Planet Orbit",
        palette=("#7ED2FF", "#FFC58A", "#5C7A9A"),
        primary_elements=("wireframe_planet", "ring_system"),
        secondary_elements=("wireframe_moon", "nebula_volume", "distant_beacon"),
        lore=(
            "A stately gas giant hangs beyond reachable space, its rings etched with the remnants "
            "of ancient cargo lanes. Pilots whisper that the rings still hum with dormant "
            "navigation beacons that once guided pilgrim fleets through this corridor."
        ),
    ),
    ThemeProfile(
        id="nebula_drift",
        name="Nebula Drift",
        palette=("#A56BFF", "#FF7AD9", "#4A2C6B"),
        primary_elements=("nebula_volume", "wireframe_planet"),
        secondary_elements=("wireframe_moon", "ring_system", "derelict_megastructure"),
        lore=(
            "Thick, luminous clouds coil around the sector, tinting every hull with magenta "
            "afterglow. The nebula is a graveyard of lost signals, and scavengers claim the "
            "static hides a still-broadcasting distress call from the first survey mission."
        ),
    ),
    ThemeProfile(
        id="derelict_fleet_graveyard",
        name="Derelict Fleet Graveyard",
        palette=("#9AA3B2", "#E2B68A", "#566070"),
        primary_elements=("derelict_megastructure", "wireframe_planet"),
        secondary_elements=("wireframe_moon", "distant_beacon", "nebula_volume"),
        lore=(
            "Colossal hulks float in silent formation, the remains of a defensive line that "
            "never received the retreat order. The only light is a beacon looped in emergency "
            "mode, inviting anyone brave enough to sift through the armored debris."
        ),
    ),
    ThemeProfile(
        id="pulsar_shroud",
        name="Pulsar Shroud",
        palette=("#69E6FF", "#FFF07C", "#1A3552"),
        primary_elements=("nebula_volume", "pulsar_spire"),
        secondary_elements=("wireframe_planet", "wireframe_moon", "ring_system", "distant_beacon"),
        lore=(
            "A distant pulsar washes the sector in rhythmic flashes, strobing every ridge of the "
            "nebula. Patrol logs note the time-keeping value of the pulses, while smugglers use "
            "the flicker to mask their jumps."
        ),
    ),
    ThemeProfile(
        id="crystalline_expanse",
        name="Crystalline Expanse",
        palette=("#A7F6D9", "#F3FFF6", "#4EA4A8"),
        primary_elements=("wireframe_planet", "crystal_cluster"),
        secondary_elements=("wireframe_moon", "ring_system", "nebula_volume"),
        lore=(
            "Light refracts through icy particulate streams, turning the void into a prism of "
            "greens and whites. Prospectors tell stories of a frozen vault world beyond the "
            "horizon, sealed when the first freeze wave swept the system."
        ),
    ),
    ThemeProfile(
        id="aurora_frontier",
        name="Aurora Frontier",
        palette=("#6FFFCB", "#7AA7FF", "#14243A"),
        primary_elements=("wireframe_planet", "aurora_ribbon"),
        secondary_elements=("wireframe_moon", "distant_beacon", "ring_system", "nebula_volume"),
        lore=(
            "Energetic winds comb the sector into long auroral curtains, marking the edge of a "
            "volatile magnetosphere. Frontier crews tell new arrivals to follow the green bands "
            "if they want to find the only stable slipstream out."
        ),
    ),
    ThemeProfile(
        id="clockwork_relay",
        name="Clockwork Relay",
        palette=("#F2C879", "#C9D1E8", "#3B4A66"),
        primary_elements=("derelict_megastructure", "ring_system"),
        secondary_elements=("wireframe_planet", "distant_beacon", "wireframe_moon"),
        lore=(
            "A skeletal relay lattice surrounds the sector like a broken astrolabe, its rings "
            "aligned with a long-dead trade calendar. The rumor is that restoring a single relay "
            "node could light an ancient jump route across the frontier."
        ),
    ),
    ThemeProfile(
        id="ember_wastes",
        name="Ember Wastes",
        palette=("#FF9A6A", "#FCD38A", "#5B3238"),
        primary_elements=("wireframe_planet", "derelict_megastructure"),
        secondary_elements=("nebula_volume", "distant_beacon", "wireframe_moon"),
        lore=(
            "The background glow is a bruise of burnt orange from old reactor scars and drifting "
            "plasma embers. The sector is notorious for running hot, and every station log keeps "
            "a memorial to the convoy that vanished in the flare season."
        ),
    ),
)


@dataclass
class SectorMetadata:
    sector_id: str
    seed: int
    difficulty: int
    theme_id: str
    palette: Tuple[str, str, str]
    sub_seeds: Dict[str, int]


@dataclass
class ManifestObject:
    type: str
    position: Vector3
    rotation: Vector3
    scale: Vector3
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NpcGroup:
    faction: str
    behavior: str
    position: Vector3
    patrol_route: List[Vector3]


@dataclass
class AsteroidFieldSpec:
    field_type: str
    center: Vector3
    radius: float
    density: float
    anchors: int


@dataclass
class HazardSpec:
    hazard_type: str
    position: Vector3
    radius: float
    severity: float


@dataclass
class ResourceNodeSpec:
    position: Vector3
    resource_type: str
    amount: float
    source: str


@dataclass
class SectorManifest:
    metadata: SectorMetadata
    spawn_point: Vector3
    safe_zone_radius: float
    friendly_outposts: List[ManifestObject]
    enemy_outposts: List[ManifestObject]
    npc_groups: List[NpcGroup]
    asteroid_fields: List[AsteroidFieldSpec]
    hazards: List[HazardSpec]
    resource_nodes: List[ResourceNodeSpec]
    background_elements: List[ManifestObject]
    validation: Dict[str, Any]
    generation_time_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": {
                "sector_id": self.metadata.sector_id,
                "seed": self.metadata.seed,
                "difficulty": self.metadata.difficulty,
                "theme_id": self.metadata.theme_id,
                "palette": self.metadata.palette,
                "sub_seeds": self.metadata.sub_seeds,
            },
            "spawn_point": self.spawn_point,
            "safe_zone_radius": self.safe_zone_radius,
            "friendly_outposts": [_object_to_dict(obj) for obj in self.friendly_outposts],
            "enemy_outposts": [_object_to_dict(obj) for obj in self.enemy_outposts],
            "npc_groups": [
                {
                    "faction": group.faction,
                    "behavior": group.behavior,
                    "position": group.position,
                    "patrol_route": group.patrol_route,
                }
                for group in self.npc_groups
            ],
            "asteroid_fields": [
                {
                    "field_type": field.field_type,
                    "center": field.center,
                    "radius": field.radius,
                    "density": field.density,
                    "anchors": field.anchors,
                }
                for field in self.asteroid_fields
            ],
            "hazards": [
                {
                    "hazard_type": hazard.hazard_type,
                    "position": hazard.position,
                    "radius": hazard.radius,
                    "severity": hazard.severity,
                }
                for hazard in self.hazards
            ],
            "resource_nodes": [
                {
                    "position": node.position,
                    "resource_type": node.resource_type,
                    "amount": node.amount,
                    "source": node.source,
                }
                for node in self.resource_nodes
            ],
            "background_elements": [_object_to_dict(obj) for obj in self.background_elements],
            "validation": self.validation,
            "generation_time_ms": self.generation_time_ms,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def _object_to_dict(obj: ManifestObject) -> Dict[str, Any]:
    return {
        "type": obj.type,
        "position": obj.position,
        "rotation": obj.rotation,
        "scale": obj.scale,
        "details": obj.details,
    }


class ProceduralSectorGenerator:
    """Generate deterministic sector layouts per the authoritative spec."""

    SECTOR_RADIUS = 10000.0
    SPAWN_SAFE_RADIUS = 1000.0
    FRIENDLY_DISTANCE = (800.0, 2500.0)
    ENEMY_DISTANCE = (3000.0, 8000.0)
    SPAWN_HAZARD_DISTANCE = 1000.0
    FRIENDLY_ASTEROID_MIN = 500.0
    ENEMY_RESOURCE_MIN = 800.0
    CORRIDOR_CLEARANCE = 800.0
    BACKGROUND_MIN_RADIUS = 12000.0
    BACKGROUND_MAX_RADIUS = 20000.0

    ASTEROID_DENSITY_RANGE = (0.2, 0.8)
    ASTEROID_RADIUS_RANGE = (1200.0, 2600.0)
    HAZARD_RADIUS_RANGE = (600.0, 1400.0)
    RESOURCE_AMOUNT_RANGE = (120.0, 520.0)

    NPC_BASE_COUNT = 6
    NPC_PER_DIFFICULTY = 3

    MAX_ATTEMPTS = 8

    def generate(
        self,
        *,
        sector_id: str,
        seed: int | str,
        difficulty: int = 1,
        theme_hint: Optional[str] = None,
    ) -> SectorManifest:
        start_time = time.perf_counter()
        base_seed = _hash_seed(sector_id, seed, difficulty, theme_hint or "")
        sub_seeds = {
            name: _hash_seed(base_seed, name)
            for name in (
                "outposts",
                "npcs",
                "asteroids",
                "hazards",
                "resources",
                "background",
                "validation",
            )
        }
        theme_rng = self._rng(sub_seeds["background"], 0)
        theme = self._select_theme(theme_rng, theme_hint)
        metadata = SectorMetadata(
            sector_id=sector_id,
            seed=base_seed,
            difficulty=difficulty,
            theme_id=theme.id,
            palette=theme.palette,
            sub_seeds=sub_seeds,
        )
        spawn_point = (0.0, 0.0, 0.0)
        validation: Dict[str, Any] = {"attempts": {}}
        layout: Optional[Tuple[List[ManifestObject], List[ManifestObject], List[NpcGroup], List[AsteroidFieldSpec], List[HazardSpec], List[ResourceNodeSpec], List[ManifestObject]]] = None
        for attempt in range(self.MAX_ATTEMPTS):
            outposts_rng = self._rng(sub_seeds["outposts"], attempt)
            npcs_rng = self._rng(sub_seeds["npcs"], attempt)
            asteroid_rng = self._rng(sub_seeds["asteroids"], attempt)
            hazard_rng = self._rng(sub_seeds["hazards"], attempt)
            resource_rng = self._rng(sub_seeds["resources"], attempt)
            background_rng = self._rng(sub_seeds["background"], attempt)

            friendly_outpost = self._place_friendly_outpost(outposts_rng, spawn_point)
            enemy_outpost = self._place_enemy_outpost(outposts_rng, spawn_point, friendly_outpost.position)
            asteroid_fields = self._place_asteroid_fields(
                asteroid_rng,
                spawn_point,
                friendly_outpost.position,
                enemy_outpost.position,
            )
            hazards = self._place_hazards(
                hazard_rng,
                spawn_point,
                friendly_outpost.position,
                enemy_outpost.position,
                difficulty,
            )
            resource_nodes = self._place_resource_nodes(
                resource_rng,
                asteroid_fields,
                hazards,
                enemy_outpost.position,
            )
            npc_groups = self._place_npcs(
                npcs_rng,
                spawn_point,
                friendly_outpost.position,
                enemy_outpost.position,
                hazards,
                difficulty,
            )
            background_elements = self._place_background(background_rng, theme)

            validation_results = self._validate_layout(
                spawn_point=spawn_point,
                friendly_outpost=friendly_outpost.position,
                enemy_outpost=enemy_outpost.position,
                asteroid_fields=asteroid_fields,
                hazards=hazards,
                resource_nodes=resource_nodes,
                npc_groups=npc_groups,
            )
            validation["attempts"][attempt] = validation_results
            if validation_results["valid"]:
                layout = (
                    [friendly_outpost],
                    [enemy_outpost],
                    npc_groups,
                    asteroid_fields,
                    hazards,
                    resource_nodes,
                    background_elements,
                )
                break

        if layout is None:
            layout = (
                [friendly_outpost],
                [enemy_outpost],
                npc_groups,
                asteroid_fields,
                hazards,
                resource_nodes,
                background_elements,
            )
            validation["fallback"] = "max_attempts_reached"

        generation_time_ms = (time.perf_counter() - start_time) * 1000.0
        return SectorManifest(
            metadata=metadata,
            spawn_point=spawn_point,
            safe_zone_radius=self.SPAWN_SAFE_RADIUS,
            friendly_outposts=layout[0],
            enemy_outposts=layout[1],
            npc_groups=layout[2],
            asteroid_fields=layout[3],
            hazards=layout[4],
            resource_nodes=layout[5],
            background_elements=layout[6],
            validation=validation,
            generation_time_ms=generation_time_ms,
        )

    def _rng(self, seed: int, attempt: int) -> "random.Random":
        import random

        return random.Random(_hash_seed(seed, attempt))

    def _select_theme(self, rng: "random.Random", theme_hint: Optional[str]) -> ThemeProfile:
        if theme_hint:
            for theme in THEMES:
                if theme.id == theme_hint:
                    return theme
        return rng.choice(THEMES)

    def _place_friendly_outpost(self, rng: "random.Random", spawn_point: Vector3) -> ManifestObject:
        position = _random_point_on_ring(rng, *self.FRIENDLY_DISTANCE)
        return ManifestObject(
            type="friendly_outpost",
            position=position,
            rotation=(0.0, rng.uniform(0.0, 360.0), 0.0),
            scale=(1.0, 1.0, 1.0),
            details={"safe_radius": 650.0, "line_of_sight": True},
        )

    def _place_enemy_outpost(
        self,
        rng: "random.Random",
        spawn_point: Vector3,
        friendly_position: Vector3,
    ) -> ManifestObject:
        for _ in range(self.MAX_ATTEMPTS * 2):
            position = _random_point_on_ring(rng, *self.ENEMY_DISTANCE)
            if _distance(position, friendly_position) < self.ENEMY_DISTANCE[0]:
                continue
            if _distance(position, spawn_point) < self.SPAWN_SAFE_RADIUS + 500.0:
                continue
            break
        return ManifestObject(
            type="enemy_outpost",
            position=position,
            rotation=(0.0, rng.uniform(0.0, 360.0), 0.0),
            scale=(1.0, 1.0, 1.0),
            details={"defense_level": rng.randint(1, 3)},
        )

    def _place_asteroid_fields(
        self,
        rng: "random.Random",
        spawn_point: Vector3,
        friendly_position: Vector3,
        enemy_position: Vector3,
    ) -> List[AsteroidFieldSpec]:
        field_type = rng.choice(["cluster", "belt", "scatter"])
        radius = rng.uniform(*self.ASTEROID_RADIUS_RANGE)
        density = rng.uniform(*self.ASTEROID_DENSITY_RANGE)
        anchors = rng.randint(2, 5)
        center = None
        for _ in range(self.MAX_ATTEMPTS * 3):
            candidate = _random_point_on_ring(rng, 2500.0, self.SECTOR_RADIUS - 1500.0)
            if _distance(candidate, friendly_position) < self.FRIENDLY_ASTEROID_MIN:
                continue
            if _segment_distance(candidate, spawn_point, friendly_position) < self.CORRIDOR_CLEARANCE:
                continue
            if _distance(candidate, enemy_position) < self.CORRIDOR_CLEARANCE:
                continue
            center = candidate
            break
        if center is None:
            center = _random_point_on_ring(rng, 3000.0, self.SECTOR_RADIUS - 2000.0)
        return [AsteroidFieldSpec(field_type=field_type, center=center, radius=radius, density=density, anchors=anchors)]

    def _place_hazards(
        self,
        rng: "random.Random",
        spawn_point: Vector3,
        friendly_position: Vector3,
        enemy_position: Vector3,
        difficulty: int,
    ) -> List[HazardSpec]:
        hazard_types = ["radiation", "gravity_anomaly", "minefield"]
        extra = 1 if rng.random() < min(0.6, 0.2 + 0.15 * max(1, difficulty)) else 0
        count = max(1, min(3, 1 + rng.randint(0, 1) + extra))
        hazards: List[HazardSpec] = []
        for _ in range(count):
            for _attempt in range(self.MAX_ATTEMPTS * 2):
                position = _random_point_on_ring(rng, 5000.0, self.SECTOR_RADIUS - 500.0)
                if _distance(position, spawn_point) < self.SPAWN_HAZARD_DISTANCE:
                    continue
                if _segment_distance(position, spawn_point, friendly_position) < self.CORRIDOR_CLEARANCE:
                    continue
                if _distance(position, enemy_position) < 900.0:
                    continue
                hazards.append(
                    HazardSpec(
                        hazard_type=rng.choice(hazard_types),
                        position=position,
                        radius=rng.uniform(*self.HAZARD_RADIUS_RANGE),
                        severity=rng.uniform(0.3, 0.9),
                    )
                )
                break
        return hazards

    def _place_resource_nodes(
        self,
        rng: "random.Random",
        asteroid_fields: Sequence[AsteroidFieldSpec],
        hazards: Sequence[HazardSpec],
        enemy_position: Vector3,
    ) -> List[ResourceNodeSpec]:
        resources = ["water", "titanium", "tyllium"]
        nodes: List[ResourceNodeSpec] = []
        for _ in range(1):
            for _attempt in range(self.MAX_ATTEMPTS * 2):
                source = "asteroid_field"
                if asteroid_fields:
                    field = rng.choice(asteroid_fields)
                    angle = rng.uniform(0.0, 2.0 * math.pi)
                    radius = rng.uniform(0.0, field.radius * 0.8)
                    position = (
                        field.center[0] + math.cos(angle) * radius,
                        field.center[1],
                        field.center[2] + math.sin(angle) * radius,
                    )
                elif hazards:
                    hazard = rng.choice(hazards)
                    position = _random_point_on_ring(rng, hazard.radius * 0.8, hazard.radius * 1.2)
                    source = "hazard"
                else:
                    position = _random_point_on_ring(rng, 2000.0, self.SECTOR_RADIUS - 2000.0)
                    source = "open_space"
                if _distance(position, enemy_position) < self.ENEMY_RESOURCE_MIN:
                    continue
                nodes.append(
                    ResourceNodeSpec(
                        position=position,
                        resource_type=rng.choice(resources),
                        amount=rng.uniform(*self.RESOURCE_AMOUNT_RANGE),
                        source=source,
                    )
                )
                break
        return nodes

    def _place_npcs(
        self,
        rng: "random.Random",
        spawn_point: Vector3,
        friendly_position: Vector3,
        enemy_position: Vector3,
        hazards: Sequence[HazardSpec],
        difficulty: int,
    ) -> List[NpcGroup]:
        npc_groups: List[NpcGroup] = []
        npc_groups.append(
            self._npc_group_near(rng, "friendly", "escort", friendly_position, 250.0, 600.0)
        )
        npc_groups.append(
            self._npc_group_near(rng, "hostile", "patrol", enemy_position, 250.0, 650.0)
        )
        total = self.NPC_BASE_COUNT + self.NPC_PER_DIFFICULTY * max(0, difficulty)
        for _ in range(total):
            faction = rng.choice(["friendly", "hostile", "neutral"])
            behavior = rng.choice(["roam", "escort", "patrol"])
            for _attempt in range(self.MAX_ATTEMPTS * 2):
                position = _random_point_in_sphere(rng, 1500.0, self.SECTOR_RADIUS - 1200.0)
                if _distance(position, spawn_point) < self.SPAWN_SAFE_RADIUS:
                    continue
                if faction == "friendly" and _distance(position, enemy_position) < 1200.0:
                    continue
                if any(_distance(position, hazard.position) < hazard.radius * 0.8 for hazard in hazards):
                    continue
                npc_groups.append(
                    NpcGroup(
                        faction=faction,
                        behavior=behavior,
                        position=position,
                        patrol_route=self._patrol_route(rng, position),
                    )
                )
                break
        return npc_groups

    def _npc_group_near(
        self,
        rng: "random.Random",
        faction: str,
        behavior: str,
        anchor: Vector3,
        min_radius: float,
        max_radius: float,
    ) -> NpcGroup:
        angle = rng.uniform(0.0, 2.0 * math.pi)
        radius = rng.uniform(min_radius, max_radius)
        position = (anchor[0] + math.cos(angle) * radius, anchor[1], anchor[2] + math.sin(angle) * radius)
        return NpcGroup(
            faction=faction,
            behavior=behavior,
            position=position,
            patrol_route=self._patrol_route(rng, position),
        )

    def _patrol_route(self, rng: "random.Random", origin: Vector3) -> List[Vector3]:
        points = []
        for _ in range(3):
            offset = _random_point_in_sphere(rng, 200.0, 450.0)
            points.append((origin[0] + offset[0], origin[1] + offset[1], origin[2] + offset[2]))
        return points

    def _place_background(self, rng: "random.Random", theme: ThemeProfile) -> List[ManifestObject]:
        background: List[ManifestObject] = []
        major_count = rng.randint(1, 3)
        minor_count = rng.randint(2, 6)
        for _ in range(major_count):
            element_type = rng.choice(theme.primary_elements)
            background.append(self._background_element(rng, element_type, theme.palette, scale_range=(9000.0, 15000.0)))
        for _ in range(minor_count):
            element_type = rng.choice(theme.secondary_elements)
            background.append(self._background_element(rng, element_type, theme.palette, scale_range=(2500.0, 7000.0)))
        return background

    def _background_element(
        self,
        rng: "random.Random",
        element_type: str,
        palette: Tuple[str, str, str],
        scale_range: Tuple[float, float],
    ) -> ManifestObject:
        position = _random_point_in_sphere(rng, self.BACKGROUND_MIN_RADIUS, self.BACKGROUND_MAX_RADIUS)
        scale_value = rng.uniform(*scale_range)
        return ManifestObject(
            type=element_type,
            position=position,
            rotation=(rng.uniform(0.0, 360.0), rng.uniform(0.0, 360.0), rng.uniform(0.0, 360.0)),
            scale=(scale_value, scale_value, scale_value),
            details={"palette": palette, "parallax": True},
        )

    def _validate_layout(
        self,
        *,
        spawn_point: Vector3,
        friendly_outpost: Vector3,
        enemy_outpost: Vector3,
        asteroid_fields: Sequence[AsteroidFieldSpec],
        hazards: Sequence[HazardSpec],
        resource_nodes: Sequence[ResourceNodeSpec],
        npc_groups: Sequence[NpcGroup],
    ) -> Dict[str, Any]:
        violations: List[str] = []
        if _distance(spawn_point, enemy_outpost) < self.SPAWN_SAFE_RADIUS:
            violations.append("enemy_outpost_in_spawn_zone")
        if not (self.FRIENDLY_DISTANCE[0] <= _distance(spawn_point, friendly_outpost) <= self.FRIENDLY_DISTANCE[1]):
            violations.append("friendly_outpost_distance")
        if _distance(friendly_outpost, enemy_outpost) < self.ENEMY_DISTANCE[0]:
            violations.append("outpost_spacing")
        for hazard in hazards:
            if _distance(spawn_point, hazard.position) < self.SPAWN_HAZARD_DISTANCE:
                violations.append("hazard_near_spawn")
            if _segment_distance(hazard.position, spawn_point, friendly_outpost) < self.CORRIDOR_CLEARANCE:
                violations.append("hazard_blocks_corridor")
        for field in asteroid_fields:
            if _segment_distance(field.center, spawn_point, friendly_outpost) < self.CORRIDOR_CLEARANCE:
                violations.append("asteroid_blocks_corridor")
            if _distance(field.center, friendly_outpost) < self.FRIENDLY_ASTEROID_MIN:
                violations.append("asteroid_near_friendly")
        for node in resource_nodes:
            if _distance(node.position, enemy_outpost) < self.ENEMY_RESOURCE_MIN:
                violations.append("resource_near_enemy")
        friendly_npcs = [npc for npc in npc_groups if npc.faction == "friendly"]
        hostile_npcs = [npc for npc in npc_groups if npc.faction == "hostile"]
        if not friendly_npcs:
            violations.append("missing_friendly_npc")
        if not hostile_npcs:
            violations.append("missing_hostile_npc")
        return {
            "valid": not violations,
            "violations": violations,
        }


__all__ = [
    "ProceduralSectorGenerator",
    "SectorManifest",
    "SectorMetadata",
    "ManifestObject",
    "AsteroidFieldSpec",
    "HazardSpec",
    "ResourceNodeSpec",
    "NpcGroup",
]
