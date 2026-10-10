"""Undoable edits. Every change to ``EditState`` goes through ``SetStateCommand``.

Because ``EditState`` is immutable, one generic command (old state -> new state) covers
every kind of edit. Continuous gestures (dragging a trim handle, spinning a spinbox)
pass a ``merge_key``; consecutive commands with the same key collapse into a single
undo step via Qt's ``mergeWith`` mechanism.
"""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

from gif_editor.core.models import EditState

if TYPE_CHECKING:
    from gif_editor.ui.document import Document


def _merge_id(key: str | None) -> int:
    # QUndoCommand ids must be ints; -1 means "never merge".
    return -1 if key is None else zlib.crc32(key.encode()) & 0x7FFFFFFF


class SetStateCommand(QUndoCommand):
    def __init__(
        self,
        doc: Document,
        old: EditState,
        new: EditState,
        text: str,
        merge_key: str | None = None,
    ) -> None:
        super().__init__(text)
        self._doc = doc
        self.old = old
        self.new = new
        self._id = _merge_id(merge_key)

    def id(self) -> int:
        return self._id

    def mergeWith(self, other: QUndoCommand) -> bool:
        if not isinstance(other, SetStateCommand) or other.id() != self.id():
            return False
        self.new = other.new
        if self.new == self.old:
            self.setObsolete(True)  # gesture ended where it started: drop the step
        return True

    def redo(self) -> None:
        self._doc._set_state_raw(self.new)

    def undo(self) -> None:
        self._doc._set_state_raw(self.old)
