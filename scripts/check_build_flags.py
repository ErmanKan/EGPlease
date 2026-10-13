"""Check every flag scripts/build.py passes against Nuitka's own option table.

Why this exists: four flags in the first version of `scripts/build.py` were wrong
(`--cache-dir`, `--no-console`, a missing `--include-package`, a missing `PYTHONPATH`), and
each mistake cost a full 20-minute compile to discover. Nuitka's real parser is importable,
so the flags can be validated in a second instead of by building twice -- including the
Windows-only ones, which cannot otherwise be tested on Linux at all.

Two subtleties this models, both verified against Nuitka 4.3's source:
- `--enable-plugin=NAME` (and `--plugin-enable`, `--enable-plugins`) is registered in
  `OptionParsing`, and `addStandardPluginCommandLineOptions` adds the `--noinclude-*-mode`
  family at that point. So those are valid *because* the plugin flag is passed.
- `--windows-console-mode` is accepted on every platform (`_warnOSSpecificOption` only
  warns); what is truly Windows-only is `--windows-icon-from-ico`. The Linux check therefore
  asserts that no icon-from-ico flag leaks, not that no `--windows-` flag appears.

Run it after touching `scripts/build.py`, and in CI:
    .venv/bin/python scripts/check_build_flags.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402  (the module under test)

#: Plugin-control spellings Nuitka accepts; the plugin's own options arrive with them.
PLUGIN_FLAGS = ("enable-plugin", "enable-plugins", "plugin-enable")
#: Registered alongside any plugin (`addStandardPluginCommandLineOptions`).
PLUGIN_DEPENDENT = ("noinclude-pytest-mode", "noinclude-setuptools-mode")
#: Only meaningful when building on Windows.
WINDOWS_ONLY = ("windows-icon-from-ico", "windows-company-name", "windows-product-name")


def known_options() -> set[str]:
    """Every long option Nuitka's parser accepts (importing it registers the options)."""
    from nuitka.options import OptionParsing

    names: set[str] = set()
    for group in [OptionParsing.parser, *OptionParsing.parser.option_groups]:
        for option in group.option_list or []:
            names.update(n.lstrip("-") for n in (*option._short_opts, *option._long_opts))
    return names


def flag_name(arg: str) -> str | None:
    """The option name of ``arg`` (``--foo=bar`` -> ``foo``), or None if it is not an option."""
    if not arg.startswith("--"):
        return None
    return arg[2:].split("=", 1)[0]


def check(platform_name: str, *, windows: bool, known: set[str]) -> list[str]:
    cmd = build.build_command("0.1.0", windows=windows)
    names = {n for a in cmd if (n := flag_name(a)) is not None}
    problems: list[str] = []
    for name in sorted(names):
        if name in known:
            continue
        if name in PLUGIN_FLAGS or name in PLUGIN_DEPENDENT:
            # Valid only if the command actually asks for a plugin.
            if not any(f in names for f in PLUGIN_FLAGS):
                problems.append(f"{platform_name}: --{name} needs a plugin flag alongside it")
            continue
        problems.append(f"{platform_name}: unknown option --{name}")
    if windows:
        for required in ("windows-icon-from-ico", "windows-console-mode"):
            if required not in names:
                problems.append(f"Windows: --{required} is missing")
    else:
        for bad in WINDOWS_ONLY:
            if bad in names:
                problems.append(f"Linux: --{bad} must not appear in a Linux build")
        # The console flag is accepted everywhere, but must not say "attach" on Linux
        # (it is a Windows console concept; Nuitka expects "disable" there).
        console = next((a for a in cmd if a.startswith("--windows-console-mode=")), "")
        if console != "--windows-console-mode=disable":
            problems.append(f"Linux: unexpected console mode {console!r}")
    print(f"{platform_name:8s} {len(cmd):2d} args -> {'ok' if not problems else 'PROBLEMS'}")
    return problems


def main() -> int:
    known = known_options()
    version = _nuitka_version()
    print(f"Nuitka {version} accepts {len(known)} long options")
    problems: list[str] = []
    for platform_name, windows in (("Linux", False), ("Windows", True)):
        problems += check(platform_name, windows=windows, known=known)
    # Options that cost real build time must never come back.
    win = {n for a in build.build_command("0.1.0", windows=True) if (n := flag_name(a)) is not None}
    for bad in ("cache-dir", "no-console"):
        if bad in win:
            problems.append(f"regression: --{bad} is not a real Nuitka option")
    # A version string that does not survive to Nuitka is only caught late in a build.
    for flag in ("file-version", "product-version"):
        value = next(
            (
                a.split("=", 1)[1]
                for a in build.build_command("0.1.0")
                if a.startswith(f"--{flag}=")
            ),
            None,
        )
        if value != "0.1.0":
            problems.append(f"--{flag} did not take the version through: {value!r}")
    if problems:
        print("\nPROBLEMS:\n  " + "\n  ".join(problems))
        return 1
    print("\nAll flags are valid for both platforms.")
    return 0


def _nuitka_version() -> str:
    import nuitka

    return getattr(nuitka, "__version__", "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
