# `scripts/fuzz_decoder.py`

> A manual M4 fuzzer (not part of the test suite): damages every corpus GIF in random ways, opens each damaged file with `GifSource` and renders every frame. The decoder may refuse a file or load it with warnings; any other exception, or a hang, is a bug.

## Where it sits
- **Layer:** tooling (pure Python, no Qt; run by hand)
- **Used by:** contributors, after changes to `core/decoder.py`.
- **Uses:** `core/decoder.py` (`GifSource`, `GifLoadError`), `tests/corpus.py` (`build_all`); `signal.SIGALRM` (POSIX only).

## Public API
```bash
PYTHONPATH=src:tests .venv/bin/python scripts/fuzz_decoder.py [cases-per-file] [seed]
```
| Argument | Default | Meaning |
|---|---|---|
| `cases-per-file` | 200 | Damaged variants made from each corpus file. |
| `seed` | 1 | Seed of the `random.Random` that picks every mutation, so a run is reproducible. |

Exit code 0 if there were no unexpected failures, 1 otherwise. No Qt is imported, so no `LD_LIBRARY_PATH` is needed.

Output: the total count and time, a table of outcomes (`loaded`, `loaded with warnings`, `refused (GifLoadError)`, `HANG`, `BUG <ExceptionType>`), the slowest case, and up to 30 lines describing unexpected failures (or "no unexpected failures").

## How it works
1. `build_all(out/fuzz/corpus)` writes the 13-entry test corpus ([corpus page](../tests/corpus.md)); files shorter than 8 bytes are skipped.
2. For each corpus file, `cases-per-file` times: `mutate(data, rng)` picks one damage type and returns `(name, damaged bytes)`:

| Mutation | What it does | What it imitates |
|---|---|---|
| `flip` | 1–4 random bytes replaced | bit rot, a bad sector |
| `flip_many` | 5–60 random bytes replaced | heavier corruption |
| `truncate` | cut at a random length (≥ 6 bytes) | an unfinished download |
| `junk` | 1–200 random bytes inserted at a random place | a broken editor or transfer |
| `header` | up to 3 of bytes 6–12 (logical screen width/height, flags, background, aspect) replaced | the most sensitive bytes: they set the canvas size and the global colour table |
| `zero_run` | 1–64 bytes zeroed | a zero-filled block on disk |
| `dup` | a slice of up to 300 bytes repeated | duplicated blocks, broken sub-block chains |

3. The damaged bytes are written to `out/fuzz/case.gif` (overwritten each time). With `signal.alarm(10)` armed, it opens the file, calls `frame(i)` for every frame in order, then about four frames again out of order (to exercise the cache and checkpoint paths), and closes it.
4. Outcome: `loaded` / `loaded with warnings` (`src.warnings` non-empty) / `refused (GifLoadError)` are all **acceptable**. A `Hang` (the alarm fired after 10 s) or any other exception is a bug: the file is kept as `out/fuzz/hang-<name>-<k>.gif` or `out/fuzz/bug-<name>-<k>.gif` so it can be reproduced and turned into a test.

*Why this matters:* the decoder is our own parser ([decoder page](../src/gif_editor/core/decoder.md)), and GIFs come from the internet. A damaged file must never crash the app, hang it, or raise something other than `GifLoadError` (which the UI explains in plain words via `ui/messages.py`). The hand-written corpus covers the known edge cases; the fuzzer finds the unknown ones.

## Results (end of M4)
**22,750 damaged files** in total over seeds 1–3: about **59 %** refused with `GifLoadError`, **28 %** loaded with warnings, **13 %** loaded cleanly; **0 unexpected exceptions, 0 hangs**. The slowest case took **711 ms**: a damaged header that declared a large canvas. (These figures are from the orchestrator's runs; the per-seed `cases-per-file` values were not recorded.)

## Invariants & gotchas
- **POSIX only** (`SIGALRM`): it runs in the Linux container, not on Windows.
- Writes only inside `out/fuzz/` (gitignored). Never point it at `/tmp`.
- A "loaded" result is not checked for correct pixels (there is no reference for random damage); the point is "no crash, no hang, no unexpected exception type".
- `alarm` interrupts Python code only; a hang inside a C call that never returns to Python would not be caught. None was seen.

## Tests
- n/a (a fuzzing tool). Bugs it finds should become regular tests in `tests/core/test_decoder_corpus.py`.

## History
- `c254cc1` (M4): added ([dev log, Milestone 4](../../04-development-log.md#milestone-4-hardening)).
