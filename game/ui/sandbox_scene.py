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
from game.world.ai import create_ai_for_ship
from game.world.space import SpaceWorld
from game.world.mining import MiningHUDState
from game.world.station import DockingStation
from game.ui.sector_map import SectorMapView
from game.ui.hangar import HangarView


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
        self.freelook_active: bool = False
        self.freelook_delta: tuple[float, float] = (0.0, 0.0)
        self.mining_state: MiningHUDState | None = None
        self.mining_feedback: str = ""
        self.mining_feedback_timer: float = 0.0
        self.weapon_group_actions: dict[str, str] = {}
        self.combat_feedback: str = ""
        self.combat_feedback_timer: float = 0.0

    def on_enter(self, **kwargs) -> None:
        self.content = kwargs["content"]
        self.input = kwargs["input"]
        self.logger = kwargs["logger"]
        self.world = SpaceWorld(
            self.content.weapons,
            self.content.sector,
            self.content.stations,
            self.content.mining,
            self.logger,
        )
        player_frame = self.content.ships.get("interceptor_mk1")
        self.player = Ship(player_frame, team="player")
        if self.content:
            self.player.equip_module(self.content.items.get("point_defense_mk1"))
            self.player.equip_module(self.content.items.get("eccm_mk1"))
            self.player.equip_module(self.content.items.get("flare_launcher_mk1"))
        self.player.assign_weapon("hp_light_1", "light_cannon_mk1")
        self.player.assign_weapon("hp_light_2", "light_cannon_mk1")
        self.player.assign_weapon("hp_missile", "missile_launcher_mk1")
        self.player.kinematics.position = Vector3(0.0, 0.0, 0.0)
        self.world.add_ship(self.player)

        dummy_frame = self.content.ships.get("assault_dummy")
        self.dummy = Ship(dummy_frame, team="enemy")
        if self.content:
            self.dummy.equip_module(self.content.items.get("jammer_mk1"))
        self.dummy.assign_weapon("hp_light_1", "heavy_cannon_mk1")
        self.dummy.kinematics.position = Vector3(0.0, 0.0, 800.0)
        self.dummy.kinematics.velocity = Vector3(0.0, 0.0, -10.0)
        enemy_ai = create_ai_for_ship(self.dummy)
        self.world.add_ship(self.dummy, ai=enemy_ai)

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
        self.freelook_active = False
        self.freelook_delta = (0.0, 0.0)
        self.station_contact: tuple[DockingStation, float] | None = None
        self.hangar_open = False
        self.hangar_view = HangarView(surface)
        self.mining_state = None
        self.mining_feedback = ""
        self.mining_feedback_timer = 0.0
        self.weapon_group_actions.clear()
        self._configure_weapon_groups()
        self.combat_feedback = ""
        self.combat_feedback_timer = 0.0
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

    def on_exit(self) -> None:
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        self.weapon_group_actions.clear()

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
            elif self.hangar_open:
                self.hangar_open = False
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
            else:
                self.manager.activate("title")

    def update(self, dt: float) -> None:
        self.sim_dt = dt
        if not self.input or not self.player or not self.world or not self.dradis:
            return
        self.input.update_axes()
        self.freelook_delta = (0.0, 0.0)
        scanning = False
        stabilizing = False
        if self.input.consume_action("open_map"):
            self.map_open = not self.map_open
            pygame.mouse.set_visible(self.map_open)
            pygame.event.set_grab(not self.map_open)
            if self.map_open:
                self.hangar_open = False
        if self.map_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
        elif self.hangar_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
            scanning = False
            stabilizing = False
        else:
            mouse_dx, mouse_dy = self.input.mouse()
            freelook_held = self.input.action("freelook")
            if freelook_held:
                self.freelook_active = True
                self.freelook_delta = (mouse_dx, mouse_dy)
                self.player.control.look_delta = Vector3()
            else:
                self.freelook_active = False
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
            scanning = self.input.action("scan_mining")
            stabilizing = self.input.action("stabilize_mining")
            if self.input.consume_action("toggle_mining"):
                if self.world.mining_active():
                    self.world.stop_mining()
                    self._set_mining_feedback("Mining disengaged")
                else:
                    success, message = self.world.start_mining(self.player)
                    self._set_mining_feedback(message)

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

        if (
            self.input.consume_action("activate_pd")
            and self.world
            and self.player
        ):
            success, message = self.world.activate_countermeasure(self.player)
            if message:
                self._set_combat_feedback(message, duration=2.5 if success else 2.0)

        if target and self.input.action("fire_primary"):
            self._fire_group("primary", target)
        if target and self.input.action("fire_secondary"):
            self._fire_group("aux", target)
        if target:
            for action, group in self.weapon_group_actions.items():
                if self.input.action(action):
                    self._fire_group(group, target)

        station, distance = self.world.nearest_station(self.player)
        if station:
            self.station_contact = (station, distance)
            if distance > station.docking_radius + 50.0 and self.hangar_open:
                self.hangar_open = False
                pygame.mouse.set_visible(False)
                pygame.event.set_grab(True)
        else:
            self.station_contact = None
            self.hangar_open = False
        if self.station_contact and self.input.consume_action("open_hangar"):
            station, distance = self.station_contact
            if distance <= station.docking_radius:
                self.hangar_open = not self.hangar_open
                pygame.mouse.set_visible(self.hangar_open)
                pygame.event.set_grab(not self.hangar_open)
        if self.hangar_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
            scanning = False
            stabilizing = False

        self.world.update(dt)
        self.dradis.update(self.world.ships, dt)
        self.mining_state = self.world.step_mining(
            self.player,
            dt,
            scanning=scanning and not (self.map_open or self.hangar_open),
            stabilizing=stabilizing and not (self.map_open or self.hangar_open),
        )
        if self.mining_state and self.mining_state.status:
            self._set_mining_feedback(self.mining_state.status, duration=3.0)
        if target and not target.is_alive():
            self.player.target_id = None
        self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
        if self.jump_feedback_timer > 0.0:
            self.jump_feedback_timer = max(0.0, self.jump_feedback_timer - dt)
        if self.mining_feedback_timer > 0.0:
            self.mining_feedback_timer = max(0.0, self.mining_feedback_timer - dt)
        if self.combat_feedback_timer > 0.0:
            self.combat_feedback_timer = max(0.0, self.combat_feedback_timer - dt)

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        if not self.renderer or not self.camera or not self.player or not self.hud or not self.world:
            return
        self.renderer.surface = surface
        self.hud.surface = surface
        self.renderer.clear()
        target = next(
            (
                s
                for s in self.world.ships
                if id(s) == self.player.target_id and s.is_alive()
            ),
            None,
        )
        lock_mode = bool(target and self.player.lock_progress >= 1.0)
        self.camera.update(
            self.player,
            self.sim_dt,
            freelook_active=self.freelook_active,
            freelook_delta=self.freelook_delta,
            target=target,
            lock_mode=lock_mode,
        )
        for ship in self.world.ships:
            if ship.is_alive():
                self.renderer.draw_ship(self.camera, ship)
        self.renderer.draw_projectiles(self.camera, self.world.projectiles)
        projectile_speed = 0.0
        if target and self.content:
            for mount in self.player.mounts:
                if mount.weapon_id:
                    weapon = self.content.weapons.get(mount.weapon_id)
                    if weapon.wclass != "hitscan":
                        projectile_speed = weapon.projectile_speed
        docking_prompt = None
        if self.station_contact:
            station, distance = self.station_contact
            docking_prompt = (station.name, distance, station.docking_radius)
        if self.dradis:
            self.hud.draw(
                self.camera,
                self.player,
                target,
                self.dradis,
                projectile_speed,
                self.sim_dt,
                self.fps,
                docking_prompt=docking_prompt if not self.hangar_open else None,
                mining_state=self.mining_state,
            )
        if self.map_open and self.map_view:
            status = self.jump_feedback if self.jump_feedback_timer > 0.0 else None
            self.map_view.draw(surface, self.world, self.player, status)
        elif self.hangar_open and self.hangar_view and self.station_contact:
            station, distance = self.station_contact
            self.hangar_view.draw(surface, self.player, station, distance)
        if self.jump_feedback_timer > 0.0:
            self._blit_feedback(surface, self.jump_feedback, offset=100)
        if self.mining_feedback_timer > 0.0:
            self._blit_feedback(surface, self.mining_feedback, offset=70)
        if self.combat_feedback_timer > 0.0:
            self._blit_feedback(surface, self.combat_feedback, offset=40)

    def _set_mining_feedback(self, message: str, duration: float = 2.0) -> None:
        if not message:
            return
        self.mining_feedback = message
        self.mining_feedback_timer = duration

    def _set_combat_feedback(self, message: str, duration: float = 2.5) -> None:
        if not message:
            return
        self.combat_feedback = message
        self.combat_feedback_timer = duration

    def _configure_weapon_groups(self) -> None:
        if not self.player:
            return
        groups: list[str] = []
        for mount in self.player.mounts:
            group = getattr(mount.hardpoint, "group", "primary")
            if group not in groups:
                groups.append(group)
        reserved = {"primary", "aux"}
        extras = [group for group in groups if group not in reserved]
        actions = ["fire_group_alpha", "fire_group_beta", "fire_group_gamma"]
        self.weapon_group_actions = {
            action: group for action, group in zip(actions, extras)
        }

    def _fire_group(self, group: str, target: Ship) -> bool:
        if not self.world or not self.player or not target.is_alive():
            return False
        fired = False
        recoil_applied = False
        launcher_fired = False
        for mount in self.player.mounts:
            if getattr(mount.hardpoint, "group", "primary") != group:
                continue
            if not mount.weapon_id:
                continue
            weapon = self.content.weapons.get(mount.weapon_id) if self.content else None
            slot_type = weapon.slot_type if weapon else mount.hardpoint.slot
            requires_lock = slot_type == "launcher"
            if requires_lock and self.player.lock_progress < 1.0:
                continue
            if not is_within_gimbal(mount, self.player, target):
                continue
            result = self.world.fire_mount(self.player, mount, target)
            fired = True
            if slot_type == "launcher":
                launcher_fired = True
            if result and result.hit and self.camera and not recoil_applied:
                self.camera.apply_recoil(0.4)
                recoil_applied = True
        if launcher_fired:
            self.player.lock_progress = 0.0
        return fired

    def _blit_feedback(self, surface: pygame.Surface, message: str, offset: float) -> None:
        if not message:
            return
        text = self.hud.font.render(message, True, (255, 230, 120))
        surface.blit(
            text,
            (
                surface.get_width() / 2 - text.get_width() / 2,
                surface.get_height() - offset,
            ),
        )


__all__ = ["SandboxScene"]
