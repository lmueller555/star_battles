import types

from pygame.math import Vector3

from game.ships.data import ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats
from game.ui.outpost_scene import OutpostInteriorScene
from game.world.station import DockingStation


class DummyWorld:
    def __init__(self) -> None:
        self.ships = []

    def add_ship(self, ship: Ship) -> None:
        self.ships.append(ship)


class DummyManager:
    def __init__(self) -> None:
        self.last_scene = None
        self.last_kwargs = None

    def activate(self, scene_id: str, **kwargs) -> None:
        self.last_scene = scene_id
        self.last_kwargs = kwargs


def _create_ship() -> Ship:
    stats = ShipStats.from_dict({})
    slots = ShipSlotLayout.from_dict({})
    frame = ShipFrame(
        id="test_ship",
        name="Test Ship",
        role="Test",
        size="Strike",
        stats=stats,
        slots=slots,
        hardpoints=[],
    )
    return Ship(frame, team="player")


def test_complete_undock_does_not_duplicate_player_ship() -> None:
    manager = DummyManager()
    scene = OutpostInteriorScene(manager)

    world = DummyWorld()
    player = _create_ship()
    station = DockingStation(
        id="station",
        name="Station",
        system_id="sol",
        position=(0.0, 0.0, 0.0),
        docking_radius=500.0,
    )

    world.ships.append(player)

    scene.world = world
    scene.player = player
    scene.station = station
    scene.content = types.SimpleNamespace()
    scene.input = types.SimpleNamespace()
    scene.logger = types.SimpleNamespace()

    scene._complete_undock()

    assert world.ships.count(player) == 1
