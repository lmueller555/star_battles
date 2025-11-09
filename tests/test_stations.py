import json

from pygame.math import Vector3

from game.combat.weapons import WeaponDatabase
from game.engine.logger import GameLogger, LoggerConfig
from game.world.sector import SectorMap
from game.world.space import SpaceWorld
from game.world.station import StationDatabase


def make_logger() -> GameLogger:
    return GameLogger(LoggerConfig(level=0, channels={}))


def test_station_database_nearest(tmp_path):
    data = [
        {"id": "a", "system": "alpha", "position": [0, 0, 0], "dockingRadius": 900},
        {"id": "b", "system": "alpha", "position": [200, 0, 0], "dockingRadius": 900},
        {"id": "c", "system": "beta", "position": [0, 0, 0], "dockingRadius": 900},
    ]
    path = tmp_path / "stations.json"
    path.write_text(json.dumps(data))
    db = StationDatabase()
    db.load(path)
    station, distance = db.nearest_in_system("alpha", (10.0, 0.0, 0.0))
    assert station is not None
    assert station.id == "a"
    assert distance == 10.0


def test_space_world_nearest_station(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0, 0], "threat": False},
        {"id": "beta", "position": [1, 1], "threat": False},
    ]))
    stations_path = tmp_path / "stations.json"
    stations_path.write_text(json.dumps([
        {"id": "dock", "system": "alpha", "position": [0, 0, 500], "dockingRadius": 950},
    ]))

    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    stations.load(stations_path)

    weapons = WeaponDatabase()
    logger = make_logger()
    world = SpaceWorld(weapons=weapons, sector=sector, stations=stations, logger=logger)

    # Player ship positioned within the docking radius
    dummy_ship = type("DummyShip", (), {"kinematics": type("Kin", (), {"position": Vector3(0, 0, 520)})()})()
    station, distance = world.nearest_station(dummy_ship)
    assert station is not None
    assert station.id == "dock"
    assert distance == 20.0
