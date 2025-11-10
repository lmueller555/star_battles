"""Overlay visualisation for the sector FTL map."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, Optional

import pygame
from pygame.math import Vector2

from game.ships.ship import Ship
from game.world.sector import SectorMap
from game.world.space import SpaceWorld


MAP_MAX_WIDTH = 480
MAP_MAX_HEIGHT = 260
MAP_HORIZONTAL_MARGIN = 32
MAP_BOTTOM_MARGIN = 48


@dataclass
class MapSelection:
    hovered_id: Optional[str] = None
    armed_id: Optional[str] = None


def map_display_rect(surface_size: tuple[int, int]) -> pygame.Rect:
    width = min(surface_size[0] - MAP_HORIZONTAL_MARGIN * 2, MAP_MAX_WIDTH)
    height = min(surface_size[1] - MAP_BOTTOM_MARGIN * 2, MAP_MAX_HEIGHT)
    width = max(0, width)
    height = max(0, height)
    x = max(0, (surface_size[0] - width) // 2)
    y = max(0, surface_size[1] - height - MAP_BOTTOM_MARGIN)
    return pygame.Rect(x, y, width, height)


class SectorMapView:
    def __init__(self, sector: SectorMap) -> None:
        self.sector = sector
        self.font = pygame.font.SysFont("consolas", 20)
        self.small_font = pygame.font.SysFont("consolas", 16)
        self.selection = MapSelection()
        self._positions: Dict[str, Vector2] = {}
        self._rect = pygame.Rect(0, 0, 0, 0)
        self._grid_padding = Vector2()
        self._grid_usable = Vector2()
        self._galaxy_points = self._generate_galaxy_points()

    def _generate_galaxy_points(self) -> list[tuple[float, float, float, float]]:
        rng = random.Random(48151623)
        points: list[tuple[float, float, float, float]] = []
        arms = 3
        steps = 90
        for arm in range(arms):
            base_angle = arm * (2.0 * math.pi / arms)
            for i in range(steps):
                t = i / steps
                radius = 0.1 + t * 0.9 + rng.uniform(-0.02, 0.02)
                angle = base_angle + t * 2.6 + rng.uniform(-0.12, 0.12)
                brightness = rng.uniform(0.3, 1.0)
                size = rng.uniform(0.5, 1.2)
                points.append((radius, angle, brightness, size))
        return points

    def _compute_layout(self, surface_size: tuple[int, int]) -> None:
        width = max(0, surface_size[0])
        height = max(0, surface_size[1])
        self._rect = pygame.Rect(0, 0, int(width), int(height))
        width = float(self._rect.width)
        height = float(self._rect.height)
        min_x, min_y, max_x, max_y = self.sector.bounds()
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        padding = Vector2(40, 40)
        usable = Vector2(
            max(0.0, width - padding.x * 2),
            max(0.0, height - padding.y * 2),
        )
        self._grid_padding = padding
        self._grid_usable = usable
        self._positions.clear()
        for system in self.sector.all_systems():
            norm_x = (system.position[0] - min_x) / span_x
            norm_y = (system.position[1] - min_y) / span_y
            pos = Vector2(
                self._rect.left + padding.x + usable.x * norm_x,
                self._rect.top + padding.y + usable.y * (1.0 - norm_y),
            )
            self._positions[system.id] = pos

    def pick_system(self, mouse_pos: tuple[int, int]) -> Optional[str]:
        if not self._rect.collidepoint(mouse_pos):
            return None
        closest = None
        closest_dist = float("inf")
        point = Vector2(mouse_pos)
        for system_id, pos in self._positions.items():
            dist = pos.distance_to(point)
            if dist < 24.0 and dist < closest_dist:
                closest = system_id
                closest_dist = dist
        return closest

    def _draw_grid(self, surface: pygame.Surface) -> None:
        if self._grid_usable.x <= 0 or self._grid_usable.y <= 0:
            return
        divisions = 6
        origin_x = float(self._grid_padding.x)
        origin_y = float(self._grid_padding.y)
        width = float(self._grid_usable.x)
        height = float(self._grid_usable.y)
        if width <= 0.0 or height <= 0.0:
            return
        step_x = width / divisions
        step_y = height / divisions
        grid_color = (48, 72, 100)
        for i in range(1, divisions):
            y = origin_y + step_y * i
            pygame.draw.line(
                surface,
                grid_color,
                (int(round(origin_x)), int(round(y))),
                (int(round(origin_x + width)), int(round(y))),
                1,
            )
        for i in range(1, divisions):
            x = origin_x + step_x * i
            pygame.draw.line(
                surface,
                grid_color,
                (int(round(x)), int(round(origin_y))),
                (int(round(x)), int(round(origin_y + height))),
                1,
            )
        edge_rect = pygame.Rect(
            int(round(origin_x)),
            int(round(origin_y)),
            max(1, int(round(width))),
            max(1, int(round(height))),
        )
        pygame.draw.rect(surface, (90, 130, 170), edge_rect, 2)

    def _draw_galaxy_background(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        if width <= 0 or height <= 0:
            return
        center = Vector2(width / 2.0, height / 2.0)
        max_radius = min(width, height) * 0.48

        for i in range(6, 0, -1):
            ratio = i / 6.0
            color = (
                20,
                40 + int(35 * ratio),
                70 + int(90 * ratio),
                int(25 + 30 * ratio),
            )
            pygame.draw.circle(
                surface,
                color,
                (int(center.x), int(center.y)),
                max(1, int(max_radius * ratio)),
            )

        pygame.draw.circle(
            surface,
            (220, 230, 255, 140),
            (int(center.x), int(center.y)),
            max(2, int(max_radius * 0.18)),
        )

        for radius, angle, brightness, size in self._galaxy_points:
            r = radius * max_radius
            direction = Vector2(math.cos(angle), math.sin(angle))
            pos = center + direction * r
            intensity = 150 + int(90 * brightness)
            alpha = 80 + int(100 * brightness)
            color = (intensity, intensity, 255, alpha)
            pygame.draw.circle(
                surface,
                color,
                (int(pos.x), int(pos.y)),
                max(1, int(round(size * 2.0))),
            )

    def draw(
        self,
        surface: pygame.Surface,
        world: SpaceWorld,
        player: Ship,
        status_text: str | None = None,
    ) -> None:
        self._compute_layout(surface.get_size())
        overlay = pygame.Surface(self._rect.size, pygame.SRCALPHA)
        overlay.fill((8, 12, 20, 230))
        self._draw_galaxy_background(overlay)
        self._draw_grid(overlay)
        surface.blit(overlay, self._rect.topleft)

        pygame.draw.rect(surface, (80, 110, 140), self._rect, 2)

        current_id = world.current_system_id
        reachable = set()
        if current_id:
            for system in self.sector.reachable(current_id, player.stats.ftl_range):
                reachable.add(system.id)

        for system in self.sector.all_systems():
            if not current_id or system.id == current_id:
                continue
            start = self._positions[current_id]
            end = self._positions[system.id]
            color = (50, 80, 110)
            if system.id in reachable:
                color = (90, 160, 200)
            pygame.draw.line(surface, color, start, end, 1)

        for system in self.sector.all_systems():
            pos = self._positions.get(system.id, Vector2())
            radius = 10
            color = (120, 160, 200)
            if system.threat:
                color = (220, 110, 130)
            if world.pending_jump_id == system.id:
                color = (255, 220, 120)
                radius = 13
            elif system.id == current_id:
                color = (140, 255, 160)
                radius = 14
            elif system.id in reachable:
                color = (150, 200, 240)
            if self.selection.hovered_id == system.id or self.selection.armed_id == system.id:
                radius += 3
            pygame.draw.circle(surface, color, (int(pos.x), int(pos.y)), radius, 2)
            name_text = self.small_font.render(system.name, True, color)
            surface.blit(name_text, (pos.x + 12, pos.y - 10))

        info_lines = []
        if current_id:
            current = self.sector.get(current_id)
            info_lines.append(f"Current: {current.name}")
        if self.selection.hovered_id:
            target = self.sector.get(self.selection.hovered_id)
            distance = 0.0
            if current_id:
                distance = self.sector.distance(current_id, target.id)
            cost = distance * player.stats.ftl_cost_per_ly
            info_lines.append(f"Target: {target.name}")
            info_lines.append(f"Range: {distance:.1f} ly | Cost: {cost:.0f} Tylium")
            if distance > player.stats.ftl_range:
                info_lines.append("Out of FTL range")
            elif cost > player.resources.tylium:
                info_lines.append("Insufficient Tylium")
        if world.jump_charge_remaining > 0.0 and world.pending_jump_id:
            info_lines.append(
                f"Charging: {world.jump_charge_remaining:.1f}s to {self.sector.get(world.pending_jump_id).name}"
            )
        elif world.ftl_cooldown > 0.0:
            info_lines.append(f"FTL cooldown: {world.ftl_cooldown:.1f}s")
        elif self.selection.armed_id:
            armed = self.sector.get(self.selection.armed_id)
            info_lines.append(f"Armed jump: {armed.name}")

        for i, line in enumerate(info_lines):
            text = self.font.render(line, True, (220, 240, 255))
            surface.blit(text, (self._rect.left + 24, self._rect.top + 24 + i * 26))

        if status_text:
            text = self.small_font.render(status_text, True, (255, 230, 120))
            surface.blit(
                text,
                (self._rect.left + 24, self._rect.bottom - 40),
            )

    def handle_event(self, event: pygame.event.Event) -> Optional[str]:
        if event.type == pygame.MOUSEMOTION:
            hovered = self.pick_system(event.pos)
            self.selection.hovered_id = hovered
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            hovered = self.pick_system(event.pos)
            if hovered:
                self.selection.armed_id = hovered
                return hovered
        return None


__all__ = ["SectorMapView", "MapSelection"]
