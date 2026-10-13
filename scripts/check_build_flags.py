"""Check every flag scripts/build.py passes, using Nuitka's own option parser.

Why this exists: four flags in the first version of `scripts/build.py` were wrong
(`--cache-dir`, `--no-console`, a missing `--include-package`, a missing `PYTHONPATH`), and
each mistake cost a full build (20+ minutes in the dev container) to discover. Nuitka's real
parser is importable, so each flag is parsed exactly as `python -m nuitka` would parse it,
in a second instead of a build -- including the Windows-only flags, which cannot otherwise
be tried on Linux at all.

How: for each platform, a fresh copy of Nuitka's parser is built (`OptionParsing` creates it
at import), the standard plugin options are added, plus the options of every plugin the
command enables (`--enable-plugin=pyside6` brings `--noinclude-qt-plugins`), which is what
Nuitka itself does before parsing. Then every flag is parsed on its own; anything the parser
rejects is reported. Using the real parser (rather than a list of option names) also gets
optparse's prefix matching right: `--enable-plugin` is accepted as `--enable-plugins`.

Run it after touching `scripts/build.py`, and in CI:
    .venv/bin/python scripts/check_build_flags.py
"""

from __future__ import annotations

import contextlib
import importlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402  (the module under test)

#: Only meaningful when building on Windows; must never reach a Linux build.
WINDOWS_ONLY = ("windows-icon-from-ico", "windows-company-name", "windows-product-name")
PLUGIN_FLAG_PREFIXES = ("--enable-plugin=", "--enable-plugins=", "--plugin-enable=")


def fresh_parser(cmd: list[str]):
    """Nuitka's parser, as it would be set up for ``cmd`` (plugins it enables included)."""
    from nuitka.options import OptionParsing
    from nuitka.plugins import Plugins

    OptionParsing = importlib.reload(OptionParsing)  # the parser is module state: rebuild it
    parser = OptionParsing.parser
    # Nuitka records each plugin whose options it registered in `plugin_options` and skips
    # it the next time, so a second fresh parser would silently lack every plugin option
    # (the Windows check then "rejected" valid flags). Forget that record first.
    Plugins.plugin_options.clear()
    Plugins.addStandardPluginCommandLineOptions(parser=parser, plugin_help_mode=False)
    plugins = [
        name
        for arg in cmd
        if arg.startswith(PLUGIN_FLAG_PREFIXES)
        for name in arg.split("=", 1)[1].split(",")
    ]
    if plugins:
        Plugins.addPluginCommandLineOptions(
            parser=parser, plugin_names=plugins, plugin_help_mode=False
        )
    return parser


def rejected_flags(cmd: list[str]) -> list[str]:
    """The flags in ``cmd`` that Nuitka's parser refuses."""
    parser = fresh_parser(cmd)
    bad = []
    for arg in cmd:
        if not arg.startswith("--"):
            continue
        sink = io.StringIO()
        try:
            with contextlib.redirect_stderr(sink), contextlib.redirect_stdout(sink):
                parser.parse_args([arg, "main.py"])
        except SystemExit:
            bad.append(arg)
    return bad


def flag_name(arg: str) -> str | None:
    """The option name of ``arg`` (``--foo=bar`` -> ``foo``), or None if it is not an option."""
    if not arg.startswith("--"):
        return None
    return arg[2:].split("=", 1)[0]


def check(platform_name: str, *, windows: bool) -> list[str]:
    cmd = build.build_command("0.1.0", windows=windows)
    problems = [f"{platform_name}: Nuitka rejects {a}" for a in rejected_flags(cmd)]
    names = {n for a in cmd if (n := flag_name(a)) is not None}
    if windows:
        for required in ("windows-icon-from-ico", "windows-console-mode"):
            if required not in names:
                problems.append(f"Windows: --{required} is missing")
    else:
        for bad in WINDOWS_ONLY:
            if bad in names:
                problems.append(f"Linux: --{bad} must not appear in a Linux build")
        # Accepted everywhere, but "attach" is a Windows console concept.
        console = next((a for a in cmd if a.startswith("--windows-console-mode=")), "")
        if console != "--windows-console-mode=disable":
            problems.append(f"Linux: unexpected console mode {console!r}")
    print(f"{platform_name:8s} {len(cmd):2d} args -> {'ok' if not problems else 'PROBLEMS'}")
    return problems


def main() -> int:
    print(f"Nuitka {_nuitka_version()}")
    problems: list[str] = []
    for platform_name, windows in (("Linux", False), ("Windows", True)):
        problems += check(platform_name, windows=windows)
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
    print("\nAll flags are accepted by Nuitka's parser for both platforms.")
    return 0


def _nuitka_version() -> str:
    # nuitka has no __version__ attribute; nuitka.Version is where the CLI gets it.
    from nuitka.Version import getNuitkaVersion

    return getNuitkaVersion()


if __name__ == "__main__":
    raise SystemExit(main())
