"""OpenGL renderer: one instance per GL context (i.e. per monitor)."""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL as gl

from . import glsl
from .scene import TEXW, Rect, Scene

BLOOM_LEVELS = 7


def _compile(vs: str, fs: str) -> int:
    def sh(src, kind):
        s = gl.glCreateShader(kind)
        gl.glShaderSource(s, src)
        gl.glCompileShader(s)
        if not gl.glGetShaderiv(s, gl.GL_COMPILE_STATUS):
            raise RuntimeError(gl.glGetShaderInfoLog(s).decode())
        return s

    p = gl.glCreateProgram()
    v, f = sh(vs, gl.GL_VERTEX_SHADER), sh(fs, gl.GL_FRAGMENT_SHADER)
    gl.glAttachShader(p, v)
    gl.glAttachShader(p, f)
    gl.glLinkProgram(p)
    if not gl.glGetProgramiv(p, gl.GL_LINK_STATUS):
        raise RuntimeError(gl.glGetProgramInfoLog(p).decode())
    gl.glDeleteShader(v)
    gl.glDeleteShader(f)
    return p


class Program:
    def __init__(self, vs, fs):
        self.id = _compile(vs, fs)
        self._loc: dict[str, int] = {}

    def loc(self, name):
        if name not in self._loc:
            self._loc[name] = gl.glGetUniformLocation(self.id, name)
        return self._loc[name]

    def use(self):
        gl.glUseProgram(self.id)

    def f(self, name, *v):
        [gl.glUniform1f, gl.glUniform2f, gl.glUniform3f, gl.glUniform4f][len(v) - 1](self.loc(name), *v)

    def i(self, name, v):
        gl.glUniform1i(self.loc(name), v)

    def m4(self, name, m):
        gl.glUniformMatrix4fv(self.loc(name), 1, gl.GL_TRUE, np.ascontiguousarray(m, np.float32))


def _tex2d(w, h, ifmt, fmt, typ, data=None, filt=gl.GL_LINEAR):
    t = gl.glGenTextures(1)
    gl.glBindTexture(gl.GL_TEXTURE_2D, t)
    gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, ifmt, w, h, 0, fmt, typ, data)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, filt)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, filt)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
    gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
    return t


class Target:
    """An RGBA16F colour target."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.tex = _tex2d(w, h, gl.GL_RGBA16F, gl.GL_RGBA, gl.GL_HALF_FLOAT)
        self.fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, self.tex, 0)

    def delete(self):
        gl.glDeleteFramebuffers(1, [self.fbo])
        gl.glDeleteTextures(1, [self.tex])


def _node_tex_data(arr: np.ndarray, channels: int) -> tuple[np.ndarray, int]:
    n = len(arr)
    rows = max(1, (n + TEXW - 1) // TEXW)
    out = np.zeros((rows * TEXW, channels), np.float32)
    out[:n] = arr[:, :channels]
    return out, rows


class Renderer:
    def __init__(self, scene: Scene, cfg: dict):
        self.scene = scene
        self.cfg = cfg
        self.star = Program(glsl.STAR_VS, glsl.STAR_FS)
        self.line = Program(glsl.LINE_VS, glsl.LINE_FS)
        self.dust = Program(glsl.DUST_VS, glsl.DUST_FS)
        self.sky = Program(glsl.SKY_VS, glsl.SKY_FS)
        self.down = Program(glsl.FULLSCREEN_VS, glsl.DOWN_FS)
        self.up = Program(glsl.FULLSCREEN_VS, glsl.UP_FS)
        self.comp = Program(glsl.FULLSCREEN_VS, glsl.COMPOSITE_FS)
        self.blit = Program(glsl.FULLSCREEN_VS, glsl.BLIT_FS)
        self.bgp = Program(glsl.FULLSCREEN_VS, glsl.BG_FS)

        self.empty_vao = gl.glGenVertexArrays(1)
        self.star_vao = gl.glGenVertexArrays(1)
        self.line_vao = gl.glGenVertexArrays(1)
        self.dust_vao = gl.glGenVertexArrays(1)
        self.sky_vao = gl.glGenVertexArrays(1)
        self.buffers: list[int] = []
        self.pos_from_tex = self.pos_to_tex = self.hl_tex = None
        self.geometry_version = -1
        self.highlight_version = -1
        self.size = (0, 0)
        self.hdr: Target | None = None
        self.mips: list[Target] = []
        self._upload_sky()

    # -------------------------------------------------------------- uploads

    def _vbo(self, data: np.ndarray) -> int:
        b = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, b)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, np.ascontiguousarray(data, np.float32), gl.GL_STATIC_DRAW)
        self.buffers.append(b)
        return b

    def _attr(self, loc, data, comps, divisor=0):
        self._vbo(data)
        gl.glEnableVertexAttribArray(loc)
        gl.glVertexAttribPointer(loc, comps, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        if divisor:
            gl.glVertexAttribDivisor(loc, divisor)

    def _upload_sky(self):
        gl.glBindVertexArray(self.sky_vao)
        b = gl.glGenBuffers(1)
        for loc, data, comps in ((0, self.scene.sky_dir, 3), (1, self.scene.sky_color, 4)):
            b = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, b)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data, gl.GL_STATIC_DRAW)
            gl.glEnableVertexAttribArray(loc)
            gl.glVertexAttribPointer(loc, comps, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        gl.glBindVertexArray(0)

    def _upload_geometry(self):
        s = self.scene
        if self.buffers:
            gl.glDeleteBuffers(len(self.buffers), self.buffers)
            self.buffers = []
        for t in (self.pos_from_tex, self.pos_to_tex):
            if t:
                gl.glDeleteTextures(1, [t])

        pf, rows = _node_tex_data(s.pos_from, 4)
        pt, _ = _node_tex_data(s.pos_to, 4)
        self.pos_from_tex = _tex2d(TEXW, rows, gl.GL_RGBA32F, gl.GL_RGBA, gl.GL_FLOAT, pf, gl.GL_NEAREST)
        self.pos_to_tex = _tex2d(TEXW, rows, gl.GL_RGBA32F, gl.GL_RGBA, gl.GL_FLOAT, pt, gl.GL_NEAREST)
        self.tex_rows = rows

        gl.glBindVertexArray(self.star_vao)
        self._attr(0, s.star_color, 4)
        self._attr(1, s.star_meta, 4)

        gl.glBindVertexArray(self.line_vao)
        self._attr(0, s.edges, 2, divisor=1)
        self._attr(1, s.edge_weight, 1, divisor=1)

        gl.glBindVertexArray(self.dust_vao)
        self._attr(0, s.dust_pos, 4)
        self._attr(1, s.dust_color, 4)
        self._attr(2, s.dust_size, 1)
        gl.glBindVertexArray(0)

        self.geometry_version = s.geometry_version
        self.highlight_version = -1

    def _upload_highlight(self):
        s = self.scene
        data, rows = _node_tex_data(np.column_stack([s.highlight, np.zeros((s.n, 1))]) if s.n else np.zeros((0, 4)), 4)
        if self.hl_tex is None or getattr(self, "hl_rows", 0) != rows:
            if self.hl_tex:
                gl.glDeleteTextures(1, [self.hl_tex])
            self.hl_tex = _tex2d(TEXW, rows, gl.GL_RGBA32F, gl.GL_RGBA, gl.GL_FLOAT, data, gl.GL_NEAREST)
            self.hl_rows = rows
        else:
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.hl_tex)
            gl.glTexSubImage2D(gl.GL_TEXTURE_2D, 0, 0, 0, TEXW, rows, gl.GL_RGBA, gl.GL_FLOAT, data)
        self.highlight_version = s.highlight_version

    def _resize(self, w, h):
        if self.hdr:
            for t in (self.hdr, self.lines, self.soft, self.bg):
                t.delete()
        for m in self.mips:
            m.delete()
        self.hdr = Target(w, h)
        self.lines = Target(w, h)
        self.soft = Target(max(1, w // 2), max(1, h // 2))
        self.bg = Target(max(1, w // 8), max(1, h // 8))
        self.mips = []
        mw, mh = w, h
        for _ in range(BLOOM_LEVELS):
            mw, mh = max(1, mw // 2), max(1, mh // 2)
            self.mips.append(Target(mw, mh))
        self.size = (w, h)

    # -------------------------------------------------------------- frame

    def render(self, out_fbo: int, w: int, h: int, t: float, mon: Rect, total: Rect, dev_scale: float):
        s = self.scene
        # overscan so bloom sees light from just past the screen edge; this
        # keeps the seam between monitors continuous
        margin = int(h * 0.06)
        W, H = w + 2 * margin, h + 2 * margin
        ml = margin / dev_scale
        ext = Rect(mon.x - ml, mon.y - ml, mon.w + 2 * ml, mon.h + 2 * ml)
        if (W, H) != self.size:
            self._resize(W, H)
        if s.geometry_version != self.geometry_version:
            self._upload_geometry()
        if s.highlight_version != self.highlight_version:
            self._upload_highlight()

        v = s.camera.view(t, ext, total)
        mix = s.mix(t)
        px_scale = h / 2160.0
        r = self.cfg["render"]

        # the host toolkit may leave its own state behind
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glDisable(gl.GL_FRAMEBUFFER_SRGB)
        gl.glColorMask(True, True, True, True)
        gl.glUseProgram(0)

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.hdr.fbo)
        gl.glViewport(0, 0, W, H)
        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
        gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)

        # background sky
        self.sky.use()
        self.sky.m4("uSkyViewProj", v.sky_view_proj)
        self.sky.f("uPxScale", px_scale)
        gl.glBindVertexArray(self.sky_vao)
        gl.glDrawArrays(gl.GL_POINTS, 0, len(s.sky_dir))

        if s.n:
            gl.glActiveTexture(gl.GL_TEXTURE0)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.pos_from_tex)
            gl.glActiveTexture(gl.GL_TEXTURE1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.pos_to_tex)
            gl.glActiveTexture(gl.GL_TEXTURE2)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.hl_tex)

            def common(p: Program):
                p.use()
                p.i("uPosFrom", 0)
                p.i("uPosTo", 1)
                p.i("uHighlight", 2)
                p.f("uMix", mix)
                p.m4("uModel", v.model)
                p.m4("uViewProj", v.view_proj)
                p.f("uCamPos", *v.cam_pos)
                p.f("uViewport", float(W), float(H))
                p.f("uPxScale", px_scale)
                p.f("uRefDist", self.cfg["camera"]["distance"])
                p.f("uTime", t)
                p.f("uSearchDim", s.search_dim)

            # soft dust (haze, clouds) at half resolution: it has no fine
            # detail, and it's the bulk of the fill cost
            common(self.dust)
            self.dust.f("uDiff", r["dust_differential"])
            gl.glBindVertexArray(self.dust_vao)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.soft.fbo)
            gl.glViewport(0, 0, self.soft.w, self.soft.h)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            self.dust.f("uPxScale", px_scale * self.soft.h / H)
            gl.glDrawArrays(gl.GL_POINTS, 0, s.dust_soft_count)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.hdr.fbo)
            gl.glViewport(0, 0, W, H)
            self.dust.f("uPxScale", px_scale)
            gl.glDrawArrays(gl.GL_POINTS, s.dust_soft_count, len(s.dust_pos) - s.dust_soft_count)
            self.blit.use()
            self.blit.i("uSrc", 3)
            gl.glActiveTexture(gl.GL_TEXTURE3)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.soft.tex)
            gl.glBindVertexArray(self.empty_vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            gl.glActiveTexture(gl.GL_TEXTURE0)

            if len(s.edges):
                common(self.line)
                self.line.f("uLineWidth", r["line_width"])
                self.line.f("uLineBase", r["line_intensity"])
                self.line.f("uLineHover", r["line_hover_intensity"])
                self.line.f("uLineColor", *r["line_color"])
                self.line.f("uLineHoverColor", *r["line_hover_color"])
                # max-blend into their own layer: stacked links never add up
                # into bright beams, the web stays a uniformly faint trace
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.lines.fbo)
                gl.glClear(gl.GL_COLOR_BUFFER_BIT)
                gl.glBlendEquation(gl.GL_MAX)
                gl.glBindVertexArray(self.line_vao)
                gl.glDrawArraysInstanced(gl.GL_TRIANGLE_STRIP, 0, 4, len(s.edges))
                gl.glBlendEquation(gl.GL_FUNC_ADD)
                gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.hdr.fbo)
                self.blit.use()
                self.blit.i("uSrc", 3)
                gl.glActiveTexture(gl.GL_TEXTURE3)
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.lines.tex)
                gl.glBindVertexArray(self.empty_vao)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
                gl.glActiveTexture(gl.GL_TEXTURE0)

            common(self.star)
            gl.glBindVertexArray(self.star_vao)
            gl.glDrawArrays(gl.GL_POINTS, 0, s.n)

        # bloom: progressive downsample, then tent upsample back up the chain
        gl.glDisable(gl.GL_BLEND)
        gl.glBindVertexArray(self.empty_vao)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        self.down.use()
        self.down.i("uSrc", 0)
        src = self.hdr
        for k, m in enumerate(self.mips):
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, m.fbo)
            gl.glViewport(0, 0, m.w, m.h)
            gl.glBindTexture(gl.GL_TEXTURE_2D, src.tex)
            self.down.f("uTexel", 1.0 / src.w, 1.0 / src.h)
            self.down.i("uKaris", 1 if k == 0 else 0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
            src = m

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
        self.up.use()
        self.up.i("uSrc", 0)
        self.up.f("uRadius", 1.0)
        weights = r["bloom_level_weights"]
        for k in range(len(self.mips) - 1, 0, -1):
            src, dst = self.mips[k], self.mips[k - 1]
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, dst.fbo)
            gl.glViewport(0, 0, dst.w, dst.h)
            gl.glBindTexture(gl.GL_TEXTURE_2D, src.tex)
            self.up.f("uTexel", 1.0 / src.w, 1.0 / src.h)
            self.up.f("uWeight", weights[min(k, len(weights) - 1)])
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glDisable(gl.GL_BLEND)

        # deep-sky background at 1/8 resolution
        self.bgp.use()
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.bg.fbo)
        gl.glViewport(0, 0, self.bg.w, self.bg.h)
        self.bgp.m4("uInvSky", np.linalg.inv(v.sky_view_proj))
        cx, cy = v.core_frac
        self.bgp.f("uGalaxyCenter", cx, 1.0 - cy)  # shader's desktop coords are y-up
        self.bgp.f("uBgGlow", self.cfg["background"]["glow"])
        self.bgp.f("uBgNebula", self.cfg["background"]["nebula"])
        self.bgp.f("uScreenTotal", total.w * dev_scale, total.h * dev_scale)
        self.bgp.f("uExtOrigin", (ext.x - total.x) * dev_scale, (ext.y - total.y) * dev_scale)
        self.bgp.f("uExtSize", float(W), float(H))
        gl.glBindVertexArray(self.empty_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        # composite + tonemap into the caller's framebuffer
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, out_fbo)
        gl.glViewport(0, 0, w, h)
        self.comp.use()
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.hdr.tex)
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.mips[0].tex)
        self.comp.i("uHdr", 0)
        self.comp.i("uBloom", 1)
        self.comp.f("uBloomStrength", r["bloom_strength"])
        self.comp.f("uExposure", r["exposure"])
        self.comp.f("uTime", t)
        self.comp.f("uViewport", float(w), float(h))
        self.comp.f("uUVScale", w / W, h / H)
        self.comp.f("uUVOffset", margin / W, margin / H)
        gl.glActiveTexture(gl.GL_TEXTURE2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.bg.tex)
        self.comp.i("uBg", 2)
        self.comp.f("uScreenOrigin", (mon.x - total.x) * dev_scale, (mon.y - total.y) * dev_scale)
        self.comp.f("uScreenTotal", total.w * dev_scale, total.h * dev_scale)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
