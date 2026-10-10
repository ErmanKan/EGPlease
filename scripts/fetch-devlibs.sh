#!/usr/bin/env bash
# Fetch the Linux system libraries PySide6 needs for HEADLESS tests in the dev container
# into ./.devlibs (project-local, gitignored). Nothing is installed system-wide and no
# package maintainer scripts run: the .deb is only unpacked with `dpkg-deb -x`.
#
# Trust chain: Debian archive key (local keyring) -> signed InRelease -> Packages index
# hash -> package SHA256 (pinned below and re-checked).
set -euo pipefail
cd "$(dirname "$0")/.."

PKG=libegl1
VER=1.7.0-1+b2
SHA256=62e7bc8ccd47a60e55aad17f83d8d474310d782eb8589bbce2ab714c31712406
URL=https://deb.debian.org/debian/pool/main/libg/libglvnd/${PKG}_${VER}_amd64.deb
DEB=.devlibs/debs/${PKG}_${VER}_amd64.deb

mkdir -p .devlibs/debs
if [ ! -f "$DEB" ]; then
  curl -fsSL -o "$DEB" "$URL"
fi
echo "$SHA256  $DEB" | sha256sum -c -
rm -rf .devlibs/root
dpkg-deb -x "$DEB" .devlibs/root
echo "OK: $(ls .devlibs/root/usr/lib/x86_64-linux-gnu/)"
