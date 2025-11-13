"""GPU-backed rendering helpers for escort-class hulls."""

from __future__ import annotations

from array import array
import logging
from typing import Sequence

import pygame

try:  # pragma: no cover - optional dependency during testing
    import moderngl
except Exception:  # pragma: no cover - handled gracefully at runtime
    moderngl = None

from pygame.math import Vector3

LOGGER = logging.getLogger(__name__)


VERTEX_SHADER_SOURCE = """
#version 330

uniform vec3 u_camera_pos;
uniform vec3 u_camera_forward;
uniform vec3 u_camera_right;
uniform vec3 u_camera_up;
uniform float u_fov_factor;
uniform float u_aspect;
uniform float u_near;
uniform float u_far;

uniform vec3 u_ship_origin;
uniform vec3 u_ship_right;
uniform vec3 u_ship_up;
uniform vec3 u_ship_forward;
uniform float u_scale;

in vec3 in_position;

void main() {
    vec3 local = in_position * u_scale;
    vec3 world = u_ship_origin
        + u_ship_right * local.x
        + u_ship_up * local.y
        + u_ship_forward * local.z;

    vec3 rel = world - u_camera_pos;
    float depth = dot(rel, u_camera_forward);

    float x = dot(rel, u_camera_right);
    float y = dot(rel, u_camera_up);

    float ndc_x = (x * u_fov_factor / u_aspect) / depth;
    float ndc_y = (y * u_fov_factor) / depth;

    float ndc_z = ((depth - u_near) / (u_far - u_near)) * 2.0 - 1.0;

    gl_Position = vec4(ndc_x, ndc_y, ndc_z, 1.0);
}
"""


FRAGMENT_SHADER_SOURCE = """
#version 330

uniform vec4 u_color;

out vec4 fragColor;

void main() {
    fragColor = u_color;
}
"""


class EscortGPURenderer:
    """Render escort-class ship wireframes using moderngl when available."""

    def __init__(
        self,
        vertices: Sequence[Vector3],
        edges: Sequence[tuple[int, int]],
    ) -> None:
        if moderngl is None:
            raise RuntimeError("moderngl is not available")

        self._ctx = moderngl.create_standalone_context(require=330)
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        self._ctx.line_width = 1.0
        self._program = self._ctx.program(
            vertex_shader=VERTEX_SHADER_SOURCE,
            fragment_shader=FRAGMENT_SHADER_SOURCE,
        )

        vertex_data = array("f")
        for vertex in vertices:
            vertex_data.extend((vertex.x, vertex.y, vertex.z))
        self._vertex_buffer = self._ctx.buffer(vertex_data.tobytes())

        index_data = array("I")
        for start, end in edges:
            index_data.append(start)
            index_data.append(end)
        self._index_buffer = self._ctx.buffer(index_data.tobytes())

        self._vao = self._ctx.vertex_array(
            self._program,
            [(self._vertex_buffer, "3f", "in_position")],
            index_buffer=self._index_buffer,
        )

        self._framebuffer = None
        self._framebuffer_size: tuple[int, int] | None = None

    def _ensure_framebuffer(self, size: tuple[int, int]) -> None:
        if size == self._framebuffer_size and self._framebuffer is not None:
            return
        if self._framebuffer is not None:
            self._framebuffer.release()
        self._framebuffer = self._ctx.simple_framebuffer(size)
        self._framebuffer.use()
        self._framebuffer_size = size

    def draw(
        self,
        surface: pygame.Surface,
        *,
        camera_position: Vector3,
        camera_forward: Vector3,
        camera_right: Vector3,
        camera_up: Vector3,
        aspect: float,
        fov_factor: float,
        near: float,
        far: float,
        ship_origin: Vector3,
        ship_right: Vector3,
        ship_up: Vector3,
        ship_forward: Vector3,
        scale: float,
        color: tuple[int, int, int],
    ) -> None:
        if self._framebuffer is None or self._framebuffer_size != surface.get_size():
            width, height = surface.get_size()
            if width <= 0 or height <= 0:
                return
            self._ensure_framebuffer((width, height))
        assert self._framebuffer is not None

        self._framebuffer.use()
        self._framebuffer.clear(0.0, 0.0, 0.0, 0.0)

        program = self._program
        program["u_camera_pos"].value = tuple(camera_position)
        program["u_camera_forward"].value = tuple(camera_forward)
        program["u_camera_right"].value = tuple(camera_right)
        program["u_camera_up"].value = tuple(camera_up)
        program["u_aspect"].value = float(aspect)
        program["u_fov_factor"].value = float(fov_factor)
        program["u_near"].value = float(near)
        program["u_far"].value = float(far)

        program["u_ship_origin"].value = tuple(ship_origin)
        program["u_ship_right"].value = tuple(ship_right)
        program["u_ship_up"].value = tuple(ship_up)
        program["u_ship_forward"].value = tuple(ship_forward)
        program["u_scale"].value = float(scale)

        r, g, b = color
        program["u_color"].value = (r / 255.0, g / 255.0, b / 255.0, 1.0)

        self._vao.render(mode=moderngl.LINES)

        data = self._framebuffer.read(components=4, alignment=1)
        width, height = surface.get_size()
        temp_surface = pygame.image.frombuffer(data, (width, height), "RGBA")
        flipped = pygame.transform.flip(temp_surface, False, True)
        surface.blit(flipped, (0, 0))


def initialize_gpu_renderer(
    vertices: Sequence[Vector3],
    edges: Sequence[tuple[int, int]],
) -> EscortGPURenderer | None:
    """Safely create a GPU renderer when moderngl is available."""

    if moderngl is None:
        LOGGER.warning("moderngl is not available; Escort GPU renderer disabled")
        return None
    try:
        return EscortGPURenderer(vertices, edges)
    except Exception as exc:  # pragma: no cover - runtime-only failure path
        LOGGER.warning("Failed to initialize Escort GPU renderer: %s", exc)
        return None


__all__ = ["EscortGPURenderer", "initialize_gpu_renderer"]

