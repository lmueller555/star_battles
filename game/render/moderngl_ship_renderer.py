"""GPU accelerated wireframe rendering for ship silhouettes using moderngl."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence, Tuple

LOGGER = logging.getLogger(__name__)

import pygame

try:  # pragma: no cover - runtime dependency may be missing during tests
    import moderngl
except Exception:  # pragma: no cover - fallback when moderngl unavailable
    moderngl = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    import numpy as np
except Exception:  # pragma: no cover - fallback when numpy unavailable
    np = None  # type: ignore[assignment]
    LOGGER.warning("numpy is not available; GPU ship rendering disabled.")


VERTEX_SHADER = """
#version 330
in vec2 in_vert;
uniform vec2 u_viewport;
void main() {
    vec2 ndc = (in_vert / u_viewport) * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
}
"""


FRAGMENT_SHADER = """
#version 330
uniform vec4 u_color;
out vec4 f_color;
void main() {
    f_color = u_color;
}
"""


@dataclass
class _RenderTarget:
    width: int
    height: int


class ModernglShipRenderer:
    """Render batches of 2D line segments using moderngl."""

    def __init__(self) -> None:
        self._available = False
        self._ctx: moderngl.Context | None = None
        self._program: moderngl.Program | None = None
        self._vbo: moderngl.Buffer | None = None
        self._vao: moderngl.VertexArray | None = None
        self._fbo: moderngl.Framebuffer | None = None
        self._target: _RenderTarget | None = None
        self._init_context()

    @property
    def available(self) -> bool:
        return self._available

    def _init_context(self) -> None:
        if moderngl is None:
            LOGGER.warning("moderngl is not available; GPU ship rendering disabled.")
            return
        try:
            self._ctx = moderngl.create_standalone_context()
        except Exception as exc:  # pragma: no cover - environment dependent
            LOGGER.warning("Unable to create moderngl context: %s", exc)
            self._ctx = None
            return
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        self._program = self._ctx.program(
            vertex_shader=VERTEX_SHADER,
            fragment_shader=FRAGMENT_SHADER,
        )
        self._vbo = self._ctx.buffer(reserve=1024)
        self._vao = self._ctx.simple_vertex_array(self._program, self._vbo, "in_vert")
        self._available = True

    def _ensure_target(self, width: int, height: int) -> bool:
        if not self._available or self._ctx is None:
            return False
        if width <= 0 or height <= 0:
            return False
        if self._target and self._target.width == width and self._target.height == height:
            return True
        if self._fbo is not None:
            self._fbo.release()
        self._fbo = self._ctx.simple_framebuffer((width, height))
        self._fbo.use()
        self._target = _RenderTarget(width=width, height=height)
        return True

    def render_segments(
        self,
        target_surface: pygame.Surface,
        segments: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]],
        color: Tuple[int, int, int],
        *,
        line_width: float = 1.0,
    ) -> bool:
        """Render the provided line segments into ``target_surface``.

        Returns ``True`` when GPU rendering succeeds. When GPU rendering is
        unavailable, ``False`` is returned, signaling the caller to fall back to
        CPU rasterisation.
        """

        if np is None:
            return False
        if not self._available or self._ctx is None or not segments:
            return False
        width, height = target_surface.get_size()
        if not self._ensure_target(width, height):
            return False

        assert self._program is not None
        assert self._vbo is not None
        assert self._vao is not None
        assert self._fbo is not None

        vertices = np.zeros((len(segments) * 2, 2), dtype="f4")
        for index, segment in enumerate(segments):
            start, end = segment
            vertices[index * 2] = start
            vertices[index * 2 + 1] = end

        self._vbo.orphan(vertices.nbytes)
        self._vbo.write(vertices.tobytes())

        self._program["u_viewport"].value = (float(width), float(height))
        rgba = (
            float(color[0]) / 255.0,
            float(color[1]) / 255.0,
            float(color[2]) / 255.0,
            1.0,
        )
        self._program["u_color"].value = rgba

        try:
            self._ctx.line_width = max(1.0, float(line_width))
        except Exception:  # pragma: no cover - backend specific behaviour
            pass

        self._fbo.use()
        self._fbo.clear(0.0, 0.0, 0.0, 0.0)
        self._vao.render(mode=moderngl.LINES, vertices=len(segments) * 2)

        buffer = self._fbo.read(components=4, alignment=1)
        surface = pygame.image.frombuffer(buffer, (width, height), "RGBA")
        surface = pygame.transform.flip(surface, False, True).convert_alpha()
        target_surface.blit(surface, (0, 0))
        return True


__all__ = ["ModernglShipRenderer"]
