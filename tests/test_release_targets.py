"""Pausing frees the full-screen render targets, and drawing again rebuilds them
without changing the picture.

    python -m unittest discover tests

Runs headlessly through EGL, like galaxy.snapshot.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import numpy as np  # noqa: E402
from OpenGL import GL as gl  # noqa: E402

from galaxy import config  # noqa: E402
from galaxy.layout import force_layout, to_disk  # noqa: E402
from galaxy.render import Renderer  # noqa: E402
from galaxy.scene import Rect, Scene  # noqa: E402
from galaxy.snapshot import egl_context  # noqa: E402
from galaxy.vault import build_graph  # noqa: E402

DEMO_VAULT = os.path.join(os.path.dirname(__file__), "..", "demo-vault")
W, H = 640, 360


class ReleaseTargetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        egl_context()
        # defaults only: never read the user's config or touch their layout cache
        cfg = config.load(os.devnull)
        cfg["vault"]["path"] = os.path.abspath(DEMO_VAULT)
        g = build_graph(cfg["vault"]["path"], cfg["vault"]["archive_prefix"])
        scene = Scene(cfg)
        scene.set_graph(g, to_disk(g, force_layout(g)), -1000.0)
        cls.renderer = Renderer(scene, cfg)
        cls.fbo = gl.glGenFramebuffers(1)
        cls.out = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, cls.out)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, W, H, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, cls.fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, cls.out, 0)

    def frame(self) -> np.ndarray:
        mon = Rect(0, 0, W, H)
        self.renderer.render(self.fbo, W, H, 60.0, mon, mon, 1.0)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self.fbo)
        px = gl.glReadPixels(0, 0, W, H, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        return np.frombuffer(px, np.uint8).copy()

    def target_textures(self) -> list[int]:
        r = self.renderer
        return [t.tex for t in (r.hdr, r.lines, r.soft, r.bg, *r.mips)]

    def test_release_frees_textures_and_render_rebuilds_them(self):
        before = self.frame()
        self.assertGreater(before.max(), 0, "first frame rendered nothing")
        textures = self.target_textures()
        self.assertTrue(all(gl.glIsTexture(t) for t in textures))

        self.renderer.release_targets()
        self.assertIsNone(self.renderer.hdr)
        self.assertEqual(self.renderer.mips, [])
        self.assertFalse(any(gl.glIsTexture(t) for t in textures), "a target texture was not deleted")

        after = self.frame()
        self.assertIsNotNone(self.renderer.hdr)
        self.assertTrue(all(gl.glIsTexture(t) for t in self.target_textures()))
        np.testing.assert_array_equal(before, after)

    def test_release_twice_is_harmless(self):
        self.frame()
        self.renderer.release_targets()
        self.renderer.release_targets()
        self.assertIsNone(self.renderer.hdr)


if __name__ == "__main__":
    unittest.main()
