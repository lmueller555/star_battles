import logging
import random
from pathlib import Path

from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.logger import DEFAULT_CHANNELS, GameLogger, LoggerConfig
from game.world.asteroids import Asteroid, AsteroidField, BROWN, RESOURCE_COLORS
from game.world.space import SpaceWorld
from game.ships.ship import Ship


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

    asteroids = world.asteroids_in_current_system()
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

    asteroid = world.asteroids_in_current_system()[0]
    ship.kinematics.position = Vector3(asteroid.position.x, asteroid.position.y, asteroid.position.z)

    total = 0.0
    while not asteroid.scanned and total < 10.0:
        world.step_mining(ship, dt=0.5, scanning=True, stabilizing=False)
        world.update(0.0)
        total += 0.5

    assert asteroid.scanned
