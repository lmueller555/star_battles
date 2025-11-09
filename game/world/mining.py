"""Mining node data structures and runtime controller."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional

from pygame.math import Vector3

from game.engine.logger import ChannelLogger
if TYPE_CHECKING:
    from game.ships.ship import Ship

RESOURCE_ATTRS = {
    "tylium": "tylium",
    "titanium": "titanium",
    "water": "water",
}


@dataclass
class MiningNodeData:
    id: str
    name: str
    system: str
    resource: str
    grade: float
    base_yield: float
    position: Vector3
    scan_time: float
    stability_decay: float

    @classmethod
    def from_dict(cls, data: Dict) -> "MiningNodeData":
        resource = data.get("resource", "tylium").lower()
        return cls(
            id=data["id"],
            name=data.get("name", data["id"].title()),
            system=data["system"],
            resource=resource,
            grade=float(data.get("grade", 1.0)),
            base_yield=float(data.get("baseYield", 5.0)),
            position=Vector3(*data.get("position", (0.0, 0.0, 0.0))),
            scan_time=float(data.get("scanTime", 3.0)),
            stability_decay=float(data.get("stabilityDecay", 0.2)),
        )


class MiningDatabase:
    """Static mining data read from disk."""

    def __init__(self) -> None:
        self._nodes: Dict[str, List[MiningNodeData]] = {}

    def load(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return
        if isinstance(data, dict):
            nodes = data.get("nodes", [])
        else:
            nodes = data
        for entry in nodes:
            try:
                node = MiningNodeData.from_dict(entry)
            except (KeyError, TypeError, ValueError):
                continue
            self._nodes.setdefault(node.system, []).append(node)

    def nodes_in_system(self, system_id: str) -> Iterable[MiningNodeData]:
        return list(self._nodes.get(system_id, []))


@dataclass
class MiningNodeRuntime:
    data: MiningNodeData
    scan_progress: float = 0.0
    discovered: bool = False
    active: bool = False
    stability: float = 1.0
    yield_rate: float = 0.0
    last_yield: float = 0.0
    alert_triggered: bool = False


@dataclass
class MiningNodeView:
    id: str
    name: str
    resource: str
    grade: float
    distance: float
    scan_progress: float
    discovered: bool


@dataclass
class MiningHUDState:
    active_node: Optional[MiningNodeView]
    stability: float
    yield_rate: float
    last_yield: float
    status: Optional[str]
    scanning_nodes: List[MiningNodeView]
    scanning_active: bool
    alert_triggered: bool = False


class MiningManager:
    """Controls scanning and extraction mini-game."""

    SCAN_RANGE = 1600.0
    LATCH_RANGE = 220.0
    STABILITY_RECOVERY = 0.65

    def __init__(self, database: MiningDatabase) -> None:
        self._database = database
        self._nodes: List[MiningNodeRuntime] = []
        self._active: Optional[MiningNodeRuntime] = None
        self._status: str = ""
        self._status_timer: float = 0.0

    @property
    def nodes(self) -> List[MiningNodeRuntime]:
        return self._nodes

    def enter_system(self, system_id: Optional[str]) -> None:
        self._nodes = []
        self._active = None
        if not system_id:
            return
        self._nodes = [MiningNodeRuntime(node) for node in self._database.nodes_in_system(system_id)]
        self._status = ""
        self._status_timer = 0.0

    def active_node(self) -> Optional[MiningNodeRuntime]:
        return self._active

    def _set_status(self, message: str, duration: float = 3.0) -> None:
        self._status = message
        self._status_timer = duration

    def start_mining(self, ship: "Ship") -> tuple[bool, str]:
        if not self._nodes:
            return False, "No mining sites in system"
        if self._active:
            return False, "Mining already active"
        candidate, distance = self._nearest_discovered(ship)
        if not candidate or distance > self.LATCH_RANGE:
            return False, "No discovered node in range"
        candidate.active = True
        candidate.stability = 1.0
        candidate.yield_rate = 0.0
        candidate.last_yield = 0.0
        candidate.alert_triggered = False
        self._active = candidate
        message = f"Mining {candidate.data.name}".strip()
        self._set_status(message)
        return True, message

    def stop_mining(self) -> None:
        if self._active:
            self._active.active = False
        self._active = None
        self._set_status("Mining disengaged", 2.0)

    def scan_step(self, ship: "Ship", dt: float) -> None:
        for node in self._nodes:
            distance = node.data.position.distance_to(ship.kinematics.position)
            if distance > self.SCAN_RANGE:
                continue
            if node.discovered:
                continue
            node.scan_progress = min(1.0, node.scan_progress + dt / max(0.1, node.data.scan_time))
            if node.scan_progress >= 1.0:
                node.discovered = True
                self._set_status(f"Scan complete: {node.data.name} (Grade {node.data.grade:.1f})")

    def step(
        self,
        ship: "Ship",
        dt: float,
        stabilizing: bool,
        scanning_active: bool,
        logger: Optional[ChannelLogger] = None,
    ) -> MiningHUDState:
        scanning_views = self._build_views(ship)
        alert = False
        if self._active:
            distance = self._active.data.position.distance_to(ship.kinematics.position)
            if distance > self.LATCH_RANGE * 1.3:
                if logger and logger.enabled:
                    logger.info("Mining disengaged: out of range (%.1fm)", distance)
                self.stop_mining()
            else:
                decay = self._active.data.stability_decay
                self._active.stability = max(0.0, self._active.stability - decay * dt)
                if stabilizing:
                    self._active.stability = min(1.0, self._active.stability + self.STABILITY_RECOVERY * dt)
                if self._active.stability <= 0.0:
                    self._active.stability = 0.0
                    if not self._active.alert_triggered:
                        self._set_status("Instability detected! Pirate drones inbound")
                        self._active.alert_triggered = True
                        alert = True
                    self._active.yield_rate = 0.0
                    self._active.last_yield = 0.0
                else:
                    efficiency = 0.35 + 0.65 * self._active.stability
                    bonus = 1.0 + ship.module_stat_total("mining_bonus")
                    yield_rate = self._active.data.base_yield * self._active.data.grade * bonus * efficiency
                    amount = yield_rate * dt
                    attr = RESOURCE_ATTRS.get(self._active.data.resource, "tylium")
                    current = getattr(ship.resources, attr, None)
                    if current is not None:
                        setattr(ship.resources, attr, current + amount)
                    self._active.yield_rate = yield_rate
                    self._active.last_yield = amount
                    if logger and logger.enabled:
                        logger.debug(
                            "Mining %.1f of %s (grade %.2f, stability %.2f)",
                            amount,
                            self._active.data.resource,
                            self._active.data.grade,
                            self._active.stability,
                        )
        if self._status_timer > 0.0:
            self._status_timer = max(0.0, self._status_timer - dt)
            if self._status_timer == 0.0:
                self._status = ""
        active_view = None
        stability = 0.0
        yield_rate = 0.0
        last_yield = 0.0
        if self._active and self._active.active:
            stability = self._active.stability
            yield_rate = self._active.yield_rate
            last_yield = self._active.last_yield
            active_view = self._node_to_view(ship, self._active)
        return MiningHUDState(
            active_node=active_view,
            stability=stability,
            yield_rate=yield_rate,
            last_yield=last_yield,
            status=self._status if self._status else None,
            scanning_nodes=scanning_views,
            scanning_active=scanning_active,
            alert_triggered=alert,
        )

    def _build_views(self, ship: "Ship") -> List[MiningNodeView]:
        views: List[MiningNodeView] = []
        for node in self._nodes:
            distance = node.data.position.distance_to(ship.kinematics.position)
            if distance > self.SCAN_RANGE * 1.2:
                continue
            views.append(
                MiningNodeView(
                    id=node.data.id,
                    name=node.data.name,
                    resource=node.data.resource,
                    grade=node.data.grade,
                    distance=distance,
                    scan_progress=node.scan_progress,
                    discovered=node.discovered,
                )
            )
        views.sort(key=lambda v: v.distance)
        return views[:5]

    def _node_to_view(self, ship: "Ship", node: MiningNodeRuntime) -> MiningNodeView:
        return MiningNodeView(
            id=node.data.id,
            name=node.data.name,
            resource=node.data.resource,
            grade=node.data.grade,
            distance=node.data.position.distance_to(ship.kinematics.position),
            scan_progress=node.scan_progress,
            discovered=node.discovered,
        )

    def _nearest_discovered(self, ship: "Ship") -> tuple[Optional[MiningNodeRuntime], float]:
        best: Optional[MiningNodeRuntime] = None
        best_dist = float("inf")
        for node in self._nodes:
            if not node.discovered:
                continue
            distance = node.data.position.distance_to(ship.kinematics.position)
            if distance < best_dist:
                best = node
                best_dist = distance
        return best, best_dist


__all__ = [
    "MiningDatabase",
    "MiningManager",
    "MiningHUDState",
    "MiningNodeData",
    "MiningNodeRuntime",
    "MiningNodeView",
]
