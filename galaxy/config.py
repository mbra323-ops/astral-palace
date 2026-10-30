"""Defaults, overridable from ~/.config/astral-palace/config.toml."""

from __future__ import annotations

import copy
import hashlib
import os
import tomllib

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_VAULT = os.path.join(REPO_DIR, "demo-vault")

DEFAULTS = {
    "vault": {
        "path": DEMO_VAULT,      # point this at your own vault
        "name": "",              # Obsidian's vault name; "" = the folder name
        "archive_prefix": "",    # "" = any top-level folder with "archive" in its name
    },
    "camera": {
        "distance": 2.1,
        "zoom_min_distance": 1.0,   # scroll-zoom limits (smaller = closer)
        "zoom_max_distance": 6.0,
        "focus_distance": 0.6,      # how close search flies the camera to a note
        "fov_deg": 24.0,
        "target_z": 0.0,
        "center_x": 0.5,          # galaxy centre across the whole desktop (0..1)
        "center_y": 0.5,
        "azimuth_deg": 0.0,
        "elevation_deg": 11.0,
        "elevation_swing_deg": 4.0,
        "elevation_period": 420.0,
        "spin_period": 720.0,     # seconds per full revolution
        "wobble_deg": 3.5,
        "wobble_period": 260.0,
    },
    "render": {
        "exposure": 1.0,
        "bloom_strength": 0.9,
        "bloom_level_weights": [1.0, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65],
        "line_width": 1.15,
        "line_intensity": 0.026,
        "line_hover_intensity": 0.5,
        "line_color": [1.0, 0.78, 0.5],
        "line_hover_color": [1.0, 0.85, 0.6],
        "dust_differential": 0.003,
        "idle_fps": 30,           # frame rate when nothing is being interacted with
        "active_linger": 1.5,     # seconds of full frame rate after the last interaction
    },
    "dust": {
        "per_note": 14,
        "bound_intensity": 0.012,
        "haze_count": 70000,
        "haze_intensity": 0.028,
        "filament_count": 90000,
        "filament_intensity": 0.5,
        "halo_count": 8000,
        "dusk_count": 45000,
        "dusk_intensity": 0.009,
    },
    "color": {
        "blue_star_fraction": 0.3,       # share of outer-disk minor notes that burn blue
        "blue_filament_fraction": 0.2,
    },
    "background": {
        "glow": 0.7,                     # faint light that reaches the screen edges
        "nebula": 0.8,                   # wispy dusk-blue clouds in the deep sky
    },
    "sky": {
        "count": 6000,
        "intensity": 1.0,
    },
    "behaviour": {
        "pause_when_covered": True,
        "pick_radius": 14.0,
        "layer": "bottom",
        "focus_obsidian": True,
        "peek_timeout": 120,        # search/peek sinks back behind windows after this idle time (s)
        "obsidian_class": "md.obsidian.Obsidian",
    },
}

def _xdg(var: str, fallback: str) -> str:
    return os.path.join(os.environ.get(var) or os.path.expanduser(fallback), "astral-palace")


CONFIG_PATH = os.path.join(_xdg("XDG_CONFIG_HOME", "~/.config"), "config.toml")
CACHE_DIR = _xdg("XDG_CACHE_HOME", "~/.cache")
# runtime state (where you dragged/zoomed the galaxy); overrides camera.center_x/y
STATE_PATH = os.path.join(_xdg("XDG_STATE_HOME", "~/.local/state"), "state.json")


def layout_cache_path(vault_path: str) -> str:
    """One layout cache per vault, so switching vaults never throws a layout away."""
    key = hashlib.blake2b(os.path.realpath(vault_path).encode(), digest_size=6).hexdigest()
    return os.path.join(CACHE_DIR, f"layout-{key}.json")


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path: str = CONFIG_PATH) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(path, "rb") as fh:
            _merge(cfg, tomllib.load(fh))
    except FileNotFoundError:
        pass
    v = cfg["vault"]
    v["path"] = os.path.abspath(os.path.expanduser(v["path"]))
    v["name"] = v["name"] or os.path.basename(v["path"].rstrip("/"))
    return cfg
