# `src/gif_editor/__init__.py`

> The top-level package. It holds the package docstring and `__version__`.

## Where it sits
- **Layer:** tooling / package root
- **Used by:** any `import gif_editor...`. Nothing reads `__version__` yet. The M5 packaging is expected to use it for the exe version info.
- **Uses:** nothing.

## Public API
| Name | Kind | Purpose |
|---|---|---|
| `__version__ = "0.1.0"` | str | Application version. Keep it in sync with `pyproject.toml` `[project].version`. |

## How it works
Two lines: the docstring "GIF Editor — offline desktop GIF editor." and the version string.

## Invariants & gotchas
- The version is duplicated in `pyproject.toml`. Nothing enforces that the two match.
- The package is not installed into the venv. It is found through `PYTHONPATH=src` (run) or pytest's `pythonpath = ["src", "tests"]` (tests).

## Tests
- None.

## History
- `7a7b418`: scaffold.
