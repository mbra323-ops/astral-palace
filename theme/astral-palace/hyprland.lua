-- Astral Palace: hand-written so the theme can also dim unfocused windows
-- (a white browser page behind your focus stops glaring). Switching to any
-- other theme drops these settings again.
local active_border_color = "rgb(d8b890)"      -- accent amber at ~60 percent saturation
local inactive_border_color = "rgba(3a3d4a99)" -- slate, barely there

hl.config({
  general = {
    col = {
      active_border = active_border_color,
      inactive_border = inactive_border_color,
    },
  },

  group = {
    col = {
      border_active = active_border_color,
      border_inactive = inactive_border_color,
    },
  },

  decoration = {
    dim_inactive = true,
    dim_strength = 0.12,
  },
})
