"""Heads-up display drawing."""
from __future__ import annotations

from math import radians, tan
from typing import Optional

import pygame
from pygame.math import Vector2

from game.math.ballistics import compute_lead
from game.sensors.dradis import DradisSystem
from game.world.mining import MiningHUDState
from game.ships.ship import Ship


def _gimbal_radius(
    angle_deg: float,
    fov_deg: float,
    aspect: float,
    screen_size: tuple[int, int],
) -> float:
    """Return the radius in pixels for the edge of a gimbal cone."""

    if angle_deg <= 0.0 or fov_deg <= 0.0:
        return 0.0
    width, height = screen_size
    if width <= 0 or height <= 0:
        return 0.0
    half_vertical = max(1e-5, radians(fov_deg) / 2.0)
    tan_half_vertical = max(1e-5, tan(half_vertical))
    tan_half_horizontal = max(1e-5, tan_half_vertical * max(1e-5, aspect))
    tan_angle = tan(radians(angle_deg))
    radius_h = (width * 0.5) * tan_angle / tan_half_horizontal
    radius_v = (height * 0.5) * tan_angle / tan_half_vertical
    radius = min(radius_h, radius_v)
    if not radius or radius < 0.0:
        return 0.0
    return float(radius)


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

    def draw_crosshair(self, camera, player: Ship) -> None:
        center = Vector2(self.surface.get_width() / 2, self.surface.get_height() / 2)
        pygame.draw.line(self.surface, (180, 220, 255), center + Vector2(-12, 0), center + Vector2(12, 0), 1)
        pygame.draw.line(self.surface, (180, 220, 255), center + Vector2(0, -12), center + Vector2(0, 12), 1)
        self.draw_gimbal_arcs(camera, player, center)

    def draw_gimbal_arcs(self, camera, player: Ship, center: Vector2) -> None:
        if not player or not camera:
            return
        surface_size = self.surface.get_size()
        gimbals: dict[str, list[float]] = {}
        for mount in getattr(player, "mounts", []):
            if not getattr(mount, "weapon_id", None):
                continue
            group = getattr(mount.hardpoint, "group", "primary")
            gimbals.setdefault(group, []).append(float(mount.hardpoint.gimbal))
        if not gimbals:
            return
        palette = {
            "primary": (120, 200, 255),
            "aux": (255, 190, 140),
        }
        fallback = (200, 210, 220)
        for index, group in enumerate(sorted(gimbals.keys())):
            angles = gimbals[group]
            max_angle = max(angles)
            radius = _gimbal_radius(max_angle, camera.fov, camera.aspect, surface_size)
            if radius <= 0.0:
                continue
            color = palette.get(group, fallback)
            pygame.draw.circle(
                self.surface,
                color,
                (int(center.x), int(center.y)),
                int(radius),
                1,
            )
            min_angle = min(angles)
            if min_angle < max_angle - 1.5:
                inner_radius = _gimbal_radius(min_angle, camera.fov, camera.aspect, surface_size)
                if inner_radius > 4.0:
                    pygame.draw.circle(
                        self.surface,
                        color,
                        (int(center.x), int(center.y)),
                        int(inner_radius),
                        1,
                    )
            if index >= 2:
                # Avoid overcrowding the reticle if many auxiliary groups exist.
                break

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
            if not contact.detected and contact.time_since_seen > 1.0:
                continue
            rel_pos = contact.ship.kinematics.position - dradis.owner.kinematics.position
            rel_flat = Vector2(rel_pos.x, rel_pos.z)
            if rel_flat.length_squared() == 0:
                continue
            direction = rel_flat.normalize()
            projected = center + direction * radius * min(1.0, contact.distance / dradis.owner.stats.dradis_range)
            base_color = (150, 255, 180) if contact.ship.team == dradis.owner.team else (255, 120, 140)
            intensity = max(0.3, min(1.0, contact.progress if contact.detected else contact.progress * 0.6))
            color = tuple(int(c * intensity) for c in base_color)
            size = 5 if contact.detected else 3
            pygame.draw.circle(self.surface, color, (int(projected.x), int(projected.y)), size, 1)

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

    def draw(
        self,
        camera,
        player: Ship,
        target: Optional[Ship],
        dradis: DradisSystem,
        projectile_speed: float,
        sim_dt: float,
        fps: float,
        docking_prompt: tuple[str, float, float] | None = None,
        mining_state: MiningHUDState | None = None,
    ) -> None:
        self.draw_crosshair(camera, player)
        self.draw_lead(camera, player, target, projectile_speed)
        self.draw_target_panel(camera, player, target)
        self.draw_meters(player)
        self.draw_lock_ring(camera, player, target)
        self.draw_dradis(dradis)
        self.draw_overlay(sim_dt, fps, player, target)
        if docking_prompt:
            name, distance, radius = docking_prompt
            self.draw_docking_prompt(name, distance, radius)
        if mining_state:
            self.draw_mining(mining_state)

    def draw_docking_prompt(self, name: str, distance: float, radius: float) -> None:
        text = self.font.render(f"Dock: {name} ({distance:.0f} m / {radius:.0f} m) - Press H", True, (255, 230, 140))
        x = self.surface.get_width() / 2 - text.get_width() / 2
        y = self.surface.get_height() - 140
        self.surface.blit(text, (x, y))

    def draw_mining(self, state: MiningHUDState) -> None:
        panel_width = 240
        panel_height = 140
        x = self.surface.get_width() - panel_width - 40
        y = 40
        panel_rect = pygame.Rect(x, y, panel_width, panel_height)
        pygame.draw.rect(self.surface, (18, 32, 42), panel_rect)
        pygame.draw.rect(self.surface, (80, 150, 180), panel_rect, 1)
        title = self.font.render("Mining", True, (210, 240, 255))
        self.surface.blit(title, (x + 12, y + 8))
        if state.active_node:
            node = state.active_node
            resource = node.resource.title()
            lines = [
                f"{node.name}",
                f"{resource} Grade {node.grade:.1f}",
                f"Range: {node.distance:.0f} m",
            ]
            for i, line in enumerate(lines):
                text = self.font.render(line, True, (200, 220, 255))
                self.surface.blit(text, (x + 12, y + 32 + i * 18))
            bar_rect = pygame.Rect(x + 12, y + 90, panel_width - 24, 12)
            pygame.draw.rect(self.surface, (50, 70, 90), bar_rect, 1)
            pygame.draw.rect(
                self.surface,
                (255, 200, 120),
                (bar_rect.x, bar_rect.y, bar_rect.width * max(0.0, min(1.0, state.stability)), bar_rect.height),
            )
            stability_text = self.font.render(f"Stability {state.stability * 100:.0f}%", True, (255, 220, 140))
            self.surface.blit(stability_text, (x + 12, y + 110))
            if state.yield_rate > 0.0:
                yield_text = self.font.render(f"Yield {state.yield_rate:.1f}/s", True, (180, 230, 180))
                self.surface.blit(yield_text, (x + 12, y + 128))
            else:
                idle_text = self.font.render("Stabilise beam", True, (255, 180, 160))
                self.surface.blit(idle_text, (x + 12, y + 128))
        else:
            text = self.font.render("No active beam", True, (180, 200, 220))
            self.surface.blit(text, (x + 12, y + 40))
            if state.scanning_active:
                scanning_text = self.font.render("Scanning...", True, (200, 220, 255))
                self.surface.blit(scanning_text, (x + 12, y + 62))
        if state.status:
            status_text = self.font.render(state.status, True, (255, 230, 160))
            self.surface.blit(status_text, (x + 12, y + panel_height + 8))
        if state.scanning_nodes:
            list_y = y + panel_height + 28
            for node in state.scanning_nodes[:3]:
                progress = node.scan_progress * 100
                label = f"{node.name}: {node.distance:.0f} m"
                text = self.font.render(label, True, (160, 200, 220))
                self.surface.blit(text, (x + 12, list_y))
                status = "ID" if node.discovered else f"Scan {progress:.0f}%"
                status_text = self.font.render(status, True, (140, 190, 210))
                self.surface.blit(status_text, (x + panel_width - status_text.get_width() - 12, list_y))
                list_y += 18


__all__ = ["HUD", "format_distance"]
