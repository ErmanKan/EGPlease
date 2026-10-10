# `tests/gifgen.py`

> Small helpers that build simple animated GIFs with Pillow, for tests that don't need exotic GIF structures.

## Where it sits
- **Layer:** tests (helper module)
- **Used by:** `tests/ui/conftest.py`, `tests/core/test_pipeline.py` (as `gifgen`), `tests/core/test_decoder.py` (as `tests.gifgen`).
- **Uses:** Pillow.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `PALETTE` | list of 8 RGB | red, green, blue, yellow, cyan, magenta, white, black. |
| `solid_frames(n, size=(16, 12))` | function | `n` RGB frames; frame `i` is solid `PALETTE[i % 8]`. |
| `make_gif(path, frames, durations=100, *, loop=0, disposal=1, transparency=None)` | function | Write with Pillow `save_all` (`optimize=False`) and return `path`. `durations` and `disposal` may be an int or a per-frame list; `loop=None` omits the loop block. |

## How it works
A thin wrapper over `Image.save(save_all=True, append_images=...)`. `optimize=False` stops Pillow from shrinking the palette, so the colours stay predictable.

**gifgen vs corpus:** gifgen writes *ordinary* GIFs through Pillow's writer, which is quick to read and fine for metadata, cache and pipeline tests. `tests/corpus.py` writes *exact bytes* for edge cases that Pillow cannot produce and carries an independent reference compositor. See [06-testing.md](../../06-testing.md#gifgen-vs-the-corpus).

## Invariants & gotchas
- Pillow's writer may crop later frames to a delta rectangle and merge identical consecutive frames. `solid_frames` uses distinct colours, so every frame survives.
- Two import spellings are in use (`from gifgen import …` and `from tests.gifgen import …`). Both work because `tests` is on `pythonpath` and is also a package, but the module is then imported twice under two names. That is harmless, since it has no state.

## Tests
- None of its own; it is exercised by every test that uses it.

## History
- `7a7b418`: scaffold (unchanged since).
