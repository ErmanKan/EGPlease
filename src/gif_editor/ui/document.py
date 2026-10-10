"""The open document: the single object every UI widget talks to.

``Document`` owns

* the decoded ``GifSource`` (or ``None`` when nothing is open),
* the current immutable ``EditState`` and the ``QUndoStack`` of edits,
* the *current frame* (a source index shared by canvas, timebar and filmstrip),
* the *selection* (source indices selected in the filmstrip; Delete acts on it).

Widgets never modify each other; they call ``Document`` methods and react to its
signals. That keeps every view consistent and makes undo/redo work everywhere.

State changes always go through ``apply()`` -> ``SetStateCommand`` -> ``_set_state_raw``.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from gif_editor.core.decoder import GifSource, SourceMeta
from gif_editor.core.models import EditState
from gif_editor.core.pipeline import Summary, plan, summarize
from gif_editor.core.timeline import TimelinePlan
from gif_editor.ui.commands import SetStateCommand


class Document(QObject):
    sourceChanged = Signal()  # a file was opened or closed (everything must refresh)
    stateChanged = Signal(object)  # new EditState
    currentIndexChanged = Signal(int)  # source frame index
    selectionChanged = Signal(object)  # frozenset[int] of source indices

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self._source: GifSource | None = None
        self._path: Path | None = None
        self._state = EditState()
        self._current = 0
        self._selection: frozenset[int] = frozenset()

    # ----------------------------------------------------------------- source
    @property
    def source(self) -> GifSource | None:
        return self._source

    @property
    def meta(self) -> SourceMeta | None:
        return self._source.meta if self._source is not None else None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._source is not None

    def set_source(self, source: GifSource, path: str | Path) -> None:
        """Adopt an already-opened source (open it off the GUI thread first)."""
        old = self._source
        self._source = source
        self._path = Path(path)
        self._state = EditState()
        self._current = 0
        self._selection = frozenset()
        self.undo_stack.clear()
        if old is not None:
            old.close()
        self.sourceChanged.emit()
        self.stateChanged.emit(self._state)
        self.currentIndexChanged.emit(0)
        self.selectionChanged.emit(self._selection)

    def close(self) -> None:
        if self._source is None:
            return
        self._source.close()
        self._source = None
        self._path = None
        self._state = EditState()
        self._current = 0
        self._selection = frozenset()
        self.undo_stack.clear()
        self.sourceChanged.emit()
        self.stateChanged.emit(self._state)
        self.currentIndexChanged.emit(0)
        self.selectionChanged.emit(self._selection)

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> EditState:
        return self._state

    def apply(self, new: EditState, text: str, merge_key: str | None = None) -> None:
        """Make ``new`` the current state as one undoable step (no-op if unchanged).

        Raises ``ValueError`` if ``new`` is invalid for the open source; nothing changes.
        """
        if new == self._state:
            return
        if self.meta is not None:
            new.validate(self.meta.width, self.meta.height, self.meta.frame_count)
        self.undo_stack.push(SetStateCommand(self, self._state, new, text, merge_key))

    def _set_state_raw(self, state: EditState) -> None:
        """Only for SetStateCommand. Emits ``stateChanged``."""
        self._state = state
        self.stateChanged.emit(state)

    # Convenience edits used by several widgets -------------------------------
    def delete_frames(self, indices: Iterable[int]) -> None:
        idx = frozenset(indices)
        new = self._state.deleted | idx
        if self.meta is not None and len(new) >= self.meta.frame_count:
            raise ValueError("Cannot delete every frame")
        n = len(idx - self._state.deleted)
        if n:
            self.apply(self._state.with_(deleted=new), f"Delete {n} frame(s)")

    def restore_frames(self, indices: Iterable[int]) -> None:
        idx = frozenset(indices)
        n = len(idx & self._state.deleted)
        if n:
            self.apply(
                self._state.with_(deleted=self._state.deleted - idx), f"Restore {n} frame(s)"
            )

    def set_trim(
        self, start_ms: int, duration_ms: int | None, *, merge_key: str | None = "trim"
    ) -> None:
        self.apply(
            self._state.with_(trim_start_ms=max(0, int(start_ms)), trim_duration_ms=duration_ms),
            "Change trim",
            merge_key,
        )

    # ---------------------------------------------------------- current frame
    @property
    def current_index(self) -> int:
        return self._current

    def set_current_index(self, i: int) -> None:
        if self.meta is None:
            return
        i = max(0, min(int(i), self.meta.frame_count - 1))
        if i != self._current:
            self._current = i
            self.currentIndexChanged.emit(i)

    # -------------------------------------------------------------- selection
    @property
    def selection(self) -> frozenset[int]:
        return self._selection

    def set_selection(self, indices: Iterable[int]) -> None:
        sel = frozenset(indices)
        if sel != self._selection:
            self._selection = sel
            self.selectionChanged.emit(sel)

    # ---------------------------------------------------------------- derived
    def plan(self) -> TimelinePlan | None:
        """Output timeline for the current state, or ``None`` if nothing is open."""
        return plan(self.meta, self._state) if self.meta is not None else None

    def summary(self) -> Summary | None:
        return summarize(self.meta, self._state) if self.meta is not None else None

    def frame_start_ms(self, i: int) -> int:
        """Source-time start of frame ``i`` (ms)."""
        assert self.meta is not None
        return sum(self.meta.delays_ms[:i])
