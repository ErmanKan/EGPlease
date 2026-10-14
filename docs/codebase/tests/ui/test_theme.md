# `tests/ui/test_theme.py`

> Tests for the dark-mode colour fixes in `ui/theme.py` and for their use in the transport bar and the Generate button, including contrast measured on rendered widgets.

## What it covers (16 test functions, 23 cases)
| Test | Checks |
|---|---|
| `test_contrast_ratio_known_values` | 21 : 1 black/white, 1 : 1 identical, symmetric |
| `test_mix_endpoints_and_midpoint` | `mix` at 0, 1 and 0.5 |
| `test_is_dark` | the dark test palette is dark, a light one is not |
| `test_tuned_palette_lifts_dark_buttons_off_the_window` | button fill ≥ 2 : 1 against the window (was below); disabled fill dimmer than enabled; disabled text ≥ 2.5 : 1 on it |
| `test_tuned_palette_never_darkens_and_leaves_light_alone` | an already light button is kept; a light palette is returned unchanged |
| `test_apply_starts_from_the_system_palette` | after a dark app palette, `apply` starts from the system palette (light offscreen); `install` twice is harmless |
| `test_media_icon_uses_the_button_text_colour` (× 6 kinds) | every opaque pixel is `ButtonText` (normal) or the disabled `ButtonText` (disabled mode); the shape is present |
| `test_media_icon_rejects_unknown_kind` | `ValueError` |
| `test_primary_colors_are_readable_for_any_accent` (× 7 accents) | text black or white, contrast ≥ 4.5 : 1, for Windows blue, Fusion blue, light cyan, yellow, dark blue, red, green |
| `test_mark_primary_follows_palette_changes` | style sheet contains the accent fill and changes when the app palette changes |
| `test_transport_buttons_framed_and_icons_follow_the_palette` | tool buttons not auto-raise; icon colour white in dark, dark in light, and kept across the play/pause swap |
| `test_rendered_dark_mode_buttons_are_visible` | grabs the real transport bar and settings panel under the tuned dark palette: fill ≥ 2 : 1 against the window, glyphs ≥ 4.5 : 1 on the fill, Generate text ≥ 4.5 : 1 |

## Fixtures and helpers
- `dark_palette(accent)`: an approximation of Qt's Windows dark palette (`#1E1E1E` window, button one step lighter, white text, Windows accent `#0078D4`, grey disabled text).
- `app_palette` fixture: yields the app and restores the system palette afterwards (`setPalette(QPalette())`).
- `set_app_palette(app, pal)`: `setPalette` **plus `processEvents()`**. For shown widgets Qt delivers the `PaletteChange` through the event loop; without the call the widgets still show the old colours when the assertion runs.
- `fill_and_glyph(widget)`: grabs the widget, samples the fill at the left edge inside the border, and returns the best contrast of any pixel against it (the text or icon).

## Gotchas
- Widgets whose palette reaction is tested must be **shown**: Qt sends no palette events to a widget that was never shown or polished.
- The offscreen platform's system palette is light, so "dark mode" is always simulated with an app palette. The live `colorSchemeChanged` path is not exercised.

## History
- Created 2026-10-14 with `ui/theme.py` ([dev log](../../../04-development-log.md#dark-mode-buttons)).
