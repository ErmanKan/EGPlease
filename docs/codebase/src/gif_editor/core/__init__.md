# `src/gif_editor/core/__init__.py`

> Package marker for the pure-Python GIF engine. Its docstring is the only content: "Pure-Python GIF engine (no Qt)."

## Where it sits
- **Layer:** core
- **Used by:** every `gif_editor.core.*` import.
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| (none) | | It re-exports nothing; import from the submodules (`gif_editor.core.decoder`, etc.). |

## How it works
An empty package. The modules are:

| Module | Role |
|---|---|
| [`models`](models.md) | `EditState` and its value types |
| [`decoder`](decoder.md) | `GifSource`: parse, composite, cache |
| [`timeline`](timeline.md) | `plan_output`: which frames, which delays |
| [`render`](render.md) | crop, resize, palette, quantize |
| [`encoder`](encoder.md) | `write_gif`: lossless diff frames, atomic |
| [`pipeline`](pipeline.md) | glue: summary, generate, PNG export |
| [`selftest`](selftest.md) | Pillow-internals round trip |

## Invariants & gotchas
- **No Qt imports anywhere under `core/`** (AGENTS.md architecture rule). This keeps the engine unit-testable without a display, and the tests run with `-p no:pytest-qt`.

## Tests
- None directly.

## History
- `7a7b418`: scaffold.
