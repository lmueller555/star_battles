import logging
import random
from pathlib import Path

import pytest
from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.logger import DEFAULT_CHANNELS, GameLogger, LoggerConfig
from game.ships.data import ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats
from game.world.asteroids import Asteroid, AsteroidField, BROWN, RESOURCE_COLORS
from game.world.space import SpaceWorld


def _load_content() -> ContentManager:
    root = Path(__file__).resolve().parents[1]
    content = ContentManager(root / "game" / "assets")
    content.load()
    return content


def _quiet_logger() -> GameLogger:
    channels = {name: False for name in DEFAULT_CHANNELS}
    return GameLogger(LoggerConfig(level=logging.CRITICAL, channels=channels))


def test_asteroid_field_generation_bounds() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    asteroids = world.all_asteroids_in_current_system()
    assert len(asteroids) == AsteroidField.ASTEROID_COUNT
    for asteroid in asteroids:
        assert Asteroid.MIN_HEALTH <= asteroid.health <= Asteroid.MAX_HEALTH
        size = asteroid.size()
        assert Asteroid.MIN_SIZE <= size <= Asteroid.MAX_SIZE
        if asteroid.resource is None:
            assert asteroid.resource_amount == 0.0
        else:
            ratio = asteroid.resource_amount / asteroid.health
            assert AsteroidField.RESOURCE_RATIO_RANGE[0] <= ratio <= AsteroidField.RESOURCE_RATIO_RANGE[1]


def test_asteroid_size_constant_after_damage() -> None:
    asteroid = Asteroid(
        id="test",
        position=Vector3(),
        health=Asteroid.MAX_HEALTH * 0.6,
        resource=None,
        resource_amount=0.0,
    )
    original_size = asteroid.size()
    asteroid.take_damage(asteroid.health * 0.5)
    assert asteroid.size() == pytest.approx(original_size)


def test_asteroid_scanning_updates_color() -> None:
    field = AsteroidField(random.Random(42))
    field.enter_system("test")
    asteroid = field.current_field()[0]
    assert not asteroid.scanned
    assert asteroid.display_color == BROWN

    total = 0.0
    while not asteroid.scanned and total < 10.0:
        asteroid.scan(0.5)
        asteroid.update(0.0)
        total += 0.5
    assert asteroid.scanned

    asteroid.update(asteroid.SCAN_EFFECT_DURATION)
    assert asteroid.display_color == RESOURCE_COLORS[asteroid.resource_key]


def test_space_world_scanning_marks_asteroid() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    frame = content.ships.get("viper_mk_vii")
    ship = Ship(frame, team="player")
    world.add_ship(ship)

    asteroid = world.all_asteroids_in_current_system()[0]
    ship.kinematics.position = Vector3(asteroid.position.x, asteroid.position.y, asteroid.position.z)

    total = 0.0
    while not asteroid.scanned and total < 10.0:
        world.step_mining(ship, dt=0.5, scanning=True, stabilizing=False)
        world.update(0.0)
        total += 0.5

    assert asteroid.scanned


def test_weapons_can_destroy_asteroid() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    frame = content.ships.get("viper_mk_vii")
    ship = Ship(frame, team="player")
    ship.apply_default_loadout(content)
    world.add_ship(ship)

    asteroid = next(a for a in world.all_asteroids_in_current_system() if not a.is_destroyed())
    ship.kinematics.position = Vector3(asteroid.position.x, asteroid.position.y, asteroid.position.z - 250.0)
    ship.kinematics.rotation = Vector3(0.0, 0.0, 0.0)
    ship.power = 1000.0

    mount = next(m for m in ship.mounts if m.weapon_id)

    initial_health = asteroid.health
    result = world.fire_mount(ship, mount, asteroid)
    assert result is not None
    assert asteroid.health < initial_health

    while not asteroid.is_destroyed():
        mount.cooldown = 0.0
        ship.power = 1000.0
        world.fire_mount(ship, mount, asteroid)

    world.asteroids.prune_destroyed()
    assert asteroid.is_destroyed()
    assert asteroid not in world.asteroids_in_current_system()


def test_destroyed_asteroid_rewards_resources() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    frame = ShipFrame(
        id="test",
        name="Test",
        role="Test",
        size="Strike",
        stats=ShipStats.from_dict({}),
        slots=ShipSlotLayout.from_dict({}),
        hardpoints=[],
    )
    ship = Ship(frame, team="player")

    asteroid = Asteroid(
        id="resource",
        position=Vector3(),
        health=Asteroid.MIN_HEALTH,
        resource="tyllium",
        resource_amount=50.0,
    )
    initial_tylium = ship.resources.tylium
    resource_amount = asteroid.resource_amount

    world._apply_asteroid_damage(asteroid, asteroid.health, ship)

    assert ship.resources.tylium == pytest.approx(initial_tylium + resource_amount)
    assert asteroid.resource_amount == 0.0
    assert asteroid.resource is None

