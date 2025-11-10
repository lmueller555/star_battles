import json

from pygame.math import Vector3

from game.combat.weapons import WeaponDatabase
from game.engine.logger import GameLogger, LoggerConfig
from game.ships.data import ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats
from game.world.sector import SectorMap
from game.world.space import SpaceWorld
from game.world.mining import MiningDatabase
from game.world.station import StationDatabase


def make_logger() -> GameLogger:
    return GameLogger(LoggerConfig(level=0, channels={}))


def make_frame(frame_id: str, *, role: str = "Interceptor", size: str = "Strike") -> ShipFrame:
    stats = ShipStats.from_dict({})
    slots = ShipSlotLayout.from_dict({})
    return ShipFrame(
        id=frame_id,
        name=frame_id.title(),
        role=role,
        size=size,
        stats=stats,
        slots=slots,
        hardpoints=[],
    )


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
    world = SpaceWorld(
        weapons=weapons,
        sector=sector,
        stations=stations,
        mining=MiningDatabase(),
        logger=logger,
    )

    player_ship = Ship(make_frame("player_ship"), team="player")
    player_ship.kinematics.position = Vector3(0.0, 0.0, 520.0)
    station_ship = Ship(make_frame("station_ship", role="Station", size="Outpost"), team="player")
    station_ship.kinematics.position = Vector3(0.0, 0.0, 500.0)

    world.add_ship(player_ship)
    world.add_ship(station_ship)

    station, distance = world.nearest_station(player_ship)
    assert station is not None
    assert station.id == "dock"
    assert distance == 20.0


def test_space_world_ignores_unanchored_station_data(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0, 0], "threat": False},
    ]))
    stations_path = tmp_path / "stations.json"
    stations_path.write_text(json.dumps([
        {"id": "ghost", "system": "alpha", "position": [200, 0, 0], "dockingRadius": 800},
    ]))

    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    stations.load(stations_path)

    world = SpaceWorld(
        weapons=WeaponDatabase(),
        sector=sector,
        stations=stations,
        mining=MiningDatabase(),
        logger=make_logger(),
    )

    player_ship = Ship(make_frame("player_ship"), team="player")
    player_ship.kinematics.position = Vector3(0.0, 0.0, 0.0)
    world.add_ship(player_ship)

    station, distance = world.nearest_station(player_ship)
    assert station is None
    assert distance == float("inf")
