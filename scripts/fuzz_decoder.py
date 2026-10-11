"""Fuzz the GIF decoder with randomly damaged files (M4 hardening; not part of the suite).

Takes every corpus GIF, damages it in several ways (flip random bytes, cut it short, splice
in junk, overwrite header fields), then opens it with GifSource and renders every frame.
The decoder may refuse a file (GifLoadError) or load it with warnings. Anything else (any
other exception, a hang) is a bug. Prints a summary and every unexpected failure.

Usage: PYTHONPATH=src:tests .venv/bin/python scripts/fuzz_decoder.py [cases-per-file] [seed]
"""

from __future__ import annotations

import random
import signal
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from corpus import build_all
from gif_editor.core.decoder import GifLoadError, GifSource

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "out" / "fuzz"  # inside the project, gitignored


class Hang(Exception):
    pass


def _alarm(_sig, _frame):
    raise Hang


def mutate(data: bytes, rng: random.Random) -> tuple[str, bytes]:
    b = bytearray(data)
    how = rng.choice(["flip", "flip_many", "truncate", "junk", "header", "zero_run", "dup"])
    if how == "flip":
        for _ in range(rng.randint(1, 4)):
            b[rng.randrange(len(b))] = rng.randrange(256)
    elif how == "flip_many":
        for _ in range(rng.randint(5, 60)):
            b[rng.randrange(len(b))] = rng.randrange(256)
    elif how == "truncate":
        b = b[: rng.randrange(6, max(7, len(b)))]
    elif how == "junk":
        at = rng.randrange(len(b))
        b[at:at] = bytes(rng.randrange(256) for _ in range(rng.randint(1, 200)))
    elif how == "header":  # logical screen size/flags, the most sensitive bytes
        for i in rng.sample(range(6, min(13, len(b))), k=min(3, max(0, len(b) - 6))):
            b[i] = rng.randrange(256)
    elif how == "zero_run":
        at = rng.randrange(len(b))
        n = rng.randint(1, 64)
        b[at : at + n] = bytes(min(n, len(b) - at))
    elif how == "dup":  # repeat a slice (duplicated blocks, broken sub-block chains)
        a = rng.randrange(len(b))
        z = min(len(b), a + rng.randint(1, 300))
        b[z:z] = b[a:z]
    return how, bytes(b)


def main() -> int:
    per_file = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    WORK.mkdir(parents=True, exist_ok=True)
    corpus = build_all(WORK / "corpus")
    signal.signal(signal.SIGALRM, _alarm)
    outcomes: Counter[str] = Counter()
    bad: list[str] = []
    slowest = (0.0, "")
    target = WORK / "case.gif"
    t_all = time.time()
    for name, (path, _expected) in corpus.items():
        data = path.read_bytes()
        if len(data) < 8:
            continue
        for k in range(per_file):
            how, mutated = mutate(data, rng)
            target.write_bytes(mutated)
            t0 = time.time()
            signal.alarm(10)
            try:
                with GifSource.open(target) as src:
                    for i in range(src.meta.frame_count):
                        src.frame(i)
                    for i in range(0, src.meta.frame_count, max(1, src.meta.frame_count // 4)):
                        src.frame(i)  # random access after sequential (cache paths)
                outcomes["loaded with warnings" if src.warnings else "loaded"] += 1
            except GifLoadError:
                outcomes["refused (GifLoadError)"] += 1
            except Hang:
                outcomes["HANG"] += 1
                bad.append(f"{name}#{k} {how}: hang > 10 s")
                (WORK / f"hang-{name}-{k}.gif").write_bytes(mutated)
            except Exception as exc:
                outcomes[f"BUG {type(exc).__name__}"] += 1
                if len(bad) < 30:
                    bad.append(f"{name}#{k} {how}: {type(exc).__name__}: {exc}")
                    bad.append("    " + traceback.format_exc().strip().splitlines()[-3].strip())
                (WORK / f"bug-{name}-{k}.gif").write_bytes(mutated)
            finally:
                signal.alarm(0)
            dt = time.time() - t0
            if dt > slowest[0]:
                slowest = (dt, f"{name}#{k} {how}")
    total = sum(outcomes.values())
    print(f"{total} damaged files in {time.time() - t_all:.0f} s (seed {seed})")
    for k, v in outcomes.most_common():
        print(f"  {k:28s} {v}")
    print(f"  slowest case: {slowest[0] * 1000:.0f} ms ({slowest[1]})")
    print("\n".join(bad) if bad else "no unexpected failures")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
