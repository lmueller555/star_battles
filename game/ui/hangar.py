"""Simple hangar overlay for docked ships."""
from __future__ import annotations

import pygame

from game.ships.ship import Ship
from game.world.station import DockingStation


class HangarView:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 14)

    def draw(self, surface: pygame.Surface, ship: Ship, station: DockingStation, distance: float) -> None:
        width, height = surface.get_size()
        panel_width = int(width * 0.5)
        panel_height = int(height * 0.6)
        panel_rect = pygame.Rect((width - panel_width) // 2, (height - panel_height) // 2, panel_width, panel_height)
        pygame.draw.rect(surface, (18, 26, 32), panel_rect)
        pygame.draw.rect(surface, (70, 120, 150), panel_rect, 2)

        title = self.font.render(f"Docked at {station.name}", True, (220, 240, 255))
        surface.blit(title, (panel_rect.x + 24, panel_rect.y + 20))
        range_text = self.small_font.render(
            f"Distance: {distance:.0f} m (dock radius {station.docking_radius:.0f} m)", True, (180, 210, 230)
        )
        surface.blit(range_text, (panel_rect.x + 24, panel_rect.y + 48))

        slot_y = panel_rect.y + 84
        slot_columns = [
            ("Weapon Slots", [
                ("Cannons", ship.frame.slots.cannon, self._hardpoint_count(ship, "cannon")),
                ("Launchers", ship.frame.slots.launcher, self._hardpoint_count(ship, "launcher")),
            ]),
            ("Support Slots", [
                ("Hull", ship.frame.slots.hull, len(ship.modules_by_slot.get("hull", []))),
                ("Engine", ship.frame.slots.engine, len(ship.modules_by_slot.get("engine", []))),
                ("Computer", ship.frame.slots.computer, len(ship.modules_by_slot.get("computer", []))),
                ("Utility", ship.frame.slots.utility, len(ship.modules_by_slot.get("utility", []))),
            ]),
        ]

        column_width = panel_width // len(slot_columns)
        for column_index, (title_text, entries) in enumerate(slot_columns):
            column_x = panel_rect.x + 24 + column_index * column_width
            column_title = self.font.render(title_text, True, (210, 235, 250))
            surface.blit(column_title, (column_x, slot_y))
            for row_index, (label, capacity, used) in enumerate(entries):
                color = (150, 220, 255) if used < capacity else (255, 200, 140)
                text = self.small_font.render(f"{label}: {used}/{capacity}", True, color)
                surface.blit(text, (column_x, slot_y + 28 + row_index * 20))

        modules_title = self.font.render("Installed Modules", True, (210, 235, 250))
        modules_y = panel_rect.y + panel_height // 2 + 10
        surface.blit(modules_title, (panel_rect.x + 24, modules_y))
        module_lines = self._module_lines(ship)
        if not module_lines:
            empty = self.small_font.render("No modules fitted", True, (160, 180, 200))
            surface.blit(empty, (panel_rect.x + 24, modules_y + 28))
        else:
            for i, line in enumerate(module_lines):
                text = self.small_font.render(line, True, (180, 220, 200))
                surface.blit(text, (panel_rect.x + 24, modules_y + 28 + i * 18))

        footer = self.small_font.render("Press H to undock", True, (170, 210, 240))
        surface.blit(footer, (panel_rect.x + panel_width - footer.get_width() - 24, panel_rect.y + panel_height - 36))

    def _module_lines(self, ship: Ship) -> list[str]:
        lines: list[str] = []
        for slot_type, modules in ship.modules_by_slot.items():
            for module in modules:
                lines.append(f"{slot_type.title()}: {module.name}")
        return lines

    def _hardpoint_count(self, ship: Ship, slot_type: str) -> int:
        count = 0
        for mount in ship.mounts:
            if mount.hardpoint.slot == slot_type and mount.weapon_id:
                count += 1
        return count


__all__ = ["HangarView"]
