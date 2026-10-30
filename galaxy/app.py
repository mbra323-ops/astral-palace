"""Live wallpaper: one layer-shell surface per monitor, one shared galaxy."""

from __future__ import annotations

import ctypes
import json
import re
import math
import os
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import quote

os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
import OpenGL  # noqa: E402

OpenGL.ERROR_CHECKING = os.environ.get("GALAXY_GL_DEBUG") == "1"

import gi  # noqa: E402
import numpy as np  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402
from OpenGL import GL as gl  # noqa: E402

from . import config  # noqa: E402
from .layout import LayoutCache, force_layout, to_disk  # noqa: E402
from .render import Renderer  # noqa: E402
from .scene import Rect, Scene  # noqa: E402
from .vault import build_graph  # noqa: E402

CSS = b"""
window.galaxy { background: black; }
.label-root { opacity: 0; transition: opacity 260ms ease-out; }
.label-root.shown { opacity: 1; }
.hairline { min-height: 1px; min-width: 34px; margin-top: 11px;
            background: linear-gradient(to right, rgba(255,214,170,0), rgba(255,214,170,0.75)); }
.hairline.flip { background: linear-gradient(to left, rgba(255,214,170,0), rgba(255,214,170,0.75)); }
.title { font-family: "Noto Sans"; font-weight: 300; font-size: 15px; letter-spacing: 1.2px;
         color: rgba(255,244,230,0.96); text-shadow: 0 0 10px rgba(255,160,70,0.55); }
.meta { font-family: "Noto Sans"; font-weight: 400; font-size: 9.5px; letter-spacing: 2.6px;
        color: rgba(255,200,150,0.55); margin-top: 2px; }

/* search bar */
.search-root { opacity: 0; transition: opacity 200ms ease-out; }
.search-root.shown { opacity: 1; }
entry.search-entry { background: rgba(13,15,22,0.80); color: #f3ede3; border: none; border-radius: 0;
        border-bottom: 1px solid rgba(216,184,144,0.6); box-shadow: none; outline: none;
        padding: 12px 20px; min-height: 30px; caret-color: #f0b871;
        font-family: "Noto Sans"; font-weight: 300; font-size: 22px; letter-spacing: 1px; }
entry.search-entry:focus-within { outline: none; box-shadow: none; }
entry.search-entry > text > placeholder { color: rgba(228,225,219,0.32); }
.search-results { background: rgba(13,15,22,0.74); padding: 4px 0; }
.search-row { padding: 7px 20px 7px 18px; border-left: 2px solid transparent; }
.search-row.selected { background: rgba(216,184,144,0.10); border-left-color: #d8b890; }
.r-title { font-family: "Noto Sans"; font-size: 15px; color: rgba(244,238,228,0.95); }
.r-meta { font-family: "Noto Sans"; font-size: 9.5px; letter-spacing: 2.2px; color: rgba(255,200,150,0.5); }
.search-count { font-family: "Noto Sans"; font-size: 10px; letter-spacing: 2.6px;
        color: rgba(216,184,144,0.65); padding: 7px 4px; }
"""


APP_ID = "dev.astralpalace.AstralPalace"   # also the D-Bus name used by bin/astral-palace-search


ON_HYPRLAND = bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


def main_thread(fn, *args):
    """Run fn on the GTK main loop. Default priority: the render loop starves idle sources."""
    GLib.idle_add(fn, *args, priority=GLib.PRIORITY_DEFAULT)


ORIG_PREFIX = "GALAXY_ORIG_"
UNSET = "__unset__"
# env vars the launcher changes for this process only; children must not inherit
# them (LD_PRELOAD of gtk4-layer-shell drags GTK4 into GTK3 apps like Electron)
OVERRIDDEN = ("LD_PRELOAD", "GDK_SCALE", "GDK_DISABLE", "PYOPENGL_PLATFORM", "PYTHONPATH")


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith(ORIG_PREFIX)]:
        name, val = key[len(ORIG_PREFIX):], env.pop(key)
        if val == UNSET:
            env.pop(name, None)
        else:
            env[name] = val
    return env


def die_with_parent():
    """Child-side: get SIGTERM when the wallpaper exits, so watchers never orphan."""
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, 15)


def spawn(argv: list[str]) -> subprocess.Popen:
    return subprocess.Popen(argv, env=child_env(), start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def log(*a):
    print("[galaxy]", *a, file=sys.stderr, flush=True)


# ------------------------------------------------------------------ hyprland

def hypr(*args) -> object:
    out = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, timeout=2, env=child_env()).stdout
    return json.loads(out)


def covered_monitors() -> set[str]:
    """Monitors whose visible workspace is filled by tiled or fullscreen windows."""
    try:
        mons = hypr("monitors")
        clients = hypr("clients")
    except Exception as e:  # noqa: BLE001
        log("hyprctl failed:", e)
        return set()
    covered = set()
    for m in mons:
        ws_ids = {m["activeWorkspace"]["id"]}
        special = m.get("specialWorkspace", {}).get("id", 0)
        if special:
            ws_ids.add(special)
        for c in clients:
            if c["workspace"]["id"] not in ws_ids or not c.get("mapped", True) or c.get("hidden"):
                continue
            if c.get("fullscreen") or not c.get("floating"):
                covered.add(m["name"])
                break
    return covered


class HyprEvents(threading.Thread):
    WATCH = ("workspace", "focusedmon", "openwindow", "closewindow", "movewindow",
             "changefloatingmode", "fullscreen", "activespecial", "monitoradded", "monitorremoved")

    def __init__(self, callback):
        super().__init__(daemon=True)
        self.callback = callback

    def run(self):
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        rt = os.environ.get("XDG_RUNTIME_DIR", "")
        path = os.path.join(rt, "hypr", sig or "", ".socket2.sock")
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.connect(path)
                    buf = b""
                    while chunk := s.recv(4096):
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        if any(ln.split(b">>")[0].decode(errors="ignore") in self.WATCH for ln in lines):
                            main_thread(self.callback)
            except OSError as e:
                log("hypr socket:", e)
            time.sleep(2)


# ------------------------------------------------------------------ vault

class VaultWatcher(threading.Thread):
    def __init__(self, vault: str, callback):
        super().__init__(daemon=True)
        self.vault, self.callback = vault, callback

    def run(self):
        cmd = ["inotifywait", "-m", "-r", "-q", "-e", "close_write,create,delete,move",
               "--format", "%w%f", "--exclude", r"/\.(obsidian|git|trash)/", self.vault]
        while True:
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, env=child_env(),
                                     preexec_fn=die_with_parent)
                for line in p.stdout:
                    if line.strip().endswith(".md") or not line.strip().rsplit("/", 1)[-1].count("."):
                        main_thread(self.callback)
            except OSError as e:
                log("inotifywait:", e)
            time.sleep(5)


# ------------------------------------------------------------------ surfaces

class MonitorSurface:
    def __init__(self, app: "GalaxyApp", monitor: Gdk.Monitor):
        self.app = app
        self.monitor = monitor
        self.name = monitor.get_connector() or "?"
        self.renderer: Renderer | None = None
        self.px = (1, 1)
        self.tick_id = 0
        self.pointer: tuple[float, float] | None = None
        self.hovered: int | None = None
        self.last_pick = 0.0
        self.last_slot = -1

        win = Gtk.Window(application=app.gtk)
        win.add_css_class("galaxy")
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "astral-palace")
        layer = {"background": LayerShell.Layer.BACKGROUND, "bottom": LayerShell.Layer.BOTTOM}
        LayerShell.set_layer(win, layer.get(app.cfg["behaviour"]["layer"], LayerShell.Layer.BOTTOM))
        LayerShell.set_monitor(win, monitor)
        for edge in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM, LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, edge, True)
        LayerShell.set_exclusive_zone(win, -1)
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

        overlay = Gtk.Overlay()
        self.area = Gtk.GLArea()
        self.area.set_allowed_apis(Gdk.GLAPI.GL)
        self.area.set_required_version(3, 3)
        self.area.set_auto_render(False)
        self.area.connect("realize", self.on_realize)
        self.area.connect("unrealize", self.on_unrealize)
        self.area.connect("resize", self.on_resize)
        self.area.connect("render", self.on_render)
        overlay.set_child(self.area)

        # hover label: hairline + title + meta
        self.fixed = Gtk.Fixed()
        self.fixed.set_can_target(False)
        self.label = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.label.add_css_class("label-root")
        self.hair = Gtk.Box()
        self.hair.add_css_class("hairline")
        self.hair.set_valign(Gtk.Align.START)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("title")
        self.meta = Gtk.Label(xalign=0)
        self.meta.add_css_class("meta")
        text.append(self.title)
        text.append(self.meta)
        self.text = text
        self.label.append(self.hair)
        self.label.append(text)
        self.fixed.put(self.label, -1000, -1000)
        self.flipped = False
        overlay.add_overlay(self.fixed)
        self.build_search(overlay)
        win.set_child(overlay)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_window_key)
        win.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda _c, x, y: self.on_motion(x, y))
        motion.connect("leave", lambda _c: self.on_motion(None, None))
        overlay.add_controller(motion)
        click = Gtk.GestureClick(button=1)
        click.connect("released", self.on_click)
        overlay.add_controller(click)
        # drag on empty space slides the whole galaxy; Wayland's implicit grab
        # keeps the drag on this surface even when the pointer crosses monitors
        drag = Gtk.GestureDrag(button=1)
        drag.connect("drag-begin", self.on_drag_begin)
        drag.connect("drag-update", self.on_drag_update)
        drag.connect("drag-end", self.on_drag_end)
        overlay.add_controller(drag)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.on_scroll)
        overlay.add_controller(scroll)
        self.drag_star = None
        self.drag_origin = None
        self.dragging = False
        self.just_dragged = False

        self.win = win
        win.present()

    # search ----------------------------------------------------------
    def build_search(self, overlay):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("search-root")
        root.set_halign(Gtk.Align.CENTER)
        root.set_valign(Gtk.Align.START)
        root.set_size_request(660, -1)
        root.set_margin_top(int(self.rect().h * 0.14))
        self.entry = Gtk.Entry(placeholder_text="Search the palace")
        self.entry.add_css_class("search-entry")
        self.entry.connect("changed", lambda e: self.app.search_query(e.get_text()))
        self.entry.connect("activate", lambda e: self.app.search_choose())
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_search_key)
        self.entry.add_controller(keys)
        self.results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.results_box.add_css_class("search-results")
        self.rows = []
        for i in range(7):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            row.add_css_class("search-row")
            title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            title.add_css_class("r-title")
            meta = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            meta.add_css_class("r-meta")
            row.append(title)
            row.append(meta)
            click = Gtk.GestureClick()
            click.connect("released", lambda _g, _n, _x, _y, i=i: self.app.search_choose(i))
            row.add_controller(click)
            self.results_box.append(row)
            self.rows.append((row, title, meta))
        self.count = Gtk.Label(xalign=1)
        self.count.add_css_class("search-count")
        root.append(self.entry)
        root.append(self.results_box)
        root.append(self.count)
        root.set_visible(False)
        overlay.add_overlay(root)
        self.search_root = root
        self.search_open = False
        self.hide_timer = 0

    def show_search(self, text: str = ""):
        if self.hide_timer:
            GLib.source_remove(self.hide_timer)
            self.hide_timer = 0
        self.search_open = True
        self.search_root.set_visible(True)
        GLib.timeout_add(16, lambda: self.search_root.add_css_class("shown") and False)
        self.entry.set_text(text)
        # keyboard focus arrives once the compositor hands this surface the keyboard
        def grab():
            self.entry.grab_focus()
            self.entry.set_position(-1)
            return False
        GLib.timeout_add(60, grab)

    def hide_search(self):
        if not self.search_open:
            return
        self.search_open = False
        self.search_root.remove_css_class("shown")

        def done():
            self.hide_timer = 0
            if not self.search_open:
                self.search_root.set_visible(False)
            return False
        self.hide_timer = GLib.timeout_add(220, done)

    def set_results(self, items: list[tuple[str, str]], selected: int, count: str):
        for i, (row, title, meta) in enumerate(self.rows):
            row.set_visible(i < len(items))
            if i < len(items):
                title.set_text(items[i][0])
                meta.set_text(items[i][1])
                (row.add_css_class if i == selected else row.remove_css_class)("selected")
        self.results_box.set_visible(bool(items))
        self.count.set_text(count)

    def on_search_key(self, ctrl, keyval, keycode, state):
        self.app.poke()
        if keyval == Gdk.KEY_Escape:
            self.app.end_peek()
        elif keyval in (Gdk.KEY_Down, Gdk.KEY_Tab):
            self.app.search_move(1)
        elif keyval in (Gdk.KEY_Up, Gdk.KEY_ISO_Left_Tab):
            self.app.search_move(-1)
        else:
            return False
        return True

    def on_window_key(self, ctrl, keyval, keycode, state):
        # keys while flying/following with the search bar closed
        if self.search_open or not self.app.peeking:
            return False
        self.app.poke()
        if keyval == Gdk.KEY_Escape:
            self.app.end_peek()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.app.open_focused()
        else:
            ch = chr(Gdk.keyval_to_unicode(keyval)) if Gdk.keyval_to_unicode(keyval) else ""
            if not ch.isprintable() or not ch.strip():
                return False
            self.app.reopen_search(self, ch)   # start typing to search again
        return True

    def set_peek(self, on: bool, keyboard: bool):
        base = {"background": LayerShell.Layer.BACKGROUND}.get(self.app.cfg["behaviour"]["layer"],
                                                                 LayerShell.Layer.BOTTOM)
        LayerShell.set_layer(self.win, LayerShell.Layer.OVERLAY if on else base)
        LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.EXCLUSIVE if keyboard
                                     else LayerShell.KeyboardMode.NONE)

    # geometry --------------------------------------------------------
    def rect(self) -> Rect:
        g = self.monitor.get_geometry()
        return Rect(g.x, g.y, g.width, g.height)

    # GL --------------------------------------------------------------
    def on_realize(self, area):
        area.make_current()
        if area.get_error():
            log(self.name, "GL error:", area.get_error())
            return
        log(self.name, "GL:", gl.glGetString(gl.GL_RENDERER).decode(), gl.glGetString(gl.GL_VERSION).decode())
        self.renderer = Renderer(self.app.scene, self.app.cfg)
        self.set_running(True)

    def on_unrealize(self, area):
        self.set_running(False)
        self.renderer = None

    def on_resize(self, area, w, h):
        self.px = (w, h)

    def on_render(self, area, ctx):
        if not self.renderer:
            return True
        fbo = gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)
        w, h = self.px
        mon = self.rect()
        dev = w / mon.w
        # GPU timing: read last frame's query (non-blocking), start a new one
        if not hasattr(self, "query"):
            self.query, self.query_pending = int(np.ravel(gl.glGenQueries(1))[0]), False
        if self.query_pending and int(np.ravel(gl.glGetQueryObjectiv(self.query, gl.GL_QUERY_RESULT_AVAILABLE))[0]):
            ns = ctypes.c_uint64(0)
            gl.glGetQueryObjectui64v(self.query, gl.GL_QUERY_RESULT, ctypes.byref(ns))
            self.app.note_gpu(self.name, ns.value / 1e9)
            self.query_pending = False
        timing = not self.query_pending
        if timing:
            gl.glBeginQuery(gl.GL_TIME_ELAPSED, self.query)
        t0 = time.perf_counter()
        self.renderer.render(int(fbo), w, h, self.app.now(), mon, self.app.total, dev)
        self.app.note_frame(self.name, time.perf_counter() - t0)
        if timing:
            gl.glEndQuery(gl.GL_TIME_ELAPSED)
            self.query_pending = True
        self.frames = getattr(self, "frames", 0) + 1
        dump = os.environ.get("GALAXY_DUMP")
        if dump and self.frames == int(os.environ.get("GALAXY_DUMP_FRAME", "600")):
            self.dump_frame(dump, w, h, fbo)
        return True

    def dump_frame(self, out_dir, w, h, fbo):
        r = self.renderer
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, r.hdr.fbo)
        hdr = np.frombuffer(gl.glReadPixels(0, 0, r.hdr.w, r.hdr.h, gl.GL_RGBA, gl.GL_FLOAT), np.float32)
        s = self.app.scene
        log("debug: fbo", fbo, "hdr max", float(hdr.max()), "mean", float(hdr.mean()), "n", s.n,
            "mix", s.mix(self.app.now()), "now", self.app.now(), "geomver", r.geometry_version, s.geometry_version)
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, int(fbo))
        data = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        img = np.frombuffer(data, np.uint8).reshape(h, w, 3)[::-1].copy()
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(img.tobytes()), GdkPixbuf.Colorspace.RGB,
                                             False, 8, w, h, w * 3)
        path = os.path.join(out_dir, f"live-{self.name}.png")
        pb.savev(path, "png", [], [])
        log("dumped", path, w, h)

    # animation -------------------------------------------------------
    def set_running(self, on: bool):
        if on and not self.tick_id and self.renderer:
            self.tick_id = self.area.add_tick_callback(self.on_tick)
            self.area.queue_render()
        elif not on and self.tick_id:
            self.area.remove_tick_callback(self.tick_id)
            self.tick_id = 0

    def on_tick(self, widget, clock):
        self.app.step(clock.get_frame_time() / 1e6)
        now = self.app.now()
        if self.pointer and now - self.last_pick > 0.08:
            self.update_hover()
        if self.hovered is not None:
            self.place_label()
        if self.app.is_active():
            self.area.queue_render()
        else:
            # idle: render at idle_fps. Slots come from the shared clock, so
            # both monitors draw the same frames and stay in step
            slot = int(now * self.app.cfg["render"]["idle_fps"])
            if slot != self.last_slot:
                self.last_slot = slot
                self.area.queue_render()
        return GLib.SOURCE_CONTINUE

    # interaction -----------------------------------------------------
    def on_motion(self, x, y):
        self.app.poke()
        self.pointer = None if x is None else (x, y)
        self.update_hover()

    def update_hover(self):
        if self.dragging:
            return
        self.last_pick = self.app.now()
        idx = None
        if self.pointer and self.app.scene.n:
            idx = self.app.scene.pick(self.app.now(), self.rect(), self.app.total, *self.pointer,
                                      self.app.cfg["behaviour"]["pick_radius"])
        self.app.set_hover(self, idx)

    def show_label(self, idx: int | None):
        self.hovered = idx
        if idx is None:
            self.label.remove_css_class("shown")
            self.area.set_cursor(None)
            return
        s = self.app.scene
        self.title.set_text(s.titles[idx])
        n = len(s.neighbors[idx])
        folder = s.folders[idx].replace("/", "  ·  ") or "vault root"
        self.meta.set_text(f"{folder.upper()}   —   {n} LINK{'S' if n != 1 else ''}")
        self.area.set_cursor(Gdk.Cursor.new_from_name("pointer"))
        self.place_label()
        self.label.add_css_class("shown")

    def place_label(self):
        idx = self.hovered
        s = self.app.scene
        if idx is None or idx >= s.n:
            return
        mon = self.rect()
        sx, sy, _, _ = s.project(self.app.now(), mon, self.app.total)
        x, y = float(sx[idx]), float(sy[idx])
        _, nat = self.label.get_preferred_size()
        flip = x + 12 + nat.width > mon.w - 24
        if flip != self.flipped:
            self.flipped = flip
            self.label.reorder_child_after(self.hair, self.text if flip else None)
            (self.hair.add_css_class if flip else self.hair.remove_css_class)("flip")
            self.title.set_xalign(1 if flip else 0)
            self.meta.set_xalign(1 if flip else 0)
        lx = x - 12 - nat.width if flip else x + 12
        self.fixed.move(self.label, lx, y - 11)

    def on_scroll(self, controller, dx, dy):
        self.app.poke()
        self.app.zoom(dy)
        return True

    def on_drag_begin(self, gesture, x, y):
        self.pointer = (x, y)
        self.update_hover()
        self.drag_star = self.hovered
        self.drag_origin = list(self.app.scene.camera.center)
        self.dragging = self.just_dragged = False

    def on_drag_update(self, gesture, dx, dy):
        if self.drag_star is not None or self.drag_origin is None:
            return
        if not self.dragging:
            if dx * dx + dy * dy < 36:
                return
            self.dragging = True
            self.app.set_hover(self, None)
            self.area.set_cursor(Gdk.Cursor.new_from_name("grabbing"))
        self.app.poke()
        total = self.app.total
        self.app.scene.camera.center_target = None
        self.app.scene.camera.center = [
            min(max(self.drag_origin[0] + dx / total.w, 0.03), 0.97),
            min(max(self.drag_origin[1] + dy / total.h, 0.05), 0.95),
        ]

    def on_drag_end(self, gesture, dx, dy):
        if self.dragging:
            self.dragging = False
            self.just_dragged = True
            self.area.set_cursor(None)
            self.app.save_state()
        self.drag_origin = None

    def on_click(self, gesture, n_press, x, y):
        if self.just_dragged:
            self.just_dragged = False
            return
        self.pointer = (x, y)
        self.update_hover()
        if self.hovered is not None:
            if n_press == 1:
                self.app.open_note(self.hovered)
        elif n_press == 2:
            # double-click on empty space: back to the default view
            self.app.reset_view()


class GalaxyApp:
    def __init__(self):
        self.cfg = config.load()
        self.scene = Scene(self.cfg)
        self.save_timer = 0
        self.active_until = 0.0
        # search / peek / focus
        self.peeking = False
        self.peek_deadline = 0.0
        self.search_host: MonitorSurface | None = None
        self.search_results: list[int] = []
        self.search_sel = 0
        self.focus_idx: int | None = None
        self.focus_path: str | None = None
        self.focus_host: MonitorSurface | None = None
        self.load_state()
        self.start = time.monotonic()
        self.last_step = None
        self.surfaces: dict[str, MonitorSurface] = {}
        self.total = Rect(0, 0, 1, 1)
        self.hover_owner: MonitorSurface | None = None
        self.cache = LayoutCache(config.layout_cache_path(self.cfg["vault"]["path"]))
        self.layout_busy = False
        self.layout_dirty = False
        self.vault_timer = 0
        self.cover_timer = 0
        self.stats: dict[str, list[float]] = {}
        self.gtk = Gtk.Application(application_id=APP_ID,
                                   flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.gtk.connect("activate", self.on_activate)

    def load_state(self):
        try:
            with open(config.STATE_PATH) as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            return
        cam = self.scene.camera
        try:
            cx, cy = state.get("center", cam.center)
            cam.center = [float(cx), float(cy)]
            cam.distance = cam.distance_target = float(state.get("distance", cam.distance))
        except (TypeError, ValueError):
            pass

    def save_state(self):
        self.save_timer = 0
        cam = self.scene.camera
        os.makedirs(os.path.dirname(config.STATE_PATH), exist_ok=True)
        tmp = config.STATE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            center = cam.center_target or cam.center   # save where it's heading
            json.dump({"center": [round(v, 4) for v in center],
                       "distance": round(cam.distance_target, 4)}, fh)
        os.replace(tmp, config.STATE_PATH)
        log("view saved: centre", cam.center, "distance", round(cam.distance_target, 3))
        return False

    def reset_view(self):
        self.end_peek()
        self.poke()
        self.scene.camera.reset()
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(800, self.save_state)

    def zoom(self, dy: float):
        """Scroll down = zoom out, up = in; ~10% per wheel notch, smooth on touchpads."""
        cam = self.scene.camera
        lo, hi = self.cfg["camera"]["zoom_min_distance"], self.cfg["camera"]["zoom_max_distance"]
        cam.distance_target = min(max(cam.distance_target * math.exp(dy * 0.1), lo), hi)
        if self.save_timer:
            GLib.source_remove(self.save_timer)
        self.save_timer = GLib.timeout_add(800, self.save_state)

    def now(self) -> float:
        return time.monotonic() - self.start

    # ---------------------------------------------------------- setup
    def on_activate(self, _app):
        if self.surfaces:
            return
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.gtk.hold()
        # `bin/astral-palace-search` (bound to e.g. Super+Period) triggers this over D-Bus
        action = Gio.SimpleAction.new("search", None)
        action.connect("activate", lambda *_: self.toggle_search())
        self.gtk.add_action(action)
        mons = Gdk.Display.get_default().get_monitors()
        mons.connect("items-changed", lambda *_: GLib.timeout_add(500, self.sync_monitors))
        self.sync_monitors()
        self.relayout(initial=True)
        # pausing reads window layout from Hyprland; elsewhere the galaxy just keeps running
        if (self.cfg["behaviour"]["pause_when_covered"] and ON_HYPRLAND
                and not os.environ.get("GALAXY_DUMP")):
            HyprEvents(self.schedule_cover_check).start()
            self.schedule_cover_check()
        VaultWatcher(self.cfg["vault"]["path"], self.schedule_relayout).start()
        GLib.timeout_add_seconds(30, self.report_stats)

    def sync_monitors(self):
        mons = Gdk.Display.get_default().get_monitors()
        current = [mons.get_item(i) for i in range(mons.get_n_items())]
        names = {m.get_connector() for m in current}
        for name in list(self.surfaces):
            if name not in names:
                self.surfaces.pop(name).win.destroy()
        for m in current:
            if m.get_connector() not in self.surfaces:
                self.surfaces[m.get_connector()] = MonitorSurface(self, m)
        rects = [s.rect() for s in self.surfaces.values()]
        x0 = min(r.x for r in rects)
        y0 = min(r.y for r in rects)
        x1 = max(r.x + r.w for r in rects)
        y1 = max(r.y + r.h for r in rects)
        self.total = Rect(x0, y0, x1 - x0, y1 - y0)
        log("monitors:", {n: vars(s.rect()) for n, s in self.surfaces.items()}, "total:", vars(self.total))
        return False

    # ---------------------------------------------------------- frame
    def step(self, frame_time: float):
        # several surfaces tick each frame; advance shared state once
        if self.last_step is not None and frame_time - self.last_step < 0.004:
            return
        dt = 0.016 if self.last_step is None else min(frame_time - self.last_step, 0.1)
        self.last_step = frame_time
        cam = self.scene.camera
        if self.focus_idx is not None:
            cam.focus_local = self.scene.current_positions(self.now())[self.focus_idx, :3]
        if self.peeking and self.now() > self.peek_deadline:
            log("search idle for too long; sinking back behind windows")
            self.end_peek()
        if (self.scene.step_highlight(dt) or cam.moving()
                or self.scene.mix(self.now()) < 1.0):
            self.poke()
        cam.step(dt)

    def poke(self):
        """Something is moving or being interacted with: render at full rate for a while."""
        self.active_until = self.now() + self.cfg["render"]["active_linger"]
        if self.peeking:
            self.peek_deadline = self.now() + self.cfg["behaviour"]["peek_timeout"]

    def is_active(self) -> bool:
        return self.now() < self.active_until

    def note_frame(self, name, secs):
        self.stats.setdefault(name, []).append(secs)

    def note_gpu(self, name, secs):
        self.stats.setdefault(name + ":gpu", []).append(secs)

    def report_stats(self):
        for name, v in sorted(self.stats.items()):
            if v:
                v.sort()
                kind = "gpu" if name.endswith(":gpu") else "cpu"
                extra = f"{len(v)/30:.0f} fps, " if kind == "cpu" else ""
                log(f"{name.split(':')[0]}: {extra}{kind} frame median {1000*v[len(v)//2]:.2f} ms, "
                    f"p95 {1000*v[int(len(v)*0.95)]:.2f} ms")
        self.stats = {}
        return True

    # ---------------------------------------------------------- hover/click
    def set_hover(self, surf: MonitorSurface, idx):
        if idx is None and self.focus_idx is not None:
            surf, idx = self.focus_host, self.focus_idx   # the followed star stays lit
        if surf is not self.hover_owner and idx is None:
            return
        if self.hover_owner and self.hover_owner is not surf:
            self.hover_owner.show_label(None)
        self.hover_owner = surf if idx is not None else None
        if idx != surf.hovered:
            self.scene.set_hover(idx)
            surf.show_label(idx)

    def open_note(self, idx: int):
        path = self.scene.paths[idx]
        uri = f"obsidian://open?vault={quote(self.cfg['vault']['name'])}&file={quote(path[:-3])}"
        log("open", uri)
        spawn(["xdg-open", uri])
        if self.peeking:
            self.end_peek()
        if self.cfg["behaviour"]["focus_obsidian"] and ON_HYPRLAND:
            GLib.timeout_add(350, self.focus_obsidian)

    def focus_obsidian(self):
        """Bring Obsidian forward (switching workspace if needed). Lua-config Hyprland
        takes Lua dispatch syntax; older versions take the classic form."""
        cls = self.cfg["behaviour"]["obsidian_class"]
        try:
            out = subprocess.run(["hyprctl", "dispatch", f'hl.dsp.focus({{ window = "class:{cls}" }})'],
                                 capture_output=True, text=True, timeout=2, env=child_env())
            if "error" in (out.stdout + out.stderr).lower():
                subprocess.run(["hyprctl", "dispatch", "focuswindow", f"class:{cls}"],
                               capture_output=True, timeout=2, env=child_env())
        except (OSError, subprocess.TimeoutExpired) as e:
            log("focus obsidian:", e)
        return False

    # ---------------------------------------------------------- search
    def focused_surface(self) -> MonitorSurface | None:
        try:
            for m in hypr("monitors"):
                if m.get("focused") and m["name"] in self.surfaces:
                    return self.surfaces[m["name"]]
        except Exception:  # noqa: BLE001
            pass
        return next(iter(self.surfaces.values()), None)

    def toggle_search(self):
        if self.peeking and self.search_host and self.search_host.search_open:
            self.end_peek()
        elif self.peeking and self.search_host:
            self.search_host.show_search()
        else:
            self.start_peek()

    def start_peek(self):
        host = self.focused_surface()
        if host is None or not self.scene.n:
            return
        self.peeking = True
        self.search_host = host
        self.poke()
        # rise above the windows on every monitor; only the host takes the keyboard
        for surf in self.surfaces.values():
            surf.set_peek(True, keyboard=surf is host)
            surf.set_running(True)
        host.show_search()
        self.search_query("")

    def end_peek(self):
        if not self.peeking:
            return
        self.peeking = False
        if self.search_host:
            self.search_host.hide_search()
        if self.focus_idx is not None:
            self.scene.camera.unfocus()
        self.focus_idx = self.focus_path = self.focus_host = None
        self.scene.set_matches(None)
        self.hover_owner = None
        self.scene.set_hover(None)
        for surf in self.surfaces.values():
            surf.show_label(None)
            surf.set_peek(False, keyboard=False)
        self.search_host = None
        self.poke()
        self.schedule_cover_check()

    def reopen_search(self, surf: MonitorSurface, text: str):
        self.search_host = surf
        surf.show_search(text)

    def search_query(self, text: str):
        self.poke()
        s = self.scene
        q = text.strip().lower()
        results: list[int] = []
        if q:
            toks = q.split()
            scored = []
            for i, title in enumerate(s.titles):
                t = title.lower()
                if t == q:
                    rank = 0
                elif t.startswith(q):
                    rank = 1
                elif any(w.startswith(q) for w in re.split(r"[\s\-_/.,—()]+", t)):
                    rank = 2
                elif q in t:
                    rank = 3
                elif all(tk in t for tk in toks):
                    rank = 4
                elif all(tk in f"{t} {s.folders[i].lower()}" for tk in toks):
                    rank = 5
                else:
                    continue
                scored.append((rank, -len(s.neighbors[i]), len(title), i))
            results = [i for *_, i in sorted(scored)]
            mask = np.zeros(s.n, np.float32)
            mask[results] = 1.0
            s.set_matches(mask)
        else:
            s.set_matches(None)
        self.search_results = results
        self.search_sel = 0
        self._update_results()

    def _note_meta(self, idx: int) -> str:
        n = len(self.scene.neighbors[idx])
        folder = self.scene.folders[idx].replace("/", "  ·  ") or "vault root"
        return f"{folder.upper()}   —   {n} LINK{'S' if n != 1 else ''}"

    def _update_results(self):
        host = self.search_host
        if host is None:
            return
        res = self.search_results
        items = [(self.scene.titles[i], self._note_meta(i)) for i in res[:7]]
        if not host.entry.get_text().strip():
            count = f"TYPE TO SEARCH {self.scene.n} STARS"
        elif not res:
            count = "NO MATCHING STARS"
        else:
            count = f"{len(res)} STAR{'S' if len(res) != 1 else ''}   ·   ENTER TO FLY"
        host.set_results(items, self.search_sel, count)

    def search_move(self, d: int):
        if self.search_results:
            self.search_sel = (self.search_sel + d) % min(len(self.search_results), 7)
            self._update_results()

    def search_choose(self, row: int | None = None):
        if not self.search_results:
            return
        i = self.search_sel if row is None else row
        if i < len(self.search_results):
            self.fly_to(self.search_results[i])

    def fly_to(self, idx: int):
        host = self.search_host or self.focused_surface()
        host.hide_search()
        self.scene.set_matches(None)
        self.focus_idx, self.focus_path, self.focus_host = idx, self.scene.paths[idx], host
        # hold the star just left of the middle of the screen you searched on
        mon, tot = host.rect(), self.total
        center = [(mon.x + mon.w * 0.45 - tot.x) / tot.w, (mon.y + mon.h * 0.5 - tot.y) / tot.h]
        local = self.scene.current_positions(self.now())[idx, :3]
        self.scene.camera.focus(local, center, self.cfg["camera"]["focus_distance"])
        for surf in self.surfaces.values():
            surf.show_label(None)
        self.hover_owner = None
        self.set_hover(host, idx)
        self.poke()

    def open_focused(self):
        if self.focus_idx is not None:
            self.open_note(self.focus_idx)

    # ---------------------------------------------------------- pause
    def schedule_cover_check(self):
        if not self.cover_timer:
            self.cover_timer = GLib.timeout_add(120, self.check_cover)
        return False

    def check_cover(self):
        self.cover_timer = 0
        if self.peeking:
            return False
        covered = covered_monitors()
        for name, s in self.surfaces.items():
            s.set_running(name not in covered)
        return False

    # ---------------------------------------------------------- vault
    def schedule_relayout(self):
        if self.vault_timer:
            GLib.source_remove(self.vault_timer)
        self.vault_timer = GLib.timeout_add(1500, self._relayout_timer)
        return False

    def _relayout_timer(self):
        self.vault_timer = 0
        self.relayout()
        return False

    def relayout(self, initial=False):
        if self.layout_busy:
            self.layout_dirty = True
            return
        self.layout_busy = True

        def work():
            try:
                t0 = time.time()
                g = build_graph(self.cfg["vault"]["path"], self.cfg["vault"]["archive_prefix"])
                sig = (tuple(n.path for n in g.notes), tuple(g.edges))
                if not initial and sig == getattr(self, "graph_sig", None):
                    main_thread(self._layout_done, None, None, None)
                    return
                init = self.cache.load()
                all_known = all(n.path in init for n in g.notes)
                iters = 0 if (initial and all_known) else (120 if init else 600)
                raw = force_layout(g, init, iterations=iters)
                self.cache.save(g, raw)
                disk = to_disk(g, raw)
                log(f"layout: {len(g.notes)} notes, {len(g.edges)} links, {iters} iters, {time.time()-t0:.1f}s")
                main_thread(self._layout_done, g, disk, sig)
            except Exception as e:  # noqa: BLE001
                log("layout failed:", repr(e))
                main_thread(self._layout_done, None, None, None)

        threading.Thread(target=work, daemon=True).start()

    def _layout_done(self, g, disk, sig):
        self.layout_busy = False
        if g is not None:
            self.graph_sig = sig
            for s in self.surfaces.values():
                s.show_label(None)
            self.hover_owner = None
            self.scene.set_graph(g, disk, self.now())
            # indices changed: keep following the same note, refresh live results
            if self.focus_path is not None:
                if self.focus_path in self.scene.paths:
                    self.focus_idx = self.scene.paths.index(self.focus_path)
                    self.set_hover(self.focus_host, self.focus_idx)
                else:
                    self.end_peek()
            if self.search_host and self.search_host.search_open:
                self.search_query(self.search_host.entry.get_text())
        if self.layout_dirty:
            self.layout_dirty = False
            self.relayout()
        return False

    def run(self):
        return self.gtk.run([])


def find_layer_shell() -> str | None:
    for d in ("/usr/lib", "/usr/lib64", "/usr/local/lib", "/usr/lib/x86_64-linux-gnu",
              "/usr/lib/aarch64-linux-gnu"):
        path = os.path.join(d, "libgtk4-layer-shell.so")
        if os.path.exists(path):
            return path
    try:
        out = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "libgtk4-layer-shell.so" in line and "=>" in line:
                return line.split("=>")[1].strip()
    except OSError:
        pass
    return None


def main():
    if "libgtk4-layer-shell" not in os.environ.get("LD_PRELOAD", ""):
        # Re-exec once with this process's environment overrides. Originals are
        # remembered so anything we launch (notes, hyprctl) gets the user's env back.
        for name in OVERRIDDEN:
            os.environ.setdefault(ORIG_PREFIX + name, os.environ.get(name, UNSET))
        lib = find_layer_shell()
        if not lib:
            sys.exit("astral-palace: libgtk4-layer-shell.so not found (install gtk4-layer-shell)")
        # layer-shell must load before libwayland-client
        os.environ["LD_PRELOAD"] = (lib + " " + os.environ.get("LD_PRELOAD", "")).strip()
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        # some drivers (NVIDIA here) give GTK a GLES context that a desktop-GL
        # GLArea can't share; ask GTK for desktop GL instead
        os.environ["GDK_DISABLE"] = ",".join(filter(None, [os.environ.get("GDK_DISABLE"), "gles-api"]))
        # render at the compositor's fractional scale rather than a forced integer one
        os.environ.pop("GDK_SCALE", None)
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        os.environ["PYTHONPATH"] = ":".join(filter(None, [repo, os.environ.get("PYTHONPATH")]))
        os.execv(sys.executable, [sys.executable, "-m", "galaxy.app", *sys.argv[1:]])
    sys.exit(GalaxyApp().run())


if __name__ == "__main__":
    main()
