"""Render frames headlessly (EGL) to PNG — for previews, docs and tuning.

    python -m galaxy.snapshot out.png [--layout single|dual] [--width 3840]
                                      [--time 120] [--vault PATH] [--search TEXT] [--hover N]

No window or compositor needed. Without a usable GPU, EGL falls back to Mesa's
software renderer: slower, same image.
"""

from __future__ import annotations

import argparse
import os
import time

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")

import ctypes  # noqa: E402

import numpy as np  # noqa: E402
from OpenGL import EGL  # noqa: E402
from OpenGL import GL as gl  # noqa: E402

from . import config  # noqa: E402
from .layout import LayoutCache, force_layout, to_disk  # noqa: E402
from .render import Renderer  # noqa: E402
from .scene import Rect, Scene  # noqa: E402
from .vault import build_graph  # noqa: E402


def egl_context():
    dpy = EGL.eglGetDisplay(EGL.EGL_DEFAULT_DISPLAY)
    major, minor = EGL.EGLint(), EGL.EGLint()
    EGL.eglInitialize(dpy, ctypes.pointer(major), ctypes.pointer(minor))
    attrs = (EGL.EGLint * 7)(EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT,
                             EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT, EGL.EGL_NONE, 0, 0)
    cfg = EGL.EGLConfig()
    num = EGL.EGLint()
    EGL.eglChooseConfig(dpy, attrs, ctypes.pointer(cfg), 1, ctypes.pointer(num))
    EGL.eglBindAPI(EGL.EGL_OPENGL_API)
    ctx_attrs = (EGL.EGLint * 7)(EGL.EGL_CONTEXT_MAJOR_VERSION, 3, EGL.EGL_CONTEXT_MINOR_VERSION, 3,
                                 EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
                                 EGL.EGL_NONE)
    ctx = EGL.eglCreateContext(dpy, cfg, EGL.EGL_NO_CONTEXT, ctx_attrs)
    EGL.eglMakeCurrent(dpy, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, ctx)
    return dpy, ctx


def load_scene(cfg, now=0.0) -> Scene:
    g = build_graph(cfg["vault"]["path"], cfg["vault"]["archive_prefix"])
    cache = LayoutCache(config.layout_cache_path(cfg["vault"]["path"]))
    init = cache.load()
    raw = force_layout(g, init)
    cache.save(g, raw)
    scene = Scene(cfg)
    scene.set_graph(g, to_disk(g, raw), now)
    return scene


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--layout", choices=["single", "dual"], default="single",
                    help="one 16:9 screen, or two side by side like a dual-monitor desktop")
    ap.add_argument("--width", type=int, default=3840, help="output width per screen in pixels")
    ap.add_argument("--time", type=float, default=60.0, help="animation time (rotation) in seconds")
    ap.add_argument("--vault", help="vault to render (default: config / bundled demo)")
    ap.add_argument("--hover", type=int, default=None, help="light up note N's constellation")
    ap.add_argument("--search", help="show the search highlight for this query")
    args = ap.parse_args()

    cfg = config.load()
    if args.vault:
        cfg["vault"]["path"] = os.path.abspath(os.path.expanduser(args.vault))
    scene = load_scene(cfg, now=-1000.0)
    if args.hover is not None:
        scene.set_hover(args.hover)
    if args.search:
        q = args.search.lower()
        scene.set_matches(np.array([q in t.lower() for t in scene.titles], np.float32))
        scene.search_dim = scene.search_dim_target
    scene.highlight[:] = scene.hl_target
    scene.highlight_version += 1

    egl_context()
    r = Renderer(scene, cfg)
    # logical monitors are 2560x1440 (like a 4K screen at 1.5x); dev scales to --width
    mons = [Rect(0, 0, 2560, 1440)] if args.layout == "single" else \
        [Rect(0, 0, 2560, 1440), Rect(2560, 0, 2560, 1440)]
    total = Rect(0, 0, 2560 * len(mons), 1440)
    dev = args.width / 2560
    parts = []
    for mon in mons:
        w, h = int(mon.w * dev), int(mon.h * dev)
        fbo = gl.glGenFramebuffers(1)
        tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, None)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
        gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_TEXTURE_2D, tex, 0)
        t0 = time.time()
        r.render(fbo, w, h, args.time, mon, total, dev)
        gl.glFinish()
        print(f"rendered {w}x{h} in {1000 * (time.time() - t0):.0f} ms "
              f"({gl.glGetString(gl.GL_RENDERER).decode()})")
        px = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        parts.append(np.frombuffer(px, np.uint8).reshape(h, w, 3)[::-1])
    img = np.ascontiguousarray(np.concatenate(parts, 1))

    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib
    hh, ww, _ = img.shape
    pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(img.tobytes()), GdkPixbuf.Colorspace.RGB,
                                         False, 8, ww, hh, ww * 3)
    fmt = "jpeg" if args.out.lower().endswith((".jpg", ".jpeg")) else "png"
    pb.savev(args.out, fmt, ["quality"] if fmt == "jpeg" else [], ["92"] if fmt == "jpeg" else [])
    print("wrote", args.out, ww, hh)


if __name__ == "__main__":
    main()
