# `tests/ui/test_messages.py`

> Tests for `ui/messages.py`: every error the user can hit maps to a plain-language explanation, with the technical text kept as details and no jargon in the visible part.

## Where it sits
- **Layer:** tests (pure functions; lives in `tests/ui/` because `messages.py` is a ui module, so the autouse `_drain_workers` fixture also gives it a `QApplication` it does not need)
- **Used by:** pytest.
- **Uses:** `ui/messages.py`, `core/decoder.py` (`GifLoadError`, `GifSource`, `Limits`), `tests/corpus.py` (`build_all`).

## Public API
| Test | Verifies |
|---|---|
| `test_not_a_gif` | The corpus `not_a_gif` file raises `kind == NOT_GIF`; headline is exactly "“name” is not a GIF."; `details == str(err)`; no jargon. |
| `test_empty_file` | A 0-byte file → `EMPTY` → "empty (0 bytes)". |
| `test_missing_file` | A missing path → `NOT_FOUND` → "no longer exists". |
| `test_folder` | A folder named `dir.gif` → `IS_DIRECTORY` → "is a folder". |
| `test_too_large_header` | The corpus `large_canvas_header` (20000×20000) → `TOO_LARGE` with `info["width"] == 20000`; headline "too large to edit (20000×20000 pixels)", body "pixels on a side"; no jargon. |
| `test_too_large_side` | `Limits(max_canvas_side=4)` on an ordinary file → `TOO_LARGE`; body names "4 pixels on a side". |
| `test_too_many_frames` | `Limits(max_frames=2)` → `TOO_MANY_FRAMES`; body "up to 2 frames". |
| `test_header_only_is_damaged` | A valid 13-byte header plus trailer, no frames → `MALFORMED` → "is damaged"; no jargon. |
| `test_unknown_error_keeps_details` | `RuntimeError("boom")` → "could not be opened", details "boom"; an empty message falls back to the class name. |
| `test_memory_error` | `MemoryError` while loading → headline mentions memory. |
| `test_load_warnings` | The corpus `truncated` file: headline "N frames could be loaded" with the real frame count, details = the warnings joined by newlines; singular "1 frame could"; no jargon. |
| `test_generate_errors` (8 cases) | `EACCES` and `EPERM` → "No permission to save"; `ENOSPC` → "disk is full"; `ENOENT` → "no longer exists"; `ENAMETOOLONG` → "too long"; `EIO` → "could not be saved"; `MemoryError` → "Not enough memory"; `RuntimeError` → "could not be generated". Every body contains "Nothing was written", the title is "Generate failed", details are non-empty, no jargon. |
| `test_windows_locked_file_is_not_called_a_permission_problem` | A `PermissionError(EACCES)` with `winerror = 32` → "“out.gif” is open in another program." (not "No permission"). |
| `test_custom_title_for_save_frame` | `title="Save failed"` is used. |
| `test_text_joins_headline_and_body` | `Explanation.text` is "Head.\nBody.", or just the headline when the body is empty. |

## How it works
Load errors are produced the real way where possible: a file is written (or a corpus entry used) and opened with `GifSource.open`, and the raised `GifLoadError` is passed to `explain_load_error`. That tests the decoder's `kind` assignment and the wording together. Generate errors are constructed directly (`OSError(errno.X, ...)`), because provoking a full disk or a Windows sharing violation in a test is not practical.

`JARGON = ("Errno", "malformed", "decodable", "exceeds", "pixels exceeds", "Traceback")`; `_assert_plain` checks that none of these appear in the headline or body.

## Invariants & gotchas
- 22 cases (15 functions; `test_generate_errors` is parametrized with 8 cases). The module-scoped `corpus` fixture writes the corpus once for the file.
- The `winerror` attribute is set by hand on a Linux `PermissionError`; on Windows the OS sets it.

## Tests
- **Gaps:** the `UNREADABLE` branch (an existing file that cannot be read); `winerror` 33 (lock violation).

## History
- `95b4f03` (M4): added with `ui/messages.py`.
