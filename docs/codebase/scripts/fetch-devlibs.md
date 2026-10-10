# `scripts/fetch-devlibs.sh`

> Downloads Debian's `libegl1` package and unpacks it into the gitignored `.devlibs/`, so PySide6 can load in the dev container. Nothing is installed system-wide.

## Where it sits
- **Layer:** tooling (bash)
- **Used by:** `scripts/test.sh` (automatically, when `libEGL.so.1` is missing).
- **Uses:** `curl`, `sha256sum`, `dpkg-deb` from the container, and the network (`deb.debian.org`).

## Public API
| Usage | Effect |
|---|---|
| `scripts/fetch-devlibs.sh` | Ensures `.devlibs/debs/libegl1_1.7.0-1+b2_amd64.deb` exists and matches the pinned SHA-256, then re-extracts it to `.devlibs/root/` and prints the extracted library names. |

Pinned values: `PKG=libegl1`, `VER=1.7.0-1+b2`, `SHA256=62e7bc8c…12406`, URL under `pool/main/libg/libglvnd/`.

## How it works
1. `cd` to the repo root and create `.devlibs/debs`.
2. Download the `.deb` only if it is not cached (`curl -fsSL`).
3. **Verify** it: `sha256sum -c` against the pinned hash. A mismatch aborts (`set -e`).
4. Delete `.devlibs/root` and extract with `dpkg-deb -x`. That only unpacks the files: no maintainer scripts run, no dpkg database changes, no root needed.
5. `scripts/test.sh` then puts `.devlibs/root/usr/lib/x86_64-linux-gnu` on `LD_LIBRARY_PATH`.

### Trust chain
The header comment describes the chain as: Debian archive key (local keyring) → signed `InRelease` → `Packages` index hash → package SHA-256.

**What the script itself enforces is only the last link: the pinned SHA-256.** The earlier links (checking `InRelease`'s signature with the Debian archive keyring and finding the package's hash in the signed `Packages` index) were done **once, by hand, when the hash was pinned** (dev log, `cc9f0fa`, "with the user's approval"). After that, the pinned hash is the trust anchor: any change to the file on the mirror makes the script fail. To bump the version, repeat the manual verification and update `VER` and `SHA256` together.

## Invariants & gotchas
- **Workers must not add other system libraries** (AGENTS.md). If Qt needs another `.so`, request it as `packages_needed` and let the orchestrator vet it.
- `libegl1` is the GLVND dispatcher. On the `offscreen` platform it only has to be loadable; no GPU or display is used.
- `.devlibs/` is gitignored, so no binaries enter the repo.
- Linux amd64 only. Not needed on Windows, where Qt ships what it needs.

## Tests
- Indirectly: `tests/ui/test_smoke.py` fails if the library is missing or broken.

## History
- `cc9f0fa`: added ([dev log](../../04-development-log.md#headless-qt-cc9f0fa)).
