"""Lightweight runtime telemetry helpers for performance instrumentation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable

from game.engine.logger import ChannelLogger


@dataclass
class BasisTelemetrySnapshot:
    frame: int
    hits: int
    misses: int
    duplicates: int
    ships: int
    revisions: Dict[int, int]


@dataclass
class BasisTelemetry:
    """Tracks cache efficiency for ship orientation basis vectors."""

    frame: int = -1
    hits: int = 0
    misses: int = 0
    duplicates: int = 0
    _ship_revisions: Dict[int, int] = field(default_factory=dict)

    def begin_frame(self, frame: int) -> None:
        if frame != self.frame:
            self.frame = frame
            self.hits = 0
            self.misses = 0
            self.duplicates = 0
            self._ship_revisions.clear()

    def record_hit(self, frame: int) -> None:
        self.begin_frame(frame)
        self.hits += 1

    def record_miss(self, frame: int, ship_id: int) -> None:
        self.begin_frame(frame)
        self.misses += 1
        if self._ship_revisions.get(ship_id) == frame:
            self.duplicates += 1
        self._ship_revisions[ship_id] = frame

    def snapshot(self) -> BasisTelemetrySnapshot:
        return BasisTelemetrySnapshot(
            frame=self.frame,
            hits=self.hits,
            misses=self.misses,
            duplicates=self.duplicates,
            ships=len(self._ship_revisions),
            revisions=dict(self._ship_revisions),
        )


_basis_telemetry = BasisTelemetry()


def record_basis_hit(frame: int) -> None:
    _basis_telemetry.record_hit(frame)


def record_basis_miss(frame: int, ship_id: int) -> None:
    _basis_telemetry.record_miss(frame, ship_id)


def basis_snapshot() -> BasisTelemetrySnapshot:
    return _basis_telemetry.snapshot()


@dataclass
class CollisionTelemetrySnapshot:
    collidables: int
    candidates: int
    culled: int
    tested: int
    duration_ms: float


@dataclass
class CollisionTelemetry:
    """Aggregates broad-phase collision statistics per frame."""

    frame: int = -1
    collidables: int = 0
    candidates: int = 0
    culled: int = 0
    tested: int = 0
    duration_ms: float = 0.0
    _log_accumulator: float = 0.0

    def begin_frame(self, frame: int, collidables: int) -> None:
        if frame != self.frame:
            self.frame = frame
            self.collidables = collidables
            self.candidates = 0
            self.culled = 0
            self.tested = 0
            self.duration_ms = 0.0

    def record_candidates(self, count: int) -> None:
        self.candidates += count

    def record_culled(self, count: int) -> None:
        self.culled += count

    def record_tested(self, count: int) -> None:
        self.tested += count

    def add_duration(self, duration_ms: float) -> None:
        self.duration_ms += duration_ms

    def advance_time(self, dt: float, logger: ChannelLogger | None = None) -> None:
        self._log_accumulator += dt
        if self._log_accumulator >= 2.5:
            self._log_accumulator = 0.0
            if logger and logger.enabled:
                logger.info(
                    "Collisions: collidables=%d candidates=%d culled=%d tested=%d time=%.2fms",
                    self.collidables,
                    self.candidates,
                    self.culled,
                    self.tested,
                    self.duration_ms,
                )

    def snapshot(self) -> CollisionTelemetrySnapshot:
        return CollisionTelemetrySnapshot(
            collidables=self.collidables,
            candidates=self.candidates,
            culled=self.culled,
            tested=self.tested,
            duration_ms=self.duration_ms,
        )


_BUCKETS: tuple[str, ...] = ("near", "mid", "far", "sentry")


@dataclass
class AITelemetrySnapshot:
    counts: Dict[str, int]
    updates: Dict[str, int]

    @property
    def total_agents(self) -> int:
        return sum(self.counts.values())

    @property
    def updated_agents(self) -> int:
        return sum(self.updates.values())


@dataclass
class AITelemetry:
    """Tracks how many AI controllers are updated per distance bucket."""

    frame: int = -1
    counts: Dict[str, int] = field(default_factory=lambda: {bucket: 0 for bucket in _BUCKETS})
    updates: Dict[str, int] = field(default_factory=lambda: {bucket: 0 for bucket in _BUCKETS})
    _log_accumulator: float = 0.0

    def begin_frame(self, frame: int) -> None:
        if frame != self.frame:
            self.frame = frame
            for bucket in _BUCKETS:
                self.counts[bucket] = 0
                self.updates[bucket] = 0

    def record(self, bucket: str, updated: bool) -> None:
        if bucket not in self.counts:
            bucket = "far"
        self.counts[bucket] += 1
        if updated:
            self.updates[bucket] += 1

    def advance_time(self, dt: float, logger: ChannelLogger | None = None) -> None:
        self._log_accumulator += dt
        if self._log_accumulator >= 3.0:
            self._log_accumulator = 0.0
            if logger and logger.enabled:
                logger.info(
                    "AI ticks: near=%d/%d mid=%d/%d far=%d/%d sentry=%d/%d",
                    self.updates["near"],
                    self.counts["near"],
                    self.updates["mid"],
                    self.counts["mid"],
                    self.updates["far"],
                    self.counts["far"],
                    self.updates["sentry"],
                    self.counts["sentry"],
                )

    def snapshot(self) -> AITelemetrySnapshot:
        return AITelemetrySnapshot(counts=dict(self.counts), updates=dict(self.updates))


@dataclass
class PerformanceSnapshot:
    basis: BasisTelemetrySnapshot | None = None
    collisions: CollisionTelemetrySnapshot | None = None
    ai: AITelemetrySnapshot | None = None

    def basis_hit_rate(self) -> float:
        if not self.basis:
            return 0.0
        total = self.basis.hits + self.basis.misses
        if total <= 0:
            return 0.0
        return self.basis.hits / total


def combine_performance(
    basis: BasisTelemetrySnapshot | None,
    collisions: CollisionTelemetrySnapshot | None,
    ai: AITelemetrySnapshot | None,
) -> PerformanceSnapshot:
    return PerformanceSnapshot(basis=basis, collisions=collisions, ai=ai)


__all__ = [
    "AITelemetry",
    "AITelemetrySnapshot",
    "BasisTelemetrySnapshot",
    "CollisionTelemetry",
    "CollisionTelemetrySnapshot",
    "PerformanceSnapshot",
    "basis_snapshot",
    "combine_performance",
    "record_basis_hit",
    "record_basis_miss",
]
