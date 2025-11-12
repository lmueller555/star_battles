from __future__ import annotations

import sys
from pathlib import Path

from pygame.math import Vector3

sys.path.append(str(Path(__file__).resolve().parents[1]))

from game.ships.data import ShipFrame
from game.ships.flight import THRUSTER_SPEED_MULTIPLIER, update_ship_flight
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats


def _make_test_ship(max_speed: float, boost_speed: float) -> Ship:
    stats = ShipStats(
        hull_hp=1000.0,
        hull_regen=5.0,
        armor=100.0,
        durability=200.0,
        avoidance=0.05,
        avoidance_rating=50.0,
        crit_defense=0.05,
        max_speed=max_speed,
        boost_speed=boost_speed,
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
    ship.control.roll_input = 0.0
    ship.control.brake = False
    ship.control.boost = False
    ship.kinematics.velocity = Vector3()
    return ship


def _advance(ship: Ship, dt: float, steps: int) -> None:
    for _ in range(steps):
        update_ship_flight(ship, dt)


def _forward_speed(ship: Ship) -> float:
    forward = ship.kinematics.basis.forward
    return ship.kinematics.velocity.dot(forward)


def test_thruster_speed_respects_lower_stat_limit() -> None:
    ship = _make_test_ship(max_speed=80.0, boost_speed=100.0)
    ship.control.throttle = 1.0
    _advance(ship, dt=0.1, steps=200)
    cruise_speed = _forward_speed(ship)

    ship.control.boost = True
    _advance(ship, dt=0.1, steps=400)
    boosted_speed = _forward_speed(ship)

    fallback_speed = ship.stats.max_speed * THRUSTER_SPEED_MULTIPLIER

    assert boosted_speed > cruise_speed
    assert boosted_speed <= ship.stats.boost_speed + 5.0
    assert boosted_speed < fallback_speed - 5.0


def test_thruster_speed_scales_with_higher_stat() -> None:
    ship = _make_test_ship(max_speed=80.0, boost_speed=170.0)
    ship.control.throttle = 1.0
    _advance(ship, dt=0.1, steps=200)

    ship.control.boost = True
    _advance(ship, dt=0.1, steps=700)
    boosted_speed = _forward_speed(ship)
    fallback_speed = ship.stats.max_speed * THRUSTER_SPEED_MULTIPLIER

    assert boosted_speed > fallback_speed + 5.0
    assert boosted_speed >= ship.stats.boost_speed * 0.8
