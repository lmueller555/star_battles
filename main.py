"""Entry point for the Star Battles vector prototype."""
from __future__ import annotations

import cProfile
import io
import json
import pstats
from pathlib import Path
from typing import Any, Dict

import pygame

from game.assets.content import ContentManager
from game.engine.input import InputBindings, InputMapper
from game.engine.logger import init_logger
from game.engine.loop import FixedTimestepLoop
from game.engine.scene import SceneManager
from game.ui.outpost_scene import OutpostInteriorScene
from game.ui.sandbox_scene import SandboxScene
from game.ui.title_scene import TitleScene
from game.ui.ship_selection_scene import ShipSelectionScene


SETTINGS_PATH = Path("settings.json")


def load_settings() -> Dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {
            "resolution": [0, 0],
            "simHz": 60,
            "maxFps": 120,
        }
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except json.JSONDecodeError:
        return {
            "resolution": [0, 0],
            "simHz": 60,
            "maxFps": 120,
        }


def main() -> None:
    settings = load_settings()
    pygame.init()
    resolution = settings.get("resolution", [1920, 1080])

    display_flags = pygame.SCALED | pygame.FULLSCREEN
    if resolution == [0, 0] or resolution == (0, 0):
        display_info = pygame.display.Info()
        resolution = (display_info.current_w, display_info.current_h)

    screen = pygame.display.set_mode(resolution, display_flags)
    pygame.display.set_caption("Star Battles Prototype")
    clock = pygame.time.Clock()

    logger = init_logger(SETTINGS_PATH)
    input_mapper = InputMapper(InputBindings.load(SETTINGS_PATH))

    content = ContentManager(Path("game/assets"))
    content.load()

    manager = SceneManager()
    manager.register("title", TitleScene)
    manager.register("ship_selection", ShipSelectionScene)
    manager.register("sandbox", SandboxScene)
    manager.register("outpost_interior", OutpostInteriorScene)
    manager.set_context(content=content, input=input_mapper, logger=logger)
    manager.activate("title")

    def process_events() -> None:
        input_mapper.begin_frame()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                loop.stop()
                return
            manager.handle_event(event)

    def update(dt: float) -> None:
        manager.update(dt)

    def render(alpha: float) -> None:
        manager.render(screen, alpha)
        pygame.display.flip()
        clock.tick(settings.get("maxFps", 120))

    loop = FixedTimestepLoop(
        update,
        render,
        process_events,
        fixed_hz=settings.get("simHz", 60),
    )

    profiler = cProfile.Profile()
    try:
        profiler.enable()
        loop.run()
    finally:
        profiler.disable()

        stats_stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stats_stream)
        stats.strip_dirs().sort_stats("cumulative").print_stats(25)

        pygame.quit()
        print("\nUsage: WASD strafe, mouse to aim, Shift boost, Ctrl brake, Q/E vertical strafe, Z/C roll, LMB cannons, RMB missiles (needs lock), T target nearest, R cycle, F3 debug overlay.")
        print("TODO Milestone 2: add Escort/Line hulls, sector FTL map with 5+ systems, mining gameplay loop, fitting UI, expanded AI behaviours.")
        print("\nProfiler results (top 25 cumulative):")
        print(stats_stream.getvalue())


if __name__ == "__main__":
    main()
