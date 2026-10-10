# `tests/ui/test_settings_panel.py`

> pytest-qt tests for `SettingsPanel`: controls ↔ `EditState` mapping, undo merging, feedback-loop safety, summary card and the Generate button.

## Where it sits
- **Layer:** tests
- **Used by:** `scripts/test.sh` / pytest.
- **Uses:** `src/gif_editor/ui/settings_panel.py`, `ui/document.py`, `core/models.py`; fixtures `doc` and `gif_path` from `tests/ui/conftest.py` (8 solid frames, 40×30, 100 ms each → 0.80 s).

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `panel` | fixture | A `SettingsPanel` over the open `doc`, registered with `qtbot` for cleanup. |
| `test_*` | tests | See below. |

## How it works
Tests drive the real child widgets (`setValue`, `setChecked`, `click`, `activated.emit`) exactly as user input would, then assert on `doc.state`, `doc.undo_stack` and the widgets. Calling `setValue` emits `valueChanged` just like typing+Enter or an arrow click, so no event simulation is needed; `qtbot.mouseClick` is used for the Generate button to prove the signal path through a real click. For quality presets the test emits `QComboBox.activated` because the panel listens to that signal (user picks only), not `currentIndexChanged`.

| Test | Checks |
|---|---|
| `test_initial_values_reflect_default_state` | Every control matches `EditState()` and the source (40×30, 0.80 s); width hint 280. |
| `test_speed_changes_merge_into_one_undo_step` | Four speed edits → one undo command; slider follows. |
| `test_speed_slider_syncs_spinbox` | Slider writes speed and updates the spin. |
| `test_undo_restores_controls_without_new_commands` | After two undos the controls show defaults and the stack still has 2 commands at index 0 (no feedback loop). |
| `test_to_end_toggles_duration_none` | "to end" ↔ `trim_duration_ms is None`, spin enabled state. |
| `test_start_time_and_duration_clamped` | Too-long duration is clamped to the remainder. |
| `test_fps_checkbox_maps_to_none_or_value` | FPS `None` ↔ value; spin changes ignored while unchecked. |
| `test_aspect_lock_keeps_ratio` / `test_aspect_unlocked_changes_one_side` / `test_aspect_uses_crop_as_base` | Lock behaviour and base size (canvas vs crop). |
| `test_scale_and_reset` | Scale % sets size; Reset sets `None`. |
| `test_preset_sets_quality_and_editing_switches_to_custom` | Preset → colours/dither; edit → Custom; matching values → preset again. |
| `test_summary_shows_output_and_updates` | Output frame count text, updated after `doc.delete_frames`. |
| `test_empty_output_disables_generate` | 0 output frames → empty message, Generate disabled. |
| `test_invalid_edit_reverted_and_reported` | `ValueError` from `apply` reverts the control and shows the message. |
| `test_generate_signal` | Click emits `generateRequested`. |
| `test_generate_disabled_after_close` | `doc.close()` disables groups and Generate. |
| `test_empty_document_everything_disabled` | A `Document()` with no source builds, is fully disabled, and forced edits push nothing. |

## Invariants & gotchas
- Must run with `QT_QPA_PLATFORM=offscreen` and the project-local libEGL (`scripts/test.sh`).
- Expected strings contain `×` via `settings_panel.TIMES` to keep ruff's ambiguous-character rule quiet.

## Tests
- This file is the test. Gaps: no pixel/visual checks of the summary colours or layout in a scroll area.

## History
- Milestone 2: created with the settings panel.
