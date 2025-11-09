"""Unit tests for deterministic formulas."""
from __future__ import annotations

from math import isclose
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from game.math.ballistics import compute_lead
from game.combat.formulas import apply_armor, calculate_crit, calculate_hit_chance
from game.ftl.utils import compute_ftl_charge, compute_ftl_cost
from game.mining.formulas import compute_mining_yield
from game.world.sector import SectorMap


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
