"""Fixed timestep game loop."""
from __future__ import annotations

import time
from typing import Callable


class FixedTimestepLoop:
    """Runs a deterministic fixed update loop with variable rendering."""

    def __init__(
        self,
        update: Callable[[float], None],
        render: Callable[[float], None],
        process_events: Callable[[], None],
        fixed_hz: float = 60.0,
        max_frame_time: float = 0.25,
    ) -> None:
        self.update = update
        self.render = render
        self.process_events = process_events
        self.fixed_dt = 1.0 / fixed_hz
        self.max_frame_time = max_frame_time
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        accumulator = 0.0
        last_time = time.perf_counter()
        while self._running:
            now = time.perf_counter()
            frame_time = now - last_time
            last_time = now
            if frame_time > self.max_frame_time:
                frame_time = self.max_frame_time
            accumulator += frame_time
            self.process_events()
            while accumulator >= self.fixed_dt:
                self.update(self.fixed_dt)
                accumulator -= self.fixed_dt
            alpha = accumulator / self.fixed_dt if self.fixed_dt > 0 else 0.0
            self.render(alpha)


__all__ = ["FixedTimestepLoop"]
