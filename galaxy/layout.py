"""Force-directed layout (ForceAtlas2-style) flattened into a galactic disk.

The raw 2D layout is cached per note path so restarts are instant and vault
edits only need a short warm-started relaxation.
"""

from __future__ import annotations

import hashlib
import json
import os

import numpy as np

from .vault import Graph


def _seed(path: str) -> int:
    return int.from_bytes(hashlib.blake2b(path.encode(), digest_size=8).digest(), "little")


def force_layout(graph: Graph, init: dict[str, tuple[float, float]] | None = None,
                 iterations: int = 600) -> np.ndarray:
    n = len(graph.notes)
    if n == 0:
        return np.zeros((0, 2), np.float32)
    deg = np.asarray(graph.degree, np.float32)
    mass = deg + 1.0
    edges = np.asarray(graph.edges, np.int32).reshape(-1, 2)

    pos = np.zeros((n, 2), np.float32)
    known = np.zeros(n, bool)
    init = init or {}
    for i, note in enumerate(graph.notes):
        if note.path in init:
            pos[i] = init[note.path]
            known[i] = True

    rng = np.random.default_rng(7)
    scale = 10.0 * np.sqrt(n)
    if not known.any():
        pos[:] = rng.normal(0, scale * 0.3, (n, 2))
    else:
        # new notes start beside their linked neighbours
        nbrs: list[list[int]] = [[] for _ in range(n)]
        for a, b in edges:
            nbrs[a].append(b)
            nbrs[b].append(a)
        for i in np.where(~known)[0]:
            k = [j for j in nbrs[i] if known[j]]
            base = pos[k].mean(0) if k else rng.normal(0, scale * 0.3, 2)
            pos[i] = base + rng.normal(0, scale * 0.02, 2)
        if known.all() and iterations > 100:
            iterations = 100

    warm = known.any()
    kr, kg = 2.0, 0.6
    temp = scale * (0.02 if warm else 0.15)
    cool = (0.003 / (0.02 if warm else 0.15)) ** (1.0 / max(iterations, 1))
    mm = mass[:, None] * mass[None, :]

    for _ in range(iterations):
        d = pos[:, None, :] - pos[None, :, :]
        dist2 = (d * d).sum(-1) + 0.01
        # repulsion ∝ m_i m_j / d
        f = (kr * mm / dist2)[:, :, None] * d
        force = f.sum(1)
        # lin-log attraction along links
        e = pos[edges[:, 1]] - pos[edges[:, 0]]
        el = np.sqrt((e * e).sum(-1)) + 1e-6
        fa = (np.log1p(el) / el)[:, None] * e
        np.add.at(force, edges[:, 0], fa)
        np.add.at(force, edges[:, 1], -fa)
        # strong gravity weighted by mass pulls hubs toward the core
        r = np.sqrt((pos * pos).sum(-1)) + 1e-6
        force -= (kg * mass * np.log1p(r) / r)[:, None] * pos
        # displacement capped by temperature, scaled down for heavy nodes
        step = force / mass[:, None]
        sl = np.sqrt((step * step).sum(-1)) + 1e-9
        pos += step * (np.minimum(sl, temp) / sl)[:, None]
        temp *= cool

    return pos - (pos * mass[:, None]).sum(0) / mass.sum()


def _exp_disk_radius(t: np.ndarray, h: float) -> np.ndarray:
    """Invert the cumulative mass of an exponential disk truncated at r=1."""
    rs = np.linspace(0, 1, 2048)
    cum = 1 - (1 + rs / h) * np.exp(-rs / h)
    cum /= cum[-1]
    return np.interp(t, cum, rs)


def to_disk(graph: Graph, raw: np.ndarray, scale_h: float = 0.32) -> np.ndarray:
    """Map raw 2D positions onto a thin, warped 3D disk of radius ~1.

    Returns (n, 3) float32 positions with z as the disk normal.
    """
    n = len(graph.notes)
    out = np.zeros((n, 3), np.float32)
    if n == 0:
        return out
    archive = np.array([nt.archive for nt in graph.notes])
    r_raw = np.sqrt((raw * raw).sum(-1))
    theta = np.arctan2(raw[:, 1], raw[:, 0])
    seeds = np.array([_seed(nt.path) for nt in graph.notes], np.uint64)
    rng_vals = np.stack([
        ((seeds >> np.uint64(s)) & np.uint64(0xFFFF)).astype(np.float64) / 65535.0
        for s in (0, 16, 32, 48)
    ], 1)

    r = np.zeros(n)
    main = ~archive
    if main.any():
        rm = r_raw[main]
        order = rm.argsort().argsort()
        t = (order + 0.5) / main.sum()
        r_rank = _exp_disk_radius(t, scale_h)
        r_lin = np.clip(rm / np.percentile(rm, 98), 0, 1.15)
        r[main] = 0.55 * r_rank + 0.45 * r_lin
    if archive.any():
        ra = r_raw[archive]
        t = (ra.argsort().argsort() + 0.5) / archive.sum()
        r[archive] = 1.2 + 0.45 * t + 0.1 * rng_vals[archive, 0]

    # gaussian-ish vertical scatter from the hash, thicker with radius
    g = (rng_vals[:, 1] + rng_vals[:, 2] + rng_vals[:, 3] - 1.5) * 2.0
    thick = np.where(archive, 0.09, 0.008 + 0.022 * r)
    warp = 0.05 * np.clip(r - 0.35, 0, None) ** 2 * np.sin(theta + 0.8)
    out[:, 0] = r * np.cos(theta)
    out[:, 1] = r * np.sin(theta)
    out[:, 2] = g * thick + warp
    return out


class LayoutCache:
    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict[str, tuple[float, float]]:
        try:
            with open(self.path) as fh:
                return {k: tuple(v) for k, v in json.load(fh).items()}
        except (OSError, ValueError):
            return {}

    def save(self, graph: Graph, raw: np.ndarray) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        data = {nt.path: [round(float(x), 3), round(float(y), 3)]
                for nt, (x, y) in zip(graph.notes, raw)}
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)
