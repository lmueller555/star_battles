"""Global frame counter utilities for simulation systems."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class _FrameClock:
    """Tracks the current simulation frame index in a threadsafe way."""

    _frame: int = 0
    _lock: Lock = Lock()

    def advance(self) -> int:
        """Advance the global frame counter and return the new value."""

        with self._lock:
            self._frame += 1
            return self._frame

    def current(self) -> int:
        """Return the most recently published frame index."""

        with self._lock:
            return self._frame


_frame_clock = _FrameClock()


def advance_frame() -> int:
    """Advance the shared simulation frame index."""

    return _frame_clock.advance()


def current_frame() -> int:
    """Return the current simulation frame index."""

    return _frame_clock.current()


__all__ = ["advance_frame", "current_frame"]
