# `tests/conftest.py`

> Session-wide pytest fixtures: the generated GIF corpus, written once per test session.

## Where it sits
- **Layer:** tests
- **Used by:** pytest automatically, for every test under `tests/`. Fixtures are consumed by `test_corpus.py`, `test_decoder_corpus.py` and `test_pipeline.py`.
- **Uses:** `tests/corpus.py` (`build_all`, `Expected`), imported as `corpus` thanks to `pythonpath = ["src", "tests"]`.

## Public API
| Fixture | Scope | Value |
|---|---|---|
| `_corpus_entries` | session | `build_all(tmp_path_factory.mktemp("gif_corpus"))` (internal) |
| `corpus` | session | `{name: (path, Expected)}` for all 13 entries. Treat as read-only. |
| `corpus_dir` | session | The directory holding the corpus files. |

## How it works
Session scope means the 13 files are generated once, not per test. Building them includes running the pure-Python reference compositor, which is slow-ish.

## Invariants & gotchas
- **No Qt imports here.** Core tests must run with `-p no:pytest-qt`, or on a machine without Qt libraries. Qt fixtures live in `tests/ui/conftest.py`.
- Tests must not modify the corpus files or the `Expected` objects. They are shared across the session.

## Tests
- `test_corpus.py::test_all_entries_written` checks the fixture output.

## History
- `cc5e164`: corpus fixtures.
