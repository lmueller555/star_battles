"""Helpers for compositing pygame UI surfaces over the OpenGL scene."""
from __future__ import annotations

import ctypes
from array import array
from typing import Tuple

import pygame

try:  # pragma: no cover - fallback path only used without PyOpenGL
    from OpenGL import GL  # type: ignore
except ImportError:  # pragma: no cover
    class _MissingGL:
        def __getattr__(self, name: str):
            raise RuntimeError(
                "PyOpenGL is required for the GPU renderer."
            )

    GL = _MissingGL()  # type: ignore

from .gl_backend import TextureProgram, VERTEX_POSITION_ATTRIB, VERTEX_TEXCOORD_ATTRIB


class UISurfaceOverlay:
    """Upload a pygame surface to a texture and draw it as a screen overlay."""

    def __init__(self) -> None:
        self._program = TextureProgram.create()
        self._vao = GL.glGenVertexArrays(1)
        self._vbo = GL.glGenBuffers(1)
        vertices = array(
            "f",
            [
                -1.0,
                -1.0,
                0.0,
                0.0,
                1.0,
                -1.0,
                1.0,
                0.0,
                -1.0,
                1.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ],
        )
        stride = 16
        GL.glBindVertexArray(self._vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._vbo)
        GL.glBufferData(
            GL.GL_ARRAY_BUFFER,
            len(vertices) * vertices.itemsize,
            vertices,
            GL.GL_STATIC_DRAW,
        )
        GL.glEnableVertexAttribArray(VERTEX_POSITION_ATTRIB)
        GL.glVertexAttribPointer(
            VERTEX_POSITION_ATTRIB,
            2,
            GL.GL_FLOAT,
            False,
            stride,
            ctypes.c_void_p(0),
        )
        GL.glEnableVertexAttribArray(VERTEX_TEXCOORD_ATTRIB)
        GL.glVertexAttribPointer(
            VERTEX_TEXCOORD_ATTRIB,
            2,
            GL.GL_FLOAT,
            False,
            stride,
            ctypes.c_void_p(8),
        )
        GL.glBindVertexArray(0)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, 0)

        self._texture = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_CLAMP_TO_EDGE)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_CLAMP_TO_EDGE)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
        self._size: Tuple[int, int] = (0, 0)

    def update(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        data = pygame.image.tostring(surface, "RGBA", True)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        if (width, height) != self._size:
            GL.glTexImage2D(
                GL.GL_TEXTURE_2D,
                0,
                GL.GL_RGBA,
                width,
                height,
                0,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                data,
            )
            self._size = (width, height)
        else:
            GL.glTexSubImage2D(
                GL.GL_TEXTURE_2D,
                0,
                0,
                0,
                width,
                height,
                GL.GL_RGBA,
                GL.GL_UNSIGNED_BYTE,
                data,
            )
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def draw(self) -> None:
        if self._size == (0, 0):
            return
        GL.glUseProgram(self._program.program)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._texture)
        GL.glUniform1i(self._program.texture_location, 0)
        GL.glBindVertexArray(self._vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glBindVertexArray(0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, 0)

    def release(self) -> None:
        if getattr(self, "_vao", 0):
            GL.glDeleteVertexArrays(1, [self._vao])
            self._vao = 0
        if getattr(self, "_vbo", 0):
            GL.glDeleteBuffers(1, [self._vbo])
            self._vbo = 0
        if getattr(self, "_texture", 0):
            GL.glDeleteTextures(1, [self._texture])
            self._texture = 0
