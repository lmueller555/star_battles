"""Unit tests for deterministic formulas."""
from __future__ import annotations

from math import cos, isclose, radians, sin
from pathlib import Path
import sys
import random

sys.path.append(str(Path(__file__).resolve().parents[1]))

from pygame.math import Vector3

from game.math.ballistics import compute_lead
from game.combat.formulas import apply_armor, calculate_crit, calculate_hit_chance
from game.combat.weapons import resolve_hitscan
from game.combat.targeting import update_lock
from game.assets.content import ContentManager
from game.sensors.dradis import DradisSystem
from game.ships.ship import Ship
from game.ftl.utils import compute_ftl_charge, compute_ftl_cost
from game.mining.formulas import compute_mining_yield
from game.world.sector import SectorMap


def load_content() -> ContentManager:
    root = Path(__file__).resolve().parents[1]
    content = ContentManager(root / "game" / "assets")
    content.load()
    return content


def test_hit_chance_clamped() -> None:
    chance = calculate_hit_chance(0.8, 0.0, 0.2, accuracy_bonus=0.5)
    assert 0.0 <= chance <= 1.0
    assert isclose(chance, 1.0)


def test_crit_calculation() -> None:
    crit = calculate_crit(0.2, 0.1, 0.05)
    assert isclose(crit, 0.25)


def test_armor_floor() -> None:
    damage = apply_armor(100.0, 95.0)
    assert isclose(damage, 15.0)


class Vec3:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other: "Vec3") -> "Vec3":
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * scalar, self.y * scalar, self.z * scalar)

    __rmul__ = __mul__

    def dot(self, other: "Vec3") -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z


def test_lead_solution() -> None:
    origin = Vec3(0, 0, 0)
    target_pos = Vec3(1000, 0, 0)
    target_vel = Vec3(10, 0, 0)
    lead = compute_lead(origin, target_pos, target_vel, 200.0)
    assert lead.x > target_pos.x


def test_ftl_cost_and_charge() -> None:
    assert isclose(compute_ftl_cost(5.0, 20.0), 100.0)
    assert isclose(compute_ftl_charge(15.0, 25.0, False), 15.0)
    assert isclose(compute_ftl_charge(15.0, 25.0, True), 25.0)


def test_mining_yield() -> None:
    yield_rate = compute_mining_yield(10.0, 1.5, 0.2, 0.8)
    assert isclose(yield_rate, 14.4)


def test_hitscan_range_and_gimbal_modifiers() -> None:
    content = load_content()
    weapon = content.weapons.get("light_cannon_mk1")
    origin = Vector3(0.0, 0.0, 0.0)
    direction = Vector3(0.0, 0.0, 1.0)
    rng = random.Random(42)

    # Far outside maximum range should clamp hit chance to zero.
    far_target = Vector3(0.0, 0.0, weapon.max_range + 100.0)
    far_result = resolve_hitscan(
        origin,
        direction,
        weapon,
        far_target,
        Vector3(),
        0.0,
        0.0,
        0.0,
        rng,
        distance=far_target.length(),
        gimbal_limit=weapon.gimbal,
    )
    assert far_result.final_hit_chance == 0.0

    # Near the centre of the cone retains baseline accuracy.
    close_target = Vector3(0.0, 0.0, weapon.optimal_range)
    close_result = resolve_hitscan(
        origin,
        direction,
        weapon,
        close_target,
        Vector3(),
        0.0,
        0.0,
        0.0,
        rng,
        distance=close_target.length(),
        gimbal_limit=weapon.gimbal,
    )
    angle = weapon.gimbal * 0.9
    offset = Vector3(
        sin(radians(angle)) * weapon.optimal_range,
        0.0,
        cos(radians(angle)) * weapon.optimal_range,
    )
    edge_result = resolve_hitscan(
        origin,
        direction,
        weapon,
        offset,
        Vector3(),
        0.0,
        0.0,
        0.0,
        rng,
        distance=offset.length(),
        gimbal_limit=weapon.gimbal,
    )
    assert 0.0 < edge_result.final_hit_chance < close_result.final_hit_chance


def test_sector_map_reachability() -> None:
    sector = SectorMap()
    root = Path(__file__).resolve().parents[1]
    sector.load(root / "game" / "assets" / "data" / "sector_map.json")
    default = sector.default_system()
    assert default is not None
    distance = sector.distance(default.id, "helios_beta")
    assert distance > 0
    reachable = {system.id for system in sector.reachable(default.id, distance + 0.1)}
    assert "helios_beta" in reachable


def test_ship_modules_apply_tags_and_stats() -> None:
    content = load_content()
    ship = Ship(content.ships.get("interceptor_mk1"))
    pd = content.items.get("point_defense_mk1")
    eccm = content.items.get("eccm_mk1")
    assert ship.equip_module(pd)
    assert ship.equip_module(eccm)
    assert ship.has_module_tag("pd")
    assert ship.module_stat_total("pd_range") == pd.stats["pd_range"]
    assert ship.module_stat_total("sensor_strength") >= eccm.stats["sensor_strength"]


def test_dradis_detection_impacted_by_jammer() -> None:
    content = load_content()
    owner = Ship(content.ships.get("interceptor_mk1"))
    target_clean = Ship(content.ships.get("assault_dummy"))
    target_clean.kinematics.position.z = 1500.0
    dradis = DradisSystem(owner)
    dt = 0.1
    time_clean = 0.0
    while True:
        dradis.update([owner, target_clean], dt)
        time_clean += dt
        contact = dradis.contacts.get(id(target_clean))
        if contact and contact.detected:
            break
        assert time_clean < 10.0

    target_jammed = Ship(content.ships.get("assault_dummy"))
    target_jammed.kinematics.position.z = 1500.0
    target_jammed.equip_module(content.items.get("jammer_mk1"))
    dradis = DradisSystem(owner)
    time_jammed = 0.0
    while True:
        dradis.update([owner, target_jammed], dt)
        time_jammed += dt
        contact = dradis.contacts.get(id(target_jammed))
        if contact and contact.detected:
            break
        assert time_jammed < 10.0
    assert time_jammed > time_clean


def test_eccm_recovers_lock_speed() -> None:
    content = load_content()
    attacker = Ship(content.ships.get("interceptor_mk1"))
    target = Ship(content.ships.get("assault_dummy"))
    target.kinematics.position.z = 800.0
    dt = 0.1

    def acquire(attacker_ship: Ship, target_ship: Ship) -> float:
        attacker_ship.lock_progress = 0.0
        elapsed = 0.0
        while attacker_ship.lock_progress < 1.0:
            update_lock(attacker_ship, target_ship, dt)
            elapsed += dt
            assert elapsed < 20.0
        return elapsed

    baseline = acquire(attacker, target)

    target_jammed = Ship(content.ships.get("assault_dummy"))
    target_jammed.kinematics.position.z = 800.0
    target_jammed.equip_module(content.items.get("jammer_mk1"))
    jammed_time = acquire(attacker, target_jammed)
    assert jammed_time > baseline

    attacker_eccm = Ship(content.ships.get("interceptor_mk1"), modules=[content.items.get("eccm_mk1")])
    attacker_eccm.kinematics.position = attacker.kinematics.position
    eccm_time = acquire(attacker_eccm, target_jammed)
    assert eccm_time < jammed_time
