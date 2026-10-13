# Documentation index

Start here. Read in this order if you are new to the codebase.

| Doc | What it tells you |
|---|---|
| [00-brief.md](00-brief.md) | The product idea and the intake answers |
| [01-research.md](01-research.md) | Prior art, stack options, risks, UX patterns (with sources) |
| [02-plan.md](02-plan.md) | Vision, MVP scope, timing model, architecture, milestones |
| [03-architecture.md](03-architecture.md) | How the code is organised *today*: layers, data flow, threading |
| [04-development-log.md](04-development-log.md) | How the project was built, step by step: decisions, review findings, fixes |
| [05-gif-primer.md](05-gif-primer.md) | GIF format concepts the code relies on (palettes, disposal, delays, LZW) |
| [06-testing.md](06-testing.md) | How tests are organised and run, the GIF corpus, headless Qt, the packaging checks (flags, icons, build + smoke test) |
| [codebase/](codebase/) | **One page per source/test/script file** (mirrors the repo tree) |

## The per-file pages (`docs/codebase/`)

Every file in `src/`, `tests/` and `scripts/` has a page at the same relative path, with `.md` appended to the file name minus its extension.
Example: `src/gif_editor/core/timeline.py` → [`codebase/src/gif_editor/core/timeline.md`](codebase/src/gif_editor/core/timeline.md).
Each page follows [`codebase/_TEMPLATE.md`](codebase/_TEMPLATE.md): purpose, where it sits, public API, how it works, invariants and gotchas, tests, history.

[`codebase/INDEX.md`](codebase/INDEX.md) lists every file with a one-line summary.
