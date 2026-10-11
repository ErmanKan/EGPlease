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
The header comment says what the script verifies (the package's SHA-256 against the pin) and how the pin was obtained: Debian archive key → `sqv --message` on the signed `InRelease` → `Packages` index hash → the package SHA-256 listed there.

**What the script itself enforces is only the last link: the pinned SHA-256.** The earlier links were verified **once, by hand, when the hash was pinned** (dev log, `cc9f0fa`, "with the user's approval"). After that, the pinned hash is the trust anchor: any change to the file on the mirror makes the script fail. (Until `76cd65c` the header comment read as if the script checked the whole chain; it now says it checks only the hash.)

The manual check, in three steps (the container is Debian trixie, whose archive keyring is at `/usr/share/keyrings/debian-archive-keyring.pgp`):
1. **Signature:** `sqv --message` verifies the clearsigned `InRelease` against the keyring and writes the authenticated `Release` text.
2. **Packages hash:** the SHA-256 of `main/binary-amd64/Packages.xz`, as listed in that authenticated `Release`, must match the downloaded index.
3. **Package hash:** the `libegl1` stanza in that index gives `Version`, `Filename` and `SHA256`; that SHA-256 is the value pinned in the script.

To repeat it (in a scratch directory **outside** the repo), e.g. when bumping the version:
```bash
curl -fsSLO https://deb.debian.org/debian/dists/trixie/InRelease
sqv --keyring /usr/share/keyrings/debian-archive-keyring.pgp --message --output Release InRelease
curl -fsSLO https://deb.debian.org/debian/dists/trixie/main/binary-amd64/Packages.xz
grep ' main/binary-amd64/Packages.xz$' Release   # the SHA256 section's line ...
sha256sum Packages.xz                             # ... must show the same hash
xz -dc Packages.xz | awk '/^Package: libegl1$/,/^$/' | grep -E '^(Version|Filename|SHA256):'
```
Then update `VER` and `SHA256` in the script together. Notes: `grep` prints one line per hash section of `Release` (MD5 and SHA256); compare with the one under `SHA256:`. `sqv --output` must name a new file: it refuses to overwrite, and `-` is taken as a file name, not stdout.

The chain was re-run while writing these docs (end of M2): the `InRelease` signature verified, the `Packages.xz` SHA-256 matched `Release`, and the `libegl1` stanza (`1.7.0-1+b2`) still lists the pinned SHA-256.

## Invariants & gotchas
- **Workers must not add other system libraries** (AGENTS.md). If Qt needs another `.so`, request it as `packages_needed` and let the orchestrator vet it.
- `libegl1` is the GLVND dispatcher. On the `offscreen` platform it only has to be loadable; no GPU or display is used.
- `.devlibs/` is gitignored, so no binaries enter the repo.
- Linux amd64 only. Not needed on Windows, where Qt ships what it needs.

## Tests
- Indirectly: `tests/ui/test_smoke.py` fails if the library is missing or broken.

## History
- `cc9f0fa`: added ([dev log](../../04-development-log.md#headless-qt-cc9f0fa)).
