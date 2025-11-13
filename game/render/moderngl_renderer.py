"""ModernGL helpers for ship wireframe rendering."""
from __future__ import annotations

from array import array
import logging
from typing import Dict, Iterable, Tuple, TYPE_CHECKING

import pygame

try:  # pragma: no cover - optional dependency
    import moderngl
except Exception:  # pragma: no cover - handled gracefully at runtime
    moderngl = None  # type: ignore[assignment]

from pygame.math import Vector3

from game.render.camera import CameraFrameData
if TYPE_CHECKING:  # pragma: no cover
    from game.render.renderer import ShipGeometry


LOGGER = logging.getLogger(__name__)
_FALLBACK_LOGGED = False


def _matrix_to_bytes(rows: Iterable[Iterable[float]]) -> bytes:
    columns = zip(*rows)
    packed = array("f")
    for column in columns:
        packed.extend(column)
    return packed.tobytes()


def _projection_matrix(frame: CameraFrameData) -> bytes:
    near = max(1e-3, float(frame.near))
    far = max(near + 1.0, float(frame.far))
    f = 1.0 / float(frame.tan_half_fov)
    aspect = float(frame.aspect) if frame.aspect > 0.0 else 1.0
    proj_rows = (
        (f / aspect, 0.0, 0.0, 0.0),
        (0.0, f, 0.0, 0.0),
        (0.0, 0.0, (far + near) / (near - far), (2.0 * far * near) / (near - far)),
        (0.0, 0.0, -1.0, 0.0),
    )
    return _matrix_to_bytes(proj_rows)


def _view_matrix(frame: CameraFrameData) -> bytes:
    position = frame.position
    right = frame.right
    up = frame.up
    forward = frame.forward
    tx = -right.dot(position)
    ty = -up.dot(position)
    tz = -forward.dot(position)
    view_rows = (
        (right.x, right.y, right.z, tx),
        (up.x, up.y, up.z, ty),
        (forward.x, forward.y, forward.z, tz),
        (0.0, 0.0, 0.0, 1.0),
    )
    return _matrix_to_bytes(view_rows)


def _model_matrix(
    origin: Vector3,
    basis: Tuple[Vector3, Vector3, Vector3],
    scale: float,
) -> bytes:
    right, up, forward = basis
    scaled_right = right * scale
    scaled_up = up * scale
    scaled_forward = forward * scale
    model_rows = (
        (scaled_right.x, scaled_right.y, scaled_right.z, origin.x),
        (scaled_up.x, scaled_up.y, scaled_up.z, origin.y),
        (scaled_forward.x, scaled_forward.y, scaled_forward.z, origin.z),
        (0.0, 0.0, 0.0, 1.0),
    )
    return _matrix_to_bytes(model_rows)


class ModernGLShipRenderer:
    """Render ship wireframes using ModernGL when available."""

    def __init__(self) -> None:
        global _FALLBACK_LOGGED
        self._ctx: "moderngl.Context | None" = None
        self._program: "moderngl.Program | None" = None
        self._vao_cache: Dict[int, "moderngl.VertexArray"] = {}
        self._framebuffer: "moderngl.Framebuffer | None" = None
        self._framebuffer_size: tuple[int, int] = (0, 0)
        self._color_texture: "moderngl.Texture | None" = None
        self._supported = False
        if moderngl is None:
            if not _FALLBACK_LOGGED:
                LOGGER.warning("ModernGL is not available; falling back to CPU renderer")
                _FALLBACK_LOGGED = True
            return
        try:
            self._ctx = moderngl.create_standalone_context()
        except Exception as exc:  # pragma: no cover - context creation is platform specific
            if not _FALLBACK_LOGGED:
                LOGGER.warning("ModernGL context creation failed: %s", exc)
                _FALLBACK_LOGGED = True
            self._ctx = None
            return
        vertex_shader = """
            #version 330
            uniform mat4 projection;
            uniform mat4 view;
            uniform mat4 model;
            in vec3 in_position;
            void main() {
                gl_Position = projection * view * model * vec4(in_position, 1.0);
            }
        """
        fragment_shader = """
            #version 330
            uniform vec4 color;
            out vec4 fragColor;
            void main() {
                fragColor = color;
            }
        """
        try:
            self._program = self._ctx.program(
                vertex_shader=vertex_shader,
                fragment_shader=fragment_shader,
            )
        except Exception as exc:  # pragma: no cover - shader compilation failure
            if not _FALLBACK_LOGGED:
                LOGGER.warning("ModernGL shader compilation failed: %s", exc)
                _FALLBACK_LOGGED = True
            self._ctx = None
            return
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)
        self._supported = True

    def is_supported(self) -> bool:
        return self._supported and self._ctx is not None and self._program is not None

    def _ensure_framebuffer(self, size: tuple[int, int]) -> None:
        if not self.is_supported():
            return
        width, height = size
        if width <= 0 or height <= 0:
            return
        if self._framebuffer and size == self._framebuffer_size:
            return
        if self._framebuffer:
            self._framebuffer.release()
        if self._color_texture:
            self._color_texture.release()
        self._color_texture = self._ctx.texture(size, components=4)
        self._color_texture.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._framebuffer = self._ctx.framebuffer(color_attachments=[self._color_texture])
        self._framebuffer_size = size

    def _geometry_vao(self, geometry: "ShipGeometry") -> "moderngl.VertexArray | None":
        if not self.is_supported():
            return None
        key = id(geometry)
        cached = self._vao_cache.get(key)
        if cached:
            return cached
        vertex_data = array("f")
        for vertex in geometry.vertices:
            vertex_data.extend((vertex.x, vertex.y, vertex.z))
        index_data = array("I")
        for start, end in geometry.edges:
            index_data.extend((start, end))
        if not vertex_data or not index_data:
            return None
        vbo = self._ctx.buffer(vertex_data.tobytes())
        ibo = self._ctx.buffer(index_data.tobytes())
        vao = self._ctx.vertex_array(
            self._program,
            [(vbo, "3f", "in_position")],
            index_buffer=ibo,
            index_element_size=4,
        )
        self._vao_cache[key] = vao
        return vao

    def render_ship(
        self,
        surface: pygame.Surface,
        frame: CameraFrameData,
        geometry: "ShipGeometry",
        origin: Vector3,
        basis: Tuple[Vector3, Vector3, Vector3],
        *,
        scale: float,
        color: tuple[int, int, int],
        line_mode: str,
    ) -> bool:
        if not self.is_supported():
            return False
        vao = self._geometry_vao(geometry)
        if vao is None:
            return False
        size = surface.get_size()
        if size[0] <= 0 or size[1] <= 0:
            return False
        self._ensure_framebuffer(size)
        if self._framebuffer is None or self._color_texture is None:
            return False
        try:
            self._framebuffer.use()
            self._ctx.viewport = (0, 0, size[0], size[1])
            self._ctx.clear(0.0, 0.0, 0.0, 0.0)
            if line_mode == "line":
                self._ctx.line_width = 1.0
            else:
                self._ctx.line_width = 2.0
            assert self._program is not None
            self._program["projection"].write(_projection_matrix(frame))
            self._program["view"].write(_view_matrix(frame))
            self._program["model"].write(_model_matrix(origin, basis, scale))
            r, g, b = color
            self._program["color"].value = (r / 255.0, g / 255.0, b / 255.0, 1.0)
            vao.render(mode=moderngl.LINES)
            raw = self._framebuffer.read(components=4, alignment=1)
        except Exception as exc:  # pragma: no cover - GPU runtime failures are environment-specific
            LOGGER.debug("ModernGL render failed: %s", exc)
            return False
        temp_surface = pygame.image.frombuffer(raw, size, "RGBA")
        flipped = pygame.transform.flip(temp_surface, False, True)
        overlay = flipped.copy()
        surface.blit(overlay, (0, 0), special_flags=pygame.BLEND_PREMULTIPLIED)
        return True


__all__ = ["ModernGLShipRenderer"]

