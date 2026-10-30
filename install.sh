#!/usr/bin/env bash
# Astral Palace installer: sets up the Python environment, optionally points it at
# your vault, and optionally installs the Omarchy theme + hooks.
#
#   ./install.sh                         # demo vault, no theme
#   ./install.sh --vault ~/Notes/Vault   # your own vault
#   ./install.sh --omarchy               # also install the Omarchy theme and hooks
#   ./install.sh --omarchy --chromium-force-dark
#
# Re-running is safe: existing config, theme and venv are kept unless you pass --force.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/astral-palace"
VAULT="" OMARCHY=0 FORCE_DARK=0 FORCE=0

while (($#)); do
  case $1 in
    --vault) VAULT="$2"; shift ;;
    --omarchy) OMARCHY=1 ;;
    --chromium-force-dark) FORCE_DARK=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\033[38;2;240;184;113m✦\033[0m %s\n' "$*"; }
fail() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# --- system dependencies --------------------------------------------------------
missing=()
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null || missing+=("python >= 3.11")
python3 - 2>/dev/null <<'PY' || missing+=("GTK 4 + gtk4-layer-shell GObject bindings (python-gobject, gtk4, gtk4-layer-shell)")
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import Gtk, Gtk4LayerShell
PY
command -v inotifywait >/dev/null || missing+=("inotifywait (inotify-tools)")
command -v gdbus >/dev/null || missing+=("gdbus (glib2)")
if ((${#missing[@]})); then
  echo "Missing system dependencies:"; printf '  - %s\n' "${missing[@]}"
  cat <<'EOF'

  Arch:          sudo pacman -S python-gobject gtk4 gtk4-layer-shell inotify-tools
  Fedora:        sudo dnf install python3-gobject gtk4 gtk4-layer-shell inotify-tools
  Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-gtk4layershell-1.0 inotify-tools
EOF
  exit 1
fi
say "system dependencies OK"

# --- python environment ---------------------------------------------------------
# system site-packages so the venv can see the distro's GObject bindings
if [[ ! -x $REPO/.venv/bin/python ]]; then
  python3 -m venv --system-site-packages "$REPO/.venv"
fi
if command -v uv >/dev/null; then
  uv pip install -q -p "$REPO/.venv/bin/python" -r "$REPO/requirements.txt"
else
  "$REPO/.venv/bin/python" -m pip install -q -r "$REPO/requirements.txt"
fi
say "python environment ready (.venv)"

# --- config -----------------------------------------------------------------------
if [[ -n $VAULT ]]; then
  VAULT="$(cd "${VAULT/#\~/$HOME}" && pwd)" || fail "vault not found: $VAULT"
  if [[ -f $CONFIG_DIR/config.toml && $FORCE == 0 ]]; then
    say "keeping existing $CONFIG_DIR/config.toml (use --force to replace)"
  else
    mkdir -p "$CONFIG_DIR"
    printf '[vault]\npath = "%s"\n' "$VAULT" >"$CONFIG_DIR/config.toml"
    say "vault set to $VAULT"
  fi
fi

# --- omarchy theme + hooks ----------------------------------------------------------
if ((OMARCHY)); then
  command -v omarchy >/dev/null || fail "--omarchy given but the omarchy command isn't available"
  theme_dir="$HOME/.config/omarchy/themes/astral-palace"
  if [[ -d $theme_dir && $FORCE == 0 ]]; then
    say "keeping existing theme at $theme_dir (use --force to replace)"
  else
    rm -rf "$theme_dir"
    mkdir -p "$(dirname "$theme_dir")"
    cp -r "$REPO/theme/astral-palace" "$theme_dir"
    say "theme installed: Astral Palace"
  fi
  # render the hook template (repo path, options), then let omarchy install it
  tmp=$(mktemp -d)
  hook="$tmp/astral-palace-galaxy"
  sed -e "s|@REPO@|$REPO|" -e "s|@FORCE_DARK@|$FORCE_DARK|" "$REPO/hooks/astral-palace-galaxy" >"$hook"
  chmod +x "$hook"
  omarchy hook install theme-set "$hook" >/dev/null
  omarchy hook install post-boot "$hook" >/dev/null
  rm -rf "$tmp"
  say "hooks installed: the galaxy runs while Astral Palace is the active theme"
fi

# --- next steps ---------------------------------------------------------------------
cat <<EOF

Next:
  Run it now:          $REPO/bin/astral-palace
EOF
if ((OMARCHY)); then
  echo "  Apply the theme:     omarchy theme set \"Astral Palace\""
else
  echo "  Start at login:      add  exec-once = $REPO/bin/astral-palace  to your compositor's autostart"
fi
cat <<EOF
  Search shortcut:     bind a key to  $REPO/bin/astral-palace-search
                       Hyprland (Lua): o.bind("SUPER + PERIOD", "Galaxy search", "$REPO/bin/astral-palace-search")
                       Hyprland:       bind = SUPER, PERIOD, exec, $REPO/bin/astral-palace-search
                       Sway:           bindsym \$mod+period exec $REPO/bin/astral-palace-search
EOF
