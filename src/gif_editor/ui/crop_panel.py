"""Left-panel **Crop** group: aspect preset, X/Y/W/H spinboxes, Full image / Center / Reset
buttons and a status line, all mirroring and editing ``doc.state.crop``.

This widget is the numeric counterpart of the draggable rectangle on the canvas
(``ui/inspector/crop_item.py``). The two never talk to each other: both write
``doc.state.crop`` through ``Document.apply`` and both refresh from ``stateChanged``.

The behaviour is specified rule by rule in ``docs/codebase/src/gif_editor/ui/crop_panel.md``.
The numbers in the comments below ("rule 3") refer to that page.

Data flow:

* **Control -> state.** Each edit builds ``doc.state.with_(crop=...)`` and calls
  ``doc.apply``. Spinbox edits share ``merge_key="crop"`` so scrubbing one is a single
  undo step; buttons and the group checkbox pass ``merge_key=None`` (one step per click).
* **State -> controls.** ``_refresh`` rewrites every control inside ``_blocked()``, so a
  refresh (after undo, or a canvas drag) can never re-enter a handler and push a command.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gif_editor.core.models import CropRect
from gif_editor.core.render import output_dimensions
from gif_editor.ui.document import Document

#: Multiplication sign (escaped so ruff's look-alike-character rule stays quiet).
TIMES = "\u00d7"

#: Aspect combo entries in order: (label, ratio w/h or None). "Original" (index 1) is
#: patched with the open file's canvas ratio on every ``sourceChanged``.
ASPECTS: tuple[tuple[str, float | None], ...] = (
    ("Free", None),
    ("Original", None),
    ("1:1", 1.0),
    ("4:3", 4 / 3),
    ("16:9", 16 / 9),
    ("3:2", 1.5),
    ("9:16", 9 / 16),
)
ORIGINAL_INDEX = 1

#: Undo merge key for spinbox scrubbing. Canvas drags use their own per-drag keys.
MERGE_KEY = "crop"


class CropPanel(QWidget):
    """The Crop group of the settings panel. Everything it shows comes from ``doc``."""

    #: A crop edit was rejected by ``Document.apply``; carries the ``ValueError`` message.
    errorOccurred = Signal(str)

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        #: The last rejected crop message, or None. Cleared by the next accepted change.
        self.last_error: str | None = None
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAccessibleName("Crop settings")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._build())

        self._connect_controls()
        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        self._on_source_changed()

    # ------------------------------------------------------------------ build
    def _build(self) -> QGroupBox:
        self.crop_group = QGroupBox("Crop")
        self.crop_group.setCheckable(True)
        self.crop_group.setAccessibleName("Crop")
        self.crop_group.setToolTip("Tick to crop; untick to use the full frame")
        form = QFormLayout(self.crop_group)

        self.aspect_combo = QComboBox()
        for label, ratio in ASPECTS:
            self.aspect_combo.addItem(label, ratio)
        self.aspect_combo.setAccessibleName("Crop aspect")
        self.aspect_combo.setToolTip("Keeps width and height in this ratio while you type")
        form.addRow("Aspect", self.aspect_combo)

        self.x_spin = self._spin("Crop x")
        self.y_spin = self._spin("Crop y")
        self.w_spin = self._spin("Crop width")
        self.h_spin = self._spin("Crop height")
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("Width", self.w_spin)
        form.addRow("Height", self.h_spin)

        buttons = QHBoxLayout()
        self.full_button = QPushButton("Full image")
        self.full_button.setAccessibleName("Crop: full image")
        self.center_button = QPushButton("Center")
        self.center_button.setAccessibleName("Crop: centre")
        self.center_button.setToolTip("Centre the crop in the frame, keeping its size")
        self.reset_button = QPushButton("Reset")
        self.reset_button.setAccessibleName("Crop: reset")
        self.reset_button.setToolTip("Remove the crop and set the aspect back to Free")
        for b in (self.full_button, self.center_button, self.reset_button):
            buttons.addWidget(b)
        form.addRow(buttons)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("Crop status")
        form.addRow(self.status_label)
        return self.crop_group

    @staticmethod
    def _spin(name: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setSuffix(" px")
        spin.setAccessibleName(name)
        # Typing "20" applies on Enter/focus-out, not as "2" then "20".
        spin.setKeyboardTracking(False)
        return spin

    def _connect_controls(self) -> None:
        self.x_spin.valueChanged.connect(self._on_x_edited)
        self.y_spin.valueChanged.connect(self._on_y_edited)
        self.w_spin.valueChanged.connect(self._on_w_edited)
        self.h_spin.valueChanged.connect(self._on_h_edited)
        self.full_button.clicked.connect(self._on_full)
        self.center_button.clicked.connect(self._on_center)
        self.reset_button.clicked.connect(self._on_reset)
        self.crop_group.toggled.connect(self._on_group_toggled)

    # ---------------------------------------------------------------- helpers
    def _canvas(self) -> tuple[int, int]:
        meta = self._doc.meta
        return (meta.width, meta.height) if meta is not None else (1, 1)

    def _current_rect(self) -> tuple[int, int, int, int]:
        """The crop as (x, y, w, h); the full canvas when there is no crop."""
        crop = self._doc.state.crop
        if crop is not None:
            return crop.x, crop.y, crop.w, crop.h
        cw, ch = self._canvas()
        return 0, 0, cw, ch

    def _ratio(self) -> float | None:
        data = self.aspect_combo.currentData()
        return float(data) if data is not None else None

    def _normalise(self, x: int, y: int, w: int, h: int) -> CropRect | None:
        """Rule 6: a rectangle covering the whole canvas is stored as ``None``."""
        cw, ch = self._canvas()
        if (x, y, w, h) == (0, 0, cw, ch):
            return None
        return CropRect(x, y, w, h)

    def _commit(self, crop: CropRect | None, text: str, merge_key: str | None) -> None:
        """Apply a crop as one undoable command; on ValueError revert and report."""
        try:
            self._doc.apply(self._doc.state.with_(crop=crop), text, merge_key)
        except ValueError as exc:
            self.last_error = str(exc)
            self._refresh()  # apply() is atomic: the state did not change, show it again
            self.errorOccurred.emit(self.last_error)

    @contextmanager
    def _blocked(self) -> Iterator[None]:
        widgets = (
            self.aspect_combo,
            self.x_spin,
            self.y_spin,
            self.w_spin,
            self.h_spin,
            self.crop_group,
            self.full_button,
            self.center_button,
            self.reset_button,
        )
        blockers = [QSignalBlocker(w) for w in widgets]
        try:
            yield
        finally:
            for b in blockers:
                b.unblock()

    # ------------------------------------------------------------ edit rules
    def _spin_edit(self, edit: Callable[[int, int, int, int, int, int], tuple]) -> None:
        if not self._doc.is_open:
            return
        cw, ch = self._canvas()
        x, y, w, h = edit(*self._current_rect(), cw, ch)
        self._commit(self._normalise(x, y, w, h), "Crop", MERGE_KEY)

    def _on_x_edited(self, value: int) -> None:
        # Rule 1: keep W, Y, H; clamp x so the rectangle stays inside.
        def edit(_x, y, w, h, cw, _ch):
            return max(0, min(value, cw - w)), y, w, h

        self._spin_edit(edit)

    def _on_y_edited(self, value: int) -> None:
        # Rule 2: mirror of rule 1.
        def edit(x, _y, w, h, _cw, ch):
            return x, max(0, min(value, ch - h)), w, h

        self._spin_edit(edit)

    def _on_w_edited(self, value: int) -> None:
        # Rules 3 and 7: keep the typed width; shift x left instead of shrinking it.
        ratio = self._ratio()

        def edit(x, y, _w, h, cw, ch):
            w = max(1, min(value, cw))
            if ratio is not None:
                h = max(1, min(round(w / ratio), ch))
                y = min(y, ch - h)  # rule 4's clamp
            x = min(x, cw - w)
            return x, y, w, h

        self._spin_edit(edit)

    def _on_h_edited(self, value: int) -> None:
        # Rules 4 and 7: mirror of the width rule.
        ratio = self._ratio()

        def edit(x, y, w, _h, cw, ch):
            h = max(1, min(value, ch))
            if ratio is not None:
                w = max(1, min(round(h * ratio), cw))
                x = min(x, cw - w)  # rule 3's clamp
            y = min(y, ch - h)
            return x, y, w, h

        self._spin_edit(edit)

    def _centered(self) -> CropRect | None:
        """Rule 10: centre the current crop size (or the output size when not cropping)."""
        cw, ch = self._canvas()
        st = self._doc.state
        if st.crop is not None:
            w, h = st.crop.w, st.crop.h
        else:
            w, h = output_dimensions(cw, ch, None, st.size)
        w, h = min(w, cw), min(h, ch)
        return self._normalise((cw - w) // 2, (ch - h) // 2, w, h)

    def _on_full(self) -> None:
        # Rule 9: the full image is canonically "no crop".
        if self._doc.is_open:
            self._commit(None, "Crop: full image", None)

    def _on_center(self) -> None:
        if self._doc.is_open:
            self._commit(self._centered(), "Crop: centre", None)

    def _on_reset(self) -> None:
        # Rule 11: like "Full image", but also returns the aspect combo to Free.
        if not self._doc.is_open:
            return
        self.aspect_combo.setCurrentIndex(0)
        self._commit(None, "Crop: reset", None)

    def _on_group_toggled(self, checked: bool) -> None:
        # Rule 12: unchecked = no crop; checking applies the Center default.
        if not self._doc.is_open:
            return
        if checked:
            crop = self._centered()
            if crop is None:  # the centred default IS the full frame: inset it so a crop exists
                cw, ch = self._canvas()
                w, h = max(1, cw * 8 // 10), max(1, ch * 8 // 10)
                crop = CropRect((cw - w) // 2, (ch - h) // 2, w, h)
            self._commit(crop, "Crop: enable", None)
        else:
            self._commit(None, "Crop: disable", None)

    # --------------------------------------------------------------- refresh
    def _on_source_changed(self) -> None:
        self.last_error = None
        meta = self._doc.meta
        with self._blocked():
            if meta is None:
                self.aspect_combo.setItemData(ORIGINAL_INDEX, None)
                for spin, lo, hi in (
                    (self.x_spin, 0, 0),
                    (self.y_spin, 0, 0),
                    (self.w_spin, 1, 1),
                    (self.h_spin, 1, 1),
                ):
                    spin.setRange(lo, hi)
            else:
                self.aspect_combo.setItemData(ORIGINAL_INDEX, meta.width / meta.height)
                self.x_spin.setRange(0, meta.width - 1)
                self.y_spin.setRange(0, meta.height - 1)
                self.w_spin.setRange(1, meta.width)
                self.h_spin.setRange(1, meta.height)
        self._refresh()

    def _on_state_changed(self, _state: object) -> None:
        self.last_error = None
        self._refresh()

    def _refresh(self) -> None:
        """Mirror ``doc.state`` into every control, signals blocked (no commands pushed)."""
        is_open = self._doc.is_open
        x, y, w, h = self._current_rect()
        crop = self._doc.state.crop
        with self._blocked():
            self.crop_group.setEnabled(is_open)
            self.crop_group.setChecked(is_open and crop is not None)
            # Note: a checkable QGroupBox force-disables its children while it is unchecked
            # and that overrides setEnabled(True). That is the intended "tick to crop" UX:
            # with no crop the inputs are greyed out, and ticking the box creates one.
            for wdg in (
                self.aspect_combo,
                self.x_spin,
                self.y_spin,
                self.w_spin,
                self.h_spin,
                self.full_button,
                self.center_button,
                self.reset_button,
            ):
                wdg.setEnabled(is_open)
            for spin, value in (
                (self.x_spin, x),
                (self.y_spin, y),
                (self.w_spin, w),
                (self.h_spin, h),
            ):
                # Leave a spinbox alone while the user is mid-typing in it.
                if spin.lineEdit().isModified() and spin.hasFocus():
                    continue
                if spin.value() != value:
                    spin.setValue(value)
        self.status_label.setText(self._status_text())

    def _status_text(self) -> str:
        meta = self._doc.meta
        if meta is None:
            return "No crop"
        crop = self._doc.state.crop
        if crop is None:
            return f"No crop (full frame {meta.width}{TIMES}{meta.height})"
        pct = round(100 * crop.w * crop.h / (meta.width * meta.height))
        return f"Crop {crop.w}{TIMES}{crop.h} at {crop.x},{crop.y} \u00b7 {pct}% of the frame"
