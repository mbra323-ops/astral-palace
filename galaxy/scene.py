"""CPU-side scene state shared by every monitor: star attributes, dust, camera."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .layout import _seed
from .vault import Graph

TEXW = 1024

# Interstellar-warm ramp: deep ember → amber → gold → warm white → white-hot
RAMP_T = np.array([0.0, 0.3, 0.55, 0.8, 1.0])
RAMP_C = np.array([
    [1.00, 0.20, 0.03],
    [1.00, 0.40, 0.08],
    [1.00, 0.64, 0.25],
    [1.00, 0.85, 0.62],
    [0.94, 0.96, 1.00],
])


# "space dusk" accents: cool dust and young blue stars against the warm disk
DUSK = np.array([
    [0.32, 0.52, 1.00],   # steel blue
    [0.30, 0.34, 0.95],   # indigo
    [0.55, 0.38, 1.00],   # violet
    [0.40, 0.70, 1.00],   # pale cyan-blue
])
BLUE_STAR = np.array([0.62, 0.78, 1.00])


def ramp(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0, 1)
    return np.stack([np.interp(t, RAMP_T, RAMP_C[:, k]) for k in range(3)], -1)


def smoothstep(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


# ---------------------------------------------------------------- matrices

def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0, 0], [0, c, -s, 0], [0, s, c, 0], [0, 0, 0, 1]], np.float64)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]], np.float64)


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0, 0], [s, c, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], np.float64)


def look_at(eye, target, up):
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.identity(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def perspective(fovy, aspect, near, far):
    f = 1.0 / math.tan(fovy / 2)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1
    return m


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class View:
    model: np.ndarray
    view_proj: np.ndarray       # sub-frustum for one monitor
    sky_view_proj: np.ndarray
    cam_pos: np.ndarray
    core_frac: tuple[float, float]   # galaxy core on the desktop (fractions, y down)


class Camera:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        # galaxy centre as a fraction of the whole desktop (x right, y down);
        # draggable at runtime, so it lives here rather than in the config
        self.center = [cfg["center_x"], cfg["center_y"]]
        # zoom: scroll sets the target, the camera eases toward it each frame
        self.distance = cfg["distance"]
        self.distance_target = cfg["distance"]
        # set by reset(); dragging moves center directly and clears it
        self.center_target: list[float] | None = None
        # focus: the camera looks at a star instead of the core (blend 0..1)
        self.focus_local: np.ndarray | None = None
        self.focus_blend = 0.0
        self.focus_blend_target = 0.0
        self.saved_view: tuple[list[float], float] | None = None

    def reset(self) -> None:
        """Glide back to the configured centre and zoom."""
        self.focus_blend_target = 0.0
        self.saved_view = None
        self.center_target = [self.cfg["center_x"], self.cfg["center_y"]]
        self.distance_target = self.cfg["distance"]

    def focus(self, local: np.ndarray, center: list[float], distance: float) -> None:
        """Fly to a star (galaxy-local position) and hold it at `center` on the desktop."""
        if self.saved_view is None:
            self.saved_view = (list(self.center_target or self.center), self.distance_target)
        self.focus_local = np.asarray(local, float)
        self.focus_blend_target = 1.0
        self.center_target = list(center)
        self.distance_target = distance

    def unfocus(self) -> None:
        """Glide back to wherever the view was before the first focus."""
        self.focus_blend_target = 0.0
        if self.saved_view is not None:
            self.center_target, self.distance_target = self.saved_view
            self.saved_view = None

    def moving(self) -> bool:
        return (self.distance != self.distance_target or self.center_target is not None
                or self.focus_blend != self.focus_blend_target)

    def step(self, dt: float) -> None:
        k = 1 - math.exp(-dt * 6.0)
        if self.distance != self.distance_target:
            self.distance += (self.distance_target - self.distance) * k
            if abs(self.distance - self.distance_target) < 1e-4:
                self.distance = self.distance_target
        if self.center_target is not None:
            self.center = [c + (t - c) * k for c, t in zip(self.center, self.center_target)]
            if max(abs(c - t) for c, t in zip(self.center, self.center_target)) < 1e-4:
                self.center, self.center_target = list(self.center_target), None
        if self.focus_blend != self.focus_blend_target:
            self.focus_blend += (self.focus_blend_target - self.focus_blend) * (1 - math.exp(-dt * 3.0))
            if abs(self.focus_blend - self.focus_blend_target) < 1e-3:
                self.focus_blend = self.focus_blend_target
                if self.focus_blend == 0.0:
                    self.focus_local = None

    def view(self, t: float, mon: Rect, total: Rect) -> View:
        c = self.cfg
        spin = 2 * math.pi * t / c["spin_period"]
        wob = math.radians(c["wobble_deg"]) * math.sin(2 * math.pi * t / c["wobble_period"])
        model = rot_x(wob) @ rot_y(0.6 * wob) @ rot_z(spin)

        e = math.radians(c["elevation_deg"] + c["elevation_swing_deg"]
                         * math.sin(2 * math.pi * t / c["elevation_period"]))
        az = math.radians(c["azimuth_deg"])
        d = self.distance
        eye = np.array([d * math.cos(e) * math.sin(az), -d * math.cos(e) * math.cos(az), d * math.sin(e)])
        target = np.array([0.0, 0.0, c["target_z"]])
        if self.focus_local is not None and self.focus_blend > 0:
            star = (model @ np.append(self.focus_local, 1.0))[:3]
            target = target + (star - target) * smoothstep(self.focus_blend)
        eye = eye + target
        view = look_at(eye, target, np.array([0.0, 0.0, 1.0]))

        aspect = total.w / total.h
        proj = perspective(math.radians(c["fov_deg"]), aspect, 0.05, 1000.0)
        # lens shift: put the galaxy centre at center_x / center_y of the desktop
        shift = np.identity(4)
        shift[0, 3] = (self.center[0] - 0.5) * 2
        shift[1, 3] = -(self.center[1] - 0.5) * 2
        # crop the full frustum down to this monitor's slice (NDC is y-up)
        x0 = -1 + 2 * (mon.x - total.x) / total.w
        x1 = -1 + 2 * (mon.x + mon.w - total.x) / total.w
        y1 = 1 - 2 * (mon.y - total.y) / total.h
        y0 = 1 - 2 * (mon.y + mon.h - total.y) / total.h
        crop = np.identity(4)
        crop[0, 0] = 2 / (x1 - x0)
        crop[0, 3] = -(x1 + x0) / (x1 - x0)
        crop[1, 1] = 2 / (y1 - y0)
        crop[1, 3] = -(y1 + y0) / (y1 - y0)
        p = crop @ shift @ proj

        # where the galaxy core lands on the desktop (drives the background glow)
        core = shift @ proj @ view @ np.array([0.0, 0.0, 0.0, 1.0])
        if core[3] > 1e-6:
            core_frac = ((core[0] / core[3] + 1) / 2, (1 - core[1] / core[3]) / 2)
        else:
            core_frac = (-10.0, -10.0)

        sky_view = view.copy()
        sky_view[:3, 3] = 0
        return View(model, p @ view, p @ sky_view, eye, core_frac)


# ---------------------------------------------------------------- scene

class Scene:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.camera = Camera(cfg["camera"])
        self.paths: list[str] = []
        self.titles: list[str] = []
        self.folders: list[str] = []
        self.n = 0
        self.pos_from = np.zeros((0, 4), np.float32)
        self.pos_to = np.zeros((0, 4), np.float32)
        self.trans_start = 0.0
        self.trans_dur = 1.0
        self.star_color = np.zeros((0, 4), np.float32)
        self.star_meta = np.zeros((0, 4), np.float32)
        self.edges = np.zeros((0, 2), np.float32)
        self.edge_weight = np.zeros((0,), np.float32)
        self.neighbors: list[np.ndarray] = []
        self.dust_pos = np.zeros((0, 4), np.float32)
        self.dust_color = np.zeros((0, 4), np.float32)
        self.dust_size = np.zeros((0,), np.float32)
        self.dust_soft_count = 0
        self.highlight = np.zeros((0, 3), np.float32)   # hover, neighbour, search match
        self.hl_target = np.zeros((0, 3), np.float32)
        self.search_dim = 0.0          # 0..1: dims non-matching stars while searching
        self.search_dim_target = 0.0
        self.geometry_version = 0
        self.highlight_version = 0
        self.sky_dir, self.sky_color = self._make_sky()

    # -- transitions

    def mix(self, t: float) -> float:
        return smoothstep((t - self.trans_start) / self.trans_dur)

    def current_positions(self, t: float) -> np.ndarray:
        m = self.mix(t)
        return self.pos_from * (1 - m) + self.pos_to * m

    def set_graph(self, graph: Graph, disk: np.ndarray, now: float) -> None:
        first = self.n == 0
        old = {p: i for i, p in enumerate(self.paths)}
        cur = self.current_positions(now) if not first else None

        n = len(graph.notes)
        to = np.zeros((n, 4), np.float32)
        to[:, :3] = disk
        to[:, 3] = 1.0
        frm = to.copy()
        for i, note in enumerate(graph.notes):
            j = old.get(note.path)
            if j is not None:
                frm[i] = cur[j]
            elif first:
                # intro: everything blooms outward from a compact core
                frm[i, :3] = disk[i] * np.array([0.06, 0.06, 0.0])
                frm[i, 3] = 0.0
            else:
                frm[i, 3] = 0.0

        self.paths = [nt.path for nt in graph.notes]
        self.titles = [nt.title for nt in graph.notes]
        self.folders = [nt.path.rsplit("/", 1)[0] if "/" in nt.path else "" for nt in graph.notes]
        self.n = n
        self.pos_from, self.pos_to = frm, to
        self.trans_start = now
        self.trans_dur = 7.0 if first else 3.0
        self._build_attributes(graph, disk)
        self.highlight = np.zeros((n, 3), np.float32)
        self.hl_target = np.zeros((n, 3), np.float32)
        self.search_dim = self.search_dim_target = 0.0
        self.geometry_version += 1
        self.highlight_version += 1

    def _build_attributes(self, graph: Graph, disk: np.ndarray) -> None:
        n = self.n
        rng = np.random.default_rng(1234)
        deg = np.asarray(graph.degree, np.float64)
        archive = np.array([nt.archive for nt in graph.notes])
        main_max = deg[~archive].max() if (~archive).any() else deg.max()
        dn = np.clip(np.log1p(deg) / math.log1p(max(main_max, 1)), 0, 1)
        r = np.sqrt((disk[:, :2] ** 2).sum(1))
        seeds = np.array([(_seed(p) % 10007) / 10007.0 for p in self.paths])

        temp = 0.5 * dn + 0.5 * (1 - np.clip(r, 0, 1)) ** 1.3 + 0.1 * (seeds - 0.5)
        col = ramp(temp)
        bright = 0.16 + 2.4 * dn ** 1.7
        # young blue stars scattered through the outer disk (minor notes only)
        seeds2 = np.array([(_seed(p + "#") % 10007) / 10007.0 for p in self.paths])
        p_blue = self.cfg["color"]["blue_star_fraction"] * np.clip((r - 0.3) / 0.7, 0, 1)
        blue = (seeds2 < p_blue) & (dn < 0.6)
        col = np.where(blue[:, None], 0.15 * col + 0.85 * BLUE_STAR, col)
        # archive: a dim, cool dusk-blue outer halo
        grey = col.mean(1, keepdims=True)
        col = np.where(archive[:, None], 0.35 * col + 0.65 * grey * np.array([0.62, 0.7, 1.0]), col)
        bright = np.where(archive, 0.22 + 0.4 * dn, bright)
        size = 0.15 + 1.0 * dn ** 0.9
        spikes = np.where(~archive & (dn > 0.6), (dn - 0.6) / 0.4, 0.0)

        self.star_color = np.column_stack([col, bright]).astype(np.float32)
        self.star_meta = np.column_stack([size, spikes, seeds, archive]).astype(np.float32)

        e = np.asarray(graph.edges, np.float32).reshape(-1, 2)
        self.edges = e
        ei = e.astype(int)
        self.edge_weight = np.where(archive[ei[:, 0]] | archive[ei[:, 1]], 0.07, 1.0).astype(np.float32)
        nb: list[list[int]] = [[] for _ in range(n)]
        for a, b in ei:
            nb[a].append(b)
            nb[b].append(a)
        self.neighbors = [np.array(x, int) for x in nb]

        self._build_dust(rng, dn, r, archive, col)

    def _build_dust(self, rng, dn, r, archive, col) -> None:
        d = self.cfg["dust"]
        main = np.where(~archive)[0]

        # dust bound to notes: soft nebular clumps, larger around hubs
        counts = np.where(archive, 3, (d["per_note"] * (0.4 + 2.2 * dn ** 1.5)).astype(int))
        idx = np.repeat(np.arange(self.n), counts)
        k = len(idx)
        spread = (0.010 + 0.045 * dn[idx] ** 1.2)[:, None]
        off = rng.normal(0, 1, (k, 3)) * spread * np.array([1, 1, 0.25])
        bpos = np.column_stack([off, idx]).astype(np.float32)
        bcol = col[idx] * 0.85 + ramp(np.full(k, 0.3)) * 0.15
        bint = d["bound_intensity"] * (0.4 + 0.6 * rng.random(k)) * np.where(archive[idx], 0.3, 1.0)
        bcolor = np.column_stack([bcol, bint]).astype(np.float32)
        bsize = (1.2 + 2.0 * rng.random(k)).astype(np.float32)

        # free disk dust: radius follows where notes actually are, so dense
        # regions of the vault glow brighter; most of it is strung into thin
        # orbital filaments that shear like an accretion disk.
        rr = r[main] if len(main) else np.array([0.5])

        def lanes(fr):
            # concentric dust lanes: bright bands separated by dark gaps
            s = 0.5 + 0.5 * np.sin(fr * 47.0 + 1.3) * np.cos(fr * 19.0 - 0.4)
            return 0.12 + 0.88 * s ** 1.6

        def disk_z(fr, ft, n):
            warp = 0.05 * np.clip(fr - 0.35, 0, None) ** 2 * np.sin(ft + 0.8)
            return rng.normal(0, 1, n) * (0.003 + 0.014 * fr) + warp

        # 1. soft gas: large faint sprites that sum into a smooth glow
        nh_ = d["haze_count"]
        hr_ = np.clip(np.abs(rng.choice(rr, nh_) + rng.normal(0, 0.06, nh_)), 0.0, 1.35)
        ht_ = rng.uniform(0, 2 * np.pi, nh_)
        gas_pos = np.column_stack([hr_, ht_, disk_z(hr_, ht_, nh_), np.full(nh_, -1.0)])
        gas_int = d["haze_intensity"] * lanes(hr_) * (0.5 + 0.5 * rng.random(nh_)) * (0.2 + 2.4 * np.exp(-hr_ / 0.22))
        gas_col = np.column_stack([ramp((1 - np.clip(hr_, 0, 1)) ** 1.5 + rng.normal(0, 0.05, nh_)), gas_int])
        gas_size = 2.5 + 4.0 * rng.random(nh_)

        # 2. thin orbital filaments that shear like an accretion disk
        nfil = d["filament_count"]
        n_arcs = 700
        arc_r = np.clip(np.abs(rng.choice(rr, n_arcs) + rng.normal(0, 0.05, n_arcs)), 0.05, 1.25)
        arc_t = rng.uniform(0, 2 * np.pi, n_arcs)
        arc_len = rng.uniform(0.3, 1.6, n_arcs)
        arc_w = rng.uniform(0.0015, 0.005, n_arcs)
        arc_b = rng.uniform(0.3, 1.0, n_arcs)
        which = rng.integers(0, n_arcs, nfil)
        fr = arc_r[which] + rng.normal(0, 1, nfil) * arc_w[which]
        u = rng.normal(0, 1, nfil)
        ft = arc_t[which] + u * arc_len[which] / np.maximum(arc_r[which], 0.2)
        fil_pos = np.column_stack([fr, ft, disk_z(fr, ft, nfil) * 0.4, np.full(nfil, -1.0)])
        fil_int = (d["filament_intensity"] * arc_b[which] * np.exp(-0.5 * u * u) * lanes(fr)
                   * (0.3 + 1.5 * np.exp(-fr / 0.3)))
        fil_rgb = ramp((1 - np.clip(fr, 0, 1)) ** 1.5 + 0.05)
        # some outer filaments are cool, like reflection-nebula dust
        cool_arc = (rng.random(n_arcs) < self.cfg["color"]["blue_filament_fraction"]) & (arc_r > 0.25)
        tint = DUSK[rng.integers(0, len(DUSK), n_arcs)]
        fil_rgb = np.where(cool_arc[which][:, None], 0.25 * fil_rgb + 0.75 * tint[which], fil_rgb)
        fil_col = np.column_stack([fil_rgb, fil_int])
        fil_size = 0.45 + 0.25 * rng.random(nfil)

        # 3. dusk clouds: soft blue/indigo/violet patches strung along the
        #    outer disk, giving the warm galaxy cool contrast
        nc = d["dusk_count"]
        n_cl = 170
        outer = rr[rr > 0.18] if (rr > 0.18).any() else rr
        cl_r = np.clip(rng.choice(outer, n_cl) + rng.normal(0, 0.04, n_cl), 0.18, 1.3)
        cl_t = rng.uniform(0, 2 * np.pi, n_cl)
        cl_dt = rng.uniform(0.12, 0.55, n_cl)
        cl_dr = rng.uniform(0.015, 0.06, n_cl)
        cl_b = rng.uniform(0.3, 1.0, n_cl) ** 1.5
        cl_c = DUSK[rng.integers(0, len(DUSK), n_cl)] * rng.uniform(0.85, 1.1, (n_cl, 1))
        w = rng.integers(0, n_cl, nc)
        u = rng.normal(0, 1, (nc, 2))
        dr_ = np.clip(cl_r[w] + u[:, 0] * cl_dr[w], 0.3, 1.45)
        dt_ = cl_t[w] + u[:, 1] * cl_dt[w]
        dusk_pos = np.column_stack([dr_, dt_, disk_z(dr_, dt_, nc) * 1.6, np.full(nc, -1.0)])
        dusk_int = d["dusk_intensity"] * cl_b[w] * np.exp(-0.5 * (u ** 2).sum(1)) * lanes(dr_) ** 0.5
        dusk_col = np.column_stack([cl_c[w], dusk_int])
        dusk_size = 4.0 + 6.0 * rng.random(nc)

        fpos = np.concatenate([gas_pos, dusk_pos]).astype(np.float32)
        fcolor = np.concatenate([gas_col, dusk_col]).astype(np.float32)
        fsize = np.concatenate([gas_size, dusk_size]).astype(np.float32)

        # sparse cool dust in the archive halo
        nh = d["halo_count"]
        hr = rng.uniform(1.15, 1.75, nh)
        ht = rng.uniform(0, 2 * np.pi, nh)
        hz = rng.normal(0, 0.07, nh)
        hpos = np.column_stack([hr, ht, hz, np.full(nh, -1.0)]).astype(np.float32)
        hcolor = np.column_stack([np.tile([0.75, 0.72, 0.75], (nh, 1)),
                                  d["haze_intensity"] * 0.08 * rng.random(nh)]).astype(np.float32)
        hsize = (1.5 + 2.5 * rng.random(nh)).astype(np.float32)

        # soft sprites first (rendered at half resolution), sharp filaments last
        self.dust_pos = np.concatenate([bpos, fpos, hpos, fil_pos.astype(np.float32)])
        self.dust_color = np.concatenate([bcolor, fcolor, hcolor, fil_col.astype(np.float32)])
        self.dust_size = np.concatenate([bsize, fsize, hsize, fil_size.astype(np.float32)])
        self.dust_soft_count = len(self.dust_pos) - nfil

    def _make_sky(self):
        rng = np.random.default_rng(99)
        n = self.cfg["sky"]["count"]
        v = rng.normal(0, 1, (n, 3))
        v /= np.linalg.norm(v, axis=1, keepdims=True)
        mag = rng.pareto(2.2, n)
        inten = np.clip(0.012 * (1 + mag), 0, 0.4) * self.cfg["sky"]["intensity"]
        t = rng.random(n)
        col = np.where(t[:, None] < 0.55, [0.85, 0.9, 1.0], np.where(t[:, None] < 0.85, [1.0, 0.95, 0.88], [1.0, 0.8, 0.6]))
        return v.astype(np.float32), np.column_stack([col, inten]).astype(np.float32)

    # -- hover highlight (eased on the CPU, uploaded only while changing)

    def set_hover(self, idx: int | None) -> None:
        self.hl_target[:, :2] = 0
        if idx is not None and 0 <= idx < self.n:
            self.hl_target[self.neighbors[idx], 1] = 1.0
            self.hl_target[idx, 0] = 1.0

    def set_matches(self, mask: np.ndarray | None) -> None:
        """Search: brighten matching stars and dim the rest (None = no search)."""
        self.hl_target[:, 2] = 0 if mask is None else mask
        self.search_dim_target = 0.0 if mask is None else 1.0

    def step_highlight(self, dt: float) -> bool:
        k = 1 - math.exp(-dt * 9.0)
        dim_moving = self.search_dim != self.search_dim_target
        if dim_moving:
            self.search_dim += (self.search_dim_target - self.search_dim) * k
            if abs(self.search_dim - self.search_dim_target) < 0.004:
                self.search_dim = self.search_dim_target
        diff = self.hl_target - self.highlight
        if not diff.any():
            return dim_moving
        self.highlight += diff * k
        small = np.abs(self.hl_target - self.highlight) < 0.004
        self.highlight[small] = self.hl_target[small]
        self.highlight_version += 1
        return True

    # -- picking

    def project(self, t: float, mon: Rect, total: Rect):
        """Screen positions (monitor-local logical px) and depth for every star."""
        v = self.camera.view(t, mon, total)
        p = self.current_positions(t)
        h = np.column_stack([p[:, :3], np.ones(len(p))])
        clip = h @ (v.view_proj @ v.model).T
        w = clip[:, 3]
        ndc = clip[:, :2] / w[:, None]
        sx = (ndc[:, 0] * 0.5 + 0.5) * mon.w
        sy = (1 - (ndc[:, 1] * 0.5 + 0.5)) * mon.h
        return sx, sy, w, p[:, 3]

    def pick(self, t: float, mon: Rect, total: Rect, x: float, y: float, radius: float):
        if self.n == 0:
            return None
        sx, sy, w, alpha = self.project(t, mon, total)
        d2 = (sx - x) ** 2 + (sy - y) ** 2
        # bigger stars are easier targets
        reach = radius * (1.0 + 0.8 * self.star_meta[:, 0])
        ok = (w > 0) & (alpha > 0.5) & (d2 < reach ** 2)
        if not ok.any():
            return None
        score = np.where(ok, d2 / reach ** 2 - 0.15 * self.star_meta[:, 0], np.inf)
        return int(np.argmin(score))
