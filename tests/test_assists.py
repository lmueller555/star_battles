"""Tests for flight assists and weapon magnetism."""
from __future__ import annotations

import sys
from pathlib import Path

from pygame.math import Vector3

sys.path.append(str(Path(__file__).resolve().parents[1]))

from game.combat.weapons import WeaponData, resolve_hitscan
from game.ships.data import ShipFrame
from game.ships.flight import update_ship_flight
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats


def _make_test_ship() -> Ship:
    stats = ShipStats(
        hull_hp=1000.0,
        hull_regen=5.0,
        armor=100.0,
        durability=200.0,
        avoidance=0.05,
        avoidance_rating=50.0,
        crit_defense=0.05,
        max_speed=80.0,
        boost_speed=140.0,
        acceleration=60.0,
        strafe_accel=40.0,
        strafe_cap=25.0,
        turn_rate=180.0,
        turn_accel=300.0,
        inertia_comp=0.8,
        boost_drain=15.0,
        power_cap=150.0,
        power_regen=40.0,
        firewall=120.0,
        emitter=120.0,
        dradis_range=3000.0,
        visual_range=800.0,
        ftl_range=10.0,
        ftl_charge=15.0,
        ftl_threat_charge=25.0,
        ftl_cost_per_ly=20.0,
    )
    slots = ShipSlotLayout(weapon_families={}, hull=0, engine=0, computer=0, utility=0)
    frame = ShipFrame(
        id="test_frame",
        name="Test Frame",
        role="Interceptor",
        size="Strike",
        stats=stats,
        slots=slots,
        hardpoints=[],
    )
    ship = Ship(frame)
    ship.control.look_delta = Vector3()
    ship.control.strafe = Vector3()
    return ship


class _DeterministicRng:
    def __init__(self, *values: float) -> None:
        self._values = list(values)

    def random(self) -> float:  # pragma: no cover - simple deterministic stub
        if not self._values:
            return 0.0
        return self._values.pop(0)


def test_auto_throttle_holds_target_speed() -> None:
    ship = _make_test_ship()
    ship.enable_auto_throttle(hold_current_speed=False)
    ship.auto_throttle_ratio = 0.6
    ship.control.throttle = 0.0
    ship.control.boost = False
    ship.control.brake = False
    ship.control.roll_input = 0.0
    ship.kinematics.velocity = Vector3()
    update_ship_flight(ship, 0.1)
    forward_speed = ship.kinematics.velocity.dot(ship.kinematics.forward())
    assert forward_speed > 0.0

    ship.control.throttle = 1.0
    update_ship_flight(ship, 0.1)
    assert ship.auto_throttle_ratio == 1.0

    ship.control.throttle = 0.0
    update_ship_flight(ship, 0.1)
    held_speed = ship.kinematics.velocity.dot(ship.kinematics.forward())
    assert held_speed > forward_speed


def test_auto_level_gently_reduces_roll() -> None:
    ship = _make_test_ship()
    ship.auto_level_enabled = True
    ship.control.throttle = 0.0
    ship.control.boost = False
    ship.control.brake = False
    ship.control.roll_input = 0.0
    ship.kinematics.rotation.z = 45.0
    ship.kinematics.angular_velocity.z = 0.0
    before = ((ship.kinematics.rotation.z + 180.0) % 360.0) - 180.0
    update_ship_flight(ship, 0.1)
    after = ((ship.kinematics.rotation.z + 180.0) % 360.0) - 180.0
    assert abs(after) < abs(before)


def test_hitscan_magnetism_softens_edge_cases() -> None:
    weapon = WeaponData(
        id="test",
        name="Test Cannon",
        slot_type="cannon",
        wclass="hitscan",
        base_damage=100.0,
        base_accuracy=0.9,
        crit_chance=0.1,
        crit_multiplier=1.5,
        rof=2.0,
        power_per_shot=10.0,
        optimal_range=600.0,
        max_range=1000.0,
        projectile_speed=0.0,
        ammo=0,
        reload=0.0,
        gimbal=5.0,
    )
    rng = _DeterministicRng(0.0, 1.0)
    result = resolve_hitscan(
        origin=Vector3(),
        direction=Vector3(0.0, 0.0, 1.0),
        weapon=weapon,
        target_position=Vector3(0.0, 0.0, 600.0),
        target_velocity=Vector3(),
        target_avoidance=0.0,
        target_crit_def=0.0,
        armor=0.0,
        rng=rng,
        distance=600.0,
        angle_error=5.0,
        gimbal_limit=5.0,
    )
    assert result.hit is True
