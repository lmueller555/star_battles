"""Heads-up display drawing."""
from __future__ import annotations

from typing import Optional

import pygame
from pygame.math import Vector2

from game.math.ballistics import compute_lead
from game.sensors.dradis import DradisSystem
from game.ships.ship import Ship


def format_distance(distance_m: float) -> str:
    if distance_m >= 1000.0:
        return f"{distance_m / 1000.0:.1f} km"
    return f"{distance_m:.0f} m"


class HUD:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font = pygame.font.SysFont("consolas", 16)
        self.large_font = pygame.font.SysFont("consolas", 24)
        self.overlay_enabled = False

    def toggle_overlay(self) -> None:
        self.overlay_enabled = not self.overlay_enabled

    def draw_crosshair(self) -> None:
        center = Vector2(self.surface.get_width() / 2, self.surface.get_height() / 2)
        pygame.draw.line(self.surface, (180, 220, 255), center + Vector2(-12, 0), center + Vector2(12, 0), 1)
        pygame.draw.line(self.surface, (180, 220, 255), center + Vector2(0, -12), center + Vector2(0, 12), 1)

    def draw_lead(self, camera, player: Ship, target: Optional[Ship], projectile_speed: float) -> None:
        if not target or projectile_speed <= 0.0:
            return
        origin = player.kinematics.position
        lead_point = compute_lead(origin, target.kinematics.position, target.kinematics.velocity, projectile_speed)
        screen, visible = camera.project(lead_point, self.surface.get_size())
        if visible:
            pygame.draw.circle(self.surface, (255, 220, 120), (int(screen.x), int(screen.y)), 8, 1)

    def draw_target_panel(self, camera, player: Ship, target: Optional[Ship]) -> None:
        if not target:
            text = self.font.render("NO TARGET", True, (200, 200, 200))
            self.surface.blit(text, (20, 20))
            return
        distance = player.kinematics.position.distance_to(target.kinematics.position)
        rel_speed = (target.kinematics.velocity - player.kinematics.velocity).length()
        lines = [
            f"Target: {target.frame.name}",
            f"Range: {format_distance(distance)}",
            f"Relative: {rel_speed:.1f} m/s",
            f"Hull: {target.hull:.0f}/{target.stats.hull_hp:.0f}",
        ]
        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            self.surface.blit(text, (20, 20 + i * 18))

    def draw_meters(self, player: Ship) -> None:
        width = 220
        bar_height = 10
        x = 20
        base_y = self.surface.get_height() - 80
        def draw_bar(label: str, value: float, maximum: float, color: tuple[int, int, int], offset: int) -> None:
            ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            pygame.draw.rect(self.surface, (40, 60, 80), (x, base_y + offset, width, bar_height), 1)
            pygame.draw.rect(self.surface, color, (x, base_y + offset, width * ratio, bar_height))
            text = self.font.render(f"{label}: {value:.0f}/{maximum:.0f}", True, color)
            self.surface.blit(text, (x, base_y + offset - 16))

        draw_bar("Power", player.power, player.stats.power_cap, (120, 200, 255), 0)
        draw_bar("Boost", player.boost_meter, player.stats.power_cap, (255, 160, 80), 24)
        resources = [
            f"Tylium: {player.resources.tylium:.0f}",
            f"Titanium: {player.resources.titanium:.0f}",
            f"Water: {player.resources.water:.0f}",
        ]
        for i, text in enumerate(resources):
            label = self.font.render(text, True, (170, 220, 180))
            self.surface.blit(label, (x, base_y + 48 + i * 18))

    def draw_lock_ring(self, camera, player: Ship, target: Optional[Ship]) -> None:
        if not target or player.lock_progress <= 0.0:
            return
        screen, visible = camera.project(target.kinematics.position, self.surface.get_size())
        if not visible:
            return
        radius = 25 + player.lock_progress * 30
        pygame.draw.circle(self.surface, (255, 200, 60), (int(screen.x), int(screen.y)), int(radius), 1)
        progress_text = self.font.render(f"LOCK {player.lock_progress*100:.0f}%", True, (255, 200, 60))
        self.surface.blit(progress_text, (screen.x - 30, screen.y + radius + 4))

    def draw_dradis(self, dradis: DradisSystem) -> None:
        center = Vector2(self.surface.get_width() - 140, self.surface.get_height() - 140)
        radius = 110
        pygame.draw.circle(self.surface, (60, 90, 110), center, radius, 1)
        for tick in (0.25, 0.5, 0.75, 1.0):
            pygame.draw.circle(self.surface, (40, 70, 90), center, radius * tick, 1)
            label = format_distance(dradis.owner.stats.dradis_range * tick)
            text = self.font.render(label, True, (150, 180, 200))
            self.surface.blit(text, (center.x - 60, center.y - radius * tick - 10))
        for contact in dradis.contacts.values():
            rel_pos = contact.ship.kinematics.position - dradis.owner.kinematics.position
            rel_flat = Vector2(rel_pos.x, rel_pos.z)
            if rel_flat.length_squared() == 0:
                continue
            direction = rel_flat.normalize()
            projected = center + direction * radius * min(1.0, contact.distance / dradis.owner.stats.dradis_range)
            color = (150, 255, 180) if contact.ship.team == dradis.owner.team else (255, 120, 140)
            pygame.draw.circle(self.surface, color, (int(projected.x), int(projected.y)), 4, 1)

    def draw_overlay(self, sim_dt: float, fps: float, player: Ship, target: Optional[Ship]) -> None:
        if not self.overlay_enabled:
            return
        lines = [
            f"FPS: {fps:.1f}",
            f"Sim dt: {sim_dt*1000:.2f} ms",
            f"Speed: {player.kinematics.velocity.length():.1f} m/s",
        ]
        if target:
            distance = player.kinematics.position.distance_to(target.kinematics.position)
            lines.append(f"Target dist: {format_distance(distance)}")
            lines.append(f"Lock: {player.lock_progress*100:.0f}%")
        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            self.surface.blit(text, (20, 140 + i * 18))

    def draw(self, camera, player: Ship, target: Optional[Ship], dradis: DradisSystem, projectile_speed: float, sim_dt: float, fps: float) -> None:
        self.draw_crosshair()
        self.draw_lead(camera, player, target, projectile_speed)
        self.draw_target_panel(camera, player, target)
        self.draw_meters(player)
        self.draw_lock_ring(camera, player, target)
        self.draw_dradis(dradis)
        self.draw_overlay(sim_dt, fps, player, target)


__all__ = ["HUD", "format_distance"]
