"""Sandbox combat scene."""
from __future__ import annotations

import pygame
from pygame.math import Vector3

from game.assets.content import ContentManager
from game.combat.targeting import is_within_gimbal, pick_nearest_target
from game.engine.input import InputMapper
from game.engine.logger import GameLogger
from game.engine.scene import Scene
from game.render.camera import ChaseCamera
from game.render.hud import HUD
from game.render.renderer import VectorRenderer
from game.sensors.dradis import DradisSystem
from game.ships.ship import Ship
from game.world.space import SpaceWorld
from game.ui.sector_map import SectorMapView


class SandboxScene(Scene):
    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.content: ContentManager | None = None
        self.input: InputMapper | None = None
        self.logger: GameLogger | None = None
        self.world: SpaceWorld | None = None
        self.player: Ship | None = None
        self.dummy: Ship | None = None
        self.dradis: DradisSystem | None = None
        self.camera: ChaseCamera | None = None
        self.renderer: VectorRenderer | None = None
        self.hud: HUD | None = None
        self.sim_dt = 1.0 / 60.0
        self.fps = 60.0
        self.map_view: SectorMapView | None = None
        self.map_open = False
        self.armed_system_id: str | None = None
        self.jump_feedback: str = ""
        self.jump_feedback_timer: float = 0.0

    def on_enter(self, **kwargs) -> None:
        self.content = kwargs["content"]
        self.input = kwargs["input"]
        self.logger = kwargs["logger"]
        self.world = SpaceWorld(self.content.weapons, self.content.sector, self.logger)
        player_frame = self.content.ships.get("interceptor_mk1")
        self.player = Ship(player_frame, team="player", modules=["pd"])
        self.player.assign_weapon("hp_light_1", "light_cannon_mk1")
        self.player.assign_weapon("hp_light_2", "light_cannon_mk1")
        self.player.assign_weapon("hp_missile", "missile_launcher_mk1")
        self.player.kinematics.position = Vector3(0.0, 0.0, 0.0)
        self.world.add_ship(self.player)

        dummy_frame = self.content.ships.get("assault_dummy")
        self.dummy = Ship(dummy_frame, team="enemy", modules=["jammer"])
        self.dummy.assign_weapon("hp_light_1", "heavy_cannon_mk1")
        self.dummy.kinematics.position = Vector3(0.0, 0.0, 800.0)
        self.dummy.kinematics.velocity = Vector3(0.0, 0.0, -10.0)
        self.world.add_ship(self.dummy)

        self.dradis = DradisSystem(self.player)
        surface = pygame.display.get_surface()
        aspect = surface.get_width() / surface.get_height()
        self.camera = ChaseCamera(70.0, aspect)
        self.renderer = VectorRenderer(surface)
        self.hud = HUD(surface)
        self.map_view = SectorMapView(self.content.sector)
        self.map_open = False
        self.armed_system_id = None
        self.jump_feedback = ""
        self.jump_feedback_timer = 0.0
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

    def on_exit(self) -> None:
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.input:
            self.input.handle_event(event)
        if self.map_open and self.map_view:
            selection = self.map_view.handle_event(event)
            if selection:
                self.armed_system_id = selection
                self.map_view.selection.armed_id = selection
                if self.content:
                    system = self.content.sector.get(selection)
                    self.jump_feedback = f"Jump armed: {system.name} (press J to commit)"
                    self.jump_feedback_timer = 4.0
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.map_open:
                self.map_open = False
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
            else:
                self.manager.activate("title")

    def update(self, dt: float) -> None:
        self.sim_dt = dt
        if not self.input or not self.player or not self.world or not self.dradis:
            return
        self.input.update_axes()
        if self.input.consume_action("open_map"):
            self.map_open = not self.map_open
            pygame.mouse.set_visible(self.map_open)
            pygame.event.set_grab(not self.map_open)
        if self.map_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
        else:
            mouse_dx, mouse_dy = self.input.mouse()
            self.player.control.look_delta = Vector3(mouse_dx, mouse_dy, 0.0)
            self.player.control.strafe = Vector3(
                self.input.axis_state.get("strafe_x", 0.0),
                self.input.axis_state.get("strafe_y", 0.0),
                0.0,
            )
            self.player.control.throttle = self.input.axis_state.get("throttle", 0.0)
            self.player.control.boost = self.input.action("boost")
            self.player.control.brake = self.input.action("brake")
            roll_input = 0.0
            pressed = pygame.key.get_pressed()
            if pressed[pygame.K_z]:
                roll_input -= 1.0
            if pressed[pygame.K_c]:
                roll_input += 1.0
            self.player.control.roll_input = roll_input

        if self.input.consume_action("toggle_overlay"):
            self.hud.toggle_overlay()
        if self.input.consume_action("target_nearest"):
            target = pick_nearest_target(self.player, self.world.ships)
            if target:
                self.player.target_id = id(target)
        if self.input.consume_action("target_cycle"):
            enemies = [s for s in self.world.ships if s.team != self.player.team and s.is_alive()]
            if enemies:
                if self.player.target_id is None:
                    self.player.target_id = id(enemies[0])
                else:
                    idx = next((i for i, s in enumerate(enemies) if id(s) == self.player.target_id), -1)
                    self.player.target_id = id(enemies[(idx + 1) % len(enemies)])

        if self.input.consume_action("commit_jump") and self.armed_system_id and self.world and self.player:
            success, message = self.world.begin_jump(self.player, self.armed_system_id)
            self.jump_feedback = message
            self.jump_feedback_timer = 4.0
            if success:
                self.map_open = False
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
                if self.map_view:
                    self.map_view.selection.armed_id = None
                self.armed_system_id = None

        target = next((s for s in self.world.ships if id(s) == self.player.target_id), None)

        if self.input.action("fire_primary") and target and is_within_gimbal(self.player.mounts[0], self.player, target):
            result = self.world.fire_mount(self.player, self.player.mounts[0], target)
            if result and result.hit and self.camera:
                self.camera.apply_recoil(0.4)
        if self.input.action("fire_primary") and target and is_within_gimbal(self.player.mounts[1], self.player, target):
            self.world.fire_mount(self.player, self.player.mounts[1], target)
        if self.input.action("fire_secondary") and target and self.player.lock_progress >= 1.0:
            mount = next((m for m in self.player.mounts if m.hardpoint.slot == "launcher"), None)
            if mount:
                self.world.fire_mount(self.player, mount, target)
                self.player.lock_progress = 0.0

        self.world.update(dt)
        self.dradis.update(self.world.ships, dt)
        if target and not target.is_alive():
            self.player.target_id = None
        self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
        if self.jump_feedback_timer > 0.0:
            self.jump_feedback_timer = max(0.0, self.jump_feedback_timer - dt)

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        if not self.renderer or not self.camera or not self.player or not self.hud or not self.world:
            return
        self.renderer.surface = surface
        self.hud.surface = surface
        self.renderer.clear()
        self.camera.update(self.player, self.sim_dt)
        for ship in self.world.ships:
            if ship.is_alive():
                self.renderer.draw_ship(self.camera, ship)
        self.renderer.draw_projectiles(self.camera, self.world.projectiles)
        target = next((s for s in self.world.ships if id(s) == self.player.target_id), None)
        projectile_speed = 0.0
        if target and self.content:
            for mount in self.player.mounts:
                if mount.weapon_id:
                    weapon = self.content.weapons.get(mount.weapon_id)
                    if weapon.wclass != "hitscan":
                        projectile_speed = weapon.projectile_speed
        if self.dradis:
            self.hud.draw(self.camera, self.player, target, self.dradis, projectile_speed, self.sim_dt, self.fps)
        if self.map_open and self.map_view:
            status = self.jump_feedback if self.jump_feedback_timer > 0.0 else None
            self.map_view.draw(surface, self.world, self.player, status)
        elif self.jump_feedback_timer > 0.0:
            text = self.hud.font.render(self.jump_feedback, True, (255, 230, 120))
            surface.blit(
                text,
                (
                    surface.get_width() / 2 - text.get_width() / 2,
                    surface.get_height() - 100,
                ),
            )


__all__ = ["SandboxScene"]
