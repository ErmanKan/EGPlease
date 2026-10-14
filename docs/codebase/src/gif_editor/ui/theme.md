# `src/gif_editor/ui/theme.py`

> Colour fixes on top of the system palette so buttons stay visible in Windows dark mode: lighter button fills, transport icons drawn in the text colour, and an accent-coloured Generate button with readable text.

## Where it sits
- **Layer:** ui (Qt: `QPalette`, `QIcon`, `QPainter`, style sheets)
- **Used by:** `app.py` (`install(app)` right after `setStyle("Fusion")`), `ui/inspector/transport.py` (`media_icon` for the five tool buttons), `ui/settings_panel.py` (`mark_primary(generate_button)`); `tests/ui/test_theme.py`.
- **Uses:** nothing in the project.

## Why it exists
The app uses Qt's **Fusion** style everywhere (see [app](../app.md)), and Fusion takes its colours from the system palette. In Windows dark mode that went wrong in three measurable ways (WCAG contrast ratios, measured on rendered widgets under a Windows-like dark palette):

| Problem | Before | After |
|---|---|---|
| Transport icons (Qt's built-in `SP_Media*` icons are dark grey glyphs) against the window | **1.17 : 1**, practically invisible; the buttons were also flat (auto-raise), so nothing showed | icons 6.0 : 1 on a framed button |
| Push-button fill against the window (the border is the window colour *darkened*, so near-black on near-black) | 2.0 : 1 | 2.77 : 1 |
| Disabled button text on its fill | 1.9 : 1 | 3.0 : 1 |
| Generate (new: accent fill). Fusion lightens and desaturates a palette-coloured button, so white text on it was only 2.2–2.4 : 1 | n/a | ≥ 4.5 : 1 in light and dark |

Light mode is unchanged apart from the accent-coloured Generate button.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `install(app)` | function | `apply(app)` now, and again (deferred one event-loop turn) on every `styleHints().colorSchemeChanged`. Idempotent per app. |
| `apply(app)` | function | Resets the app palette to the system one (`setPalette(QPalette())`), then sets `tuned_palette` of it. |
| `tuned_palette(base)` | function → `QPalette` | In a dark palette: lifts `Button` (all groups) and the disabled `ButtonText`. Light palettes come back unchanged. Only ever lightens. |
| `media_icon(kind, palette)` | function → `QIcon` | Vector transport icon (`"first"`, `"prev"`, `"play"`, `"pause"`, `"next"`, `"last"`) in `ButtonText`, with a disabled-mode variant, pre-rendered at 16–48 px. Unknown kind → `ValueError`. |
| `mark_primary(button)` | function | Accent-coloured style sheet on `button`, kept in sync with the palette; sets the `primary` property. |
| `primary_colors(palette)` | function → `(fill, text)` | The accent and black/white text with contrast ≥ `PRIMARY_MIN_CONTRAST`. |
| `primary_style_sheet(palette)` | function → `str` | The style sheet `mark_primary` applies (normal, hover, pressed, focus, disabled). |
| `contrast_ratio(a, b)`, `relative_luminance(c)`, `mix(a, b, t)`, `is_dark(palette)` | functions | WCAG colour maths and helpers. |
| `BUTTON_MIX`, `DISABLED_BUTTON_MIX`, `DISABLED_TEXT_MIX`, `PRIMARY_MIN_CONTRAST`, `ICON_SIZES`, `MEDIA_KINDS` | constants | Tuning values (see below). |

## How it works
- **Dark detection.** `is_dark` compares the luminance of `Window` and `WindowText`; no platform API, so it works for any dark palette, including high-contrast themes.
- **Button fill.** In dark mode the target fill is the window colour moved `BUTTON_MIX` = 22 % towards the text colour: Windows' `#1E1E1E` window gives `#4F4F4F`. Fusion then lightens it a little more when it paints (`#636363` on screen). Disabled buttons use 10 %, so they stay dimmer than enabled ones. If the system button is already lighter than the target, it is kept.
- **Disabled text.** 55 % from the window towards the text colour (about `#999999`): dim, but readable at about 3 : 1 on the disabled fill.
- **Following the system.** `apply` resets the app palette before tuning. Setting an empty `QPalette` makes Qt resolve every role from the system palette again; without the reset, a light/dark switch would start from the previously tuned colours and Qt would keep the explicitly set dark `Button` in light mode. The scheme signal can arrive before Qt has loaded the new system palette, so `install` defers `apply` with `QTimer.singleShot(0, ...)`.
- **Media icons.** Each icon is a `QPainterPath` on a 16 × 16 grid (single triangle + bar for frame steps, double triangle + bar for first/last, two bars for pause), filled with antialiasing in `palette.ButtonText` (normal mode) and the disabled `ButtonText` (disabled mode). Pixmaps are added at 16, 20, 24, 32 and 48 px so `QIcon` picks a sharp one at 100–300 % scaling.
- **Primary button.** A style sheet with explicit colours rather than a palette colour, because Fusion transforms palette button colours (lighter, less saturated) before painting. `primary_colors` picks black or white text, whichever contrasts more with the accent, then mixes the fill away from the text in 5 % steps until the contrast reaches 4.5 : 1. Hover is 12 % towards the text colour, pressed is 15 % away from it, keyboard focus is a 2 px border in `WindowText`, and disabled uses the palette's disabled button colours.
- **Refreshing.** Widgets holding palette-derived colours update on `QEvent.PaletteChange`: the transport bar in `changeEvent`, the primary button through a small event filter (`_PrimaryRefresher`, parented to the button) that re-applies the style sheet only when it changed. Applying a style sheet re-polishes the button, which sends another `PaletteChange`; the unchanged sheet ends that loop.

## Invariants & gotchas
- **React to `PaletteChange`, not `ApplicationPaletteChange`.** Measured: Qt sends `ApplicationPaletteChange` only to **top-level windows**, and **before** their palette is updated. `PaletteChange` reaches every widget, with the new palette already in place.
- Qt sends **no** palette events to a widget that was never shown or polished; its palette is resolved when it is. For shown widgets the change is delivered through the event loop, so tests must `processEvents()` after `setPalette` (see the test page).
- Don't call `app.setPalette` elsewhere: `apply` resets it on every scheme change.
- New icons for dark mode: draw them in a palette colour and rebuild them on `PaletteChange`. `QStyle.standardIcon` media icons are dark grey in Fusion and vanish on dark backgrounds.
- The real Windows dark palette can't be produced in the container (the offscreen platform's system palette is light). The tests use an approximation of Qt's Windows dark palette; the final check is a look at the app in Windows dark mode.

## Tests
- `tests/ui/test_theme.py`: colour maths, `tuned_palette` (lifts dark, never darkens, light untouched), `apply` resets to the system palette, icon colours per mode, unknown kind, readable primary colours for 7 accents, `mark_primary` follows a palette change, transport buttons framed with icons following light ↔ dark, and **rendered** contrast of real buttons under the dark palette.
- **Gaps:** the live `colorSchemeChanged` path (needs a real platform theme); the actual Windows dark palette.

## History
- Created 2026-10-14 after the user reported buttons almost invisible in dark mode. See [dev log](../../../../04-development-log.md#dark-mode-buttons).
