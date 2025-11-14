"""Shared OpenGL utilities for the vector renderer."""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Optional, Sequence

try:  # pragma: no cover - fallback path only used without PyOpenGL
    from OpenGL import GL  # type: ignore
except ImportError:  # pragma: no cover
    class _MissingGL:
        def __getattr__(self, name: str):  # noqa: D401 - simple proxy
            raise RuntimeError(
                "PyOpenGL is required for the GPU renderer."
            )

    GL = _MissingGL()  # type: ignore


VERTEX_POSITION_ATTRIB = 0
VERTEX_TEXCOORD_ATTRIB = 1


def compile_shader(source: str, shader_type: int) -> int:
    shader = GL.glCreateShader(shader_type)
    GL.glShaderSource(shader, source)
    GL.glCompileShader(shader)
    if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
        log = GL.glGetShaderInfoLog(shader).decode("utf-8", "ignore")
        GL.glDeleteShader(shader)
        raise RuntimeError(f"Failed to compile shader: {log}")
    return shader


def link_program(vertex_shader_src: str, fragment_shader_src: str) -> int:
    vertex_shader = compile_shader(vertex_shader_src, GL.GL_VERTEX_SHADER)
    fragment_shader = compile_shader(fragment_shader_src, GL.GL_FRAGMENT_SHADER)
    program = GL.glCreateProgram()
    GL.glAttachShader(program, vertex_shader)
    GL.glAttachShader(program, fragment_shader)
    GL.glBindAttribLocation(program, VERTEX_POSITION_ATTRIB, "a_position")
    GL.glLinkProgram(program)
    GL.glDeleteShader(vertex_shader)
    GL.glDeleteShader(fragment_shader)
    if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
        log = GL.glGetProgramInfoLog(program).decode("utf-8", "ignore")
        GL.glDeleteProgram(program)
        raise RuntimeError(f"Failed to link shader program: {log}")
    return program


@dataclass
class LineProgram:
    program: int
    mvp_location: int
    color_location: int

    @classmethod
    def create(cls) -> "LineProgram":
        vertex_shader = """
            #version 330 core
            layout(location = 0) in vec3 a_position;
            uniform mat4 u_mvp;
            void main() {
                gl_Position = u_mvp * vec4(a_position, 1.0);
            }
        """
        fragment_shader = """
            #version 330 core
            uniform vec4 u_color;
            out vec4 frag_color;
            void main() {
                frag_color = u_color;
            }
        """
        program = link_program(vertex_shader, fragment_shader)
        mvp_location = GL.glGetUniformLocation(program, "u_mvp")
        color_location = GL.glGetUniformLocation(program, "u_color")
        return cls(program=program, mvp_location=mvp_location, color_location=color_location)


@dataclass
class TextureProgram:
    program: int
    texture_location: int

    @classmethod
    def create(cls) -> "TextureProgram":
        vertex_shader = """
            #version 330 core
            layout(location = 0) in vec2 a_position;
            layout(location = 1) in vec2 a_uv;
            out vec2 v_uv;
            void main() {
                v_uv = a_uv;
                gl_Position = vec4(a_position, 0.0, 1.0);
            }
        """
        fragment_shader = """
            #version 330 core
            uniform sampler2D u_texture;
            in vec2 v_uv;
            out vec4 frag_color;
            void main() {
                frag_color = texture(u_texture, v_uv);
            }
        """
        program = link_program(vertex_shader, fragment_shader)
        texture_location = GL.glGetUniformLocation(program, "u_texture")
        return cls(program=program, texture_location=texture_location)


class StaticVertexBuffer:
    """Wrapper for a static vertex buffer containing vec3 positions."""

    def __init__(self, vertices: Sequence[float]) -> None:
        data = array("f", vertices)
        self.count = len(data) // 3
        self.vbo = GL.glGenBuffers(1)
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER,
            len(data) * data.itemsize,
            data,
            GL.GL_STATIC_DRAW,
        )
        GL.glEnableVertexAttribArray(VERTEX_POSITION_ATTRIB)
        GL.glVertexAttribPointer(VERTEX_POSITION_ATTRIB, 3, GL.GL_FLOAT, False, 12, None)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

    def draw(self) -> None:
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, self.count)
        GL.glBindVertexArray(0)

    def release(self) -> None:
        if getattr(self, "vao", 0):
            GL.glDeleteVertexArrays(1, [self.vao])
            self.vao = 0
        if getattr(self, "vbo", 0):
            GL.glDeleteBuffers(1, [self.vbo])
            self.vbo = 0


class DynamicLineBuffer:
    """Utility for drawing transient line lists."""

    def __init__(self, initial_capacity: int = 256) -> None:
        self._capacity = max(1, initial_capacity)
        self._vbo = GL.glGenBuffers(1)
        self._vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER,
            self._capacity * 3 * 4,
            None,
            GL.GL_DYNAMIC_DRAW,
        )
        GL.glEnableVertexAttribArray(VERTEX_POSITION_ATTRIB)
        GL.glVertexAttribPointer(VERTEX_POSITION_ATTRIB, 3, GL.GL_FLOAT, False, 12, None)
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self._count = 0

    def update(self, vertices: Sequence[float]) -> None:
        data = array("f", vertices)
        count = len(data) // 3
        if count > self._capacity:
            self._capacity = count
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferData(
                GL.GL_ARRAY_BUFFER,
                len(data) * data.itemsize,
                data,
                GL.GL_DYNAMIC_DRAW,
            )
        else:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
            GL.glBufferSubData(
                GL.GL_ARRAY_BUFFER,
                0,
                len(data) * data.itemsize,
                data,
            )
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)
        self._count = count

    def draw(self) -> None:
        if self._count <= 0:
            return
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_LINES, 0, self._count)
        GL.glBindVertexArray(0)

    def release(self) -> None:
        if getattr(self, "_vao", 0):
            GL.glDeleteVertexArrays(1, [self._vao])
            self._vao = 0
        if getattr(self, "_vbo", 0):
            GL.glDeleteBuffers(1, [self._vbo])
            self._vbo = 0
        self._count = 0


def ensure_default_state() -> None:
    GL.glEnable(GL.GL_BLEND)
    GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
    GL.glDisable(GL.GL_DEPTH_TEST)
    GL.glLineWidth(1.5)


def perspective_matrix(fov_factor: float, aspect: float, near: float, far: float) -> list[list[float]]:
    f = fov_factor
    nf = 1.0 / (near - far)
    return [
        [f / max(aspect, 1e-6), 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far + near) * nf, 2.0 * far * near * nf],
        [0.0, 0.0, -1.0, 0.0],
    ]


def view_matrix(position, right, up, forward) -> list[list[float]]:
    px, py, pz = position.x, position.y, position.z
    rx, ry, rz = right.x, right.y, right.z
    ux, uy, uz = up.x, up.y, up.z
    fx, fy, fz = forward.x, forward.y, forward.z
    return [
        [rx, ux, -fx, 0.0],
        [ry, uy, -fy, 0.0],
        [rz, uz, -fz, 0.0],
        [-(rx * px + ry * py + rz * pz), -(ux * px + uy * py + uz * pz), fx * px + fy * py + fz * pz, 1.0],
    ]


def model_matrix(origin, right, up, forward, scale: float) -> list[list[float]]:
    rx, ry, rz = right.x * scale, right.y * scale, right.z * scale
    ux, uy, uz = up.x * scale, up.y * scale, up.z * scale
    fx, fy, fz = forward.x * scale, forward.y * scale, forward.z * scale
    ox, oy, oz = origin.x, origin.y, origin.z
    return [
        [rx, ux, -fx, 0.0],
        [ry, uy, -fy, 0.0],
        [rz, uz, -fz, 0.0],
        [ox, oy, oz, 1.0],
    ]


def _mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    result = [[0.0 for _ in range(4)] for _ in range(4)]
    for i in range(4):
        for j in range(4):
            total = 0.0
            for k in range(4):
                total += a[i][k] * b[k][j]
            result[i][j] = total
    return result


def multiply_matrices(*matrices: list[list[float]]) -> list[list[float]]:
    result: Optional[list[list[float]]] = None
    for matrix in matrices:
        if result is None:
            result = matrix
        else:
            result = _mat_mul(result, matrix)
    if result is None:
        raise ValueError("No matrices provided for multiplication")
    return result


def flatten_matrix(matrix: list[list[float]]) -> array:
    return array("f", [component for row in matrix for component in row])
