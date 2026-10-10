"""Left-hand settings panel: timing, output size, quality, live summary and Generate.

The panel is a pure *view + controller* over ``Document``:

* every control writes a new ``EditState`` through ``Document.apply`` (or
  ``Document.set_trim``) with a fixed ``merge_key`` per control, so scrubbing a
  spinbox or dragging the speed slider is ONE undo step;
* whenever the document state changes (our own edit, undo/redo, another widget),
  ``_refresh_controls`` rewrites every control with its signals blocked, so the
  refresh can never push a new command (no feedback loop);
* invalid edits raise ``ValueError`` in ``Document.apply``; the panel catches it,
  reverts the controls to ``doc.state`` and shows the message in the summary card.

The panel never talks to other widgets. ``generateRequested`` is the only outward
signal; the main window connects it (and the Ctrl+G shortcut) to the Generate flow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from html import escape

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gif_editor.core.models import MAX_FPS, MAX_SPEED, MIN_SPEED, EditState, OutputSize, Quality
from gif_editor.ui.document import Document

#: Colour used for warnings in the summary card (amber, readable on light and dark).
WARNING_COLOR = "#c77700"
#: Colour used for errors / the empty-output message.
ERROR_COLOR = "#c0392b"

MAX_SIDE = 8192
#: Multiplication sign (escaped so linters do not flag it as a look-alike of "x").
TIMES = "\u00d7"
#: Combo-box entries: (label, Quality preset name or None for "Custom").
PRESETS: tuple[tuple[str, str | None], ...] = (
    ("High", "high"),
    ("Medium", "medium"),
    ("Low", "low"),
    ("Custom", None),
)


def _fmt_seconds(ms: int) -> str:
    return f"{ms / 1000:.2f} s"


class SettingsPanel(QWidget):
    """Output settings for the open document plus a live summary and the Generate button.

    Construct with ``SettingsPanel(doc, parent=None)``. All state lives in ``doc``;
    the panel only mirrors it and writes edits back as undoable commands.
    """

    #: Emitted when the user clicks Generate (only possible when the output is non-empty).
    generateRequested = Signal()

    PANEL_WIDTH = 280

    def __init__(self, doc: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._doc = doc
        self._error: str | None = None  # last rejected edit, shown in the summary card
        self.setAccessibleName("Settings panel")
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self._build_timing())
        root.addWidget(self._build_size())
        root.addWidget(self._build_quality())
        root.addWidget(self._build_summary())
        root.addStretch(1)

        self.generate_button = QPushButton("Generate")
        self.generate_button.setAccessibleName("Generate GIF")
        self.generate_button.setToolTip("Write the edited GIF (Ctrl+G)")
        self.generate_button.setMinimumHeight(40)
        font = self.generate_button.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.2)
        self.generate_button.setFont(font)
        self.generate_button.clicked.connect(self.generateRequested)
        root.addWidget(self.generate_button)

        self._controls: list[QWidget] = [
            self.timing_group,
            self.size_group,
            self.quality_group,
        ]
        self._connect_controls()
        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        self._on_source_changed()

    def sizeHint(self) -> QSize:
        """Preferred size: ~280 logical px wide, natural height."""
        return QSize(self.PANEL_WIDTH, super().sizeHint().height())

    # ------------------------------------------------------------------ build
    def _build_timing(self) -> QGroupBox:
        self.timing_group = QGroupBox("Timing")
        form = QFormLayout(self.timing_group)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setAccessibleName("Start time")
        self.start_spin.setDecimals(2)
        self.start_spin.setSingleStep(0.01)
        self.start_spin.setSuffix(" s")
        self.start_spin.setKeyboardTracking(False)
        form.addRow("Start time", self.start_spin)

        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setAccessibleName("Duration")
        self.duration_spin.setDecimals(2)
        self.duration_spin.setSingleStep(0.01)
        self.duration_spin.setSuffix(" s")
        self.duration_spin.setKeyboardTracking(False)
        self.to_end_check = QCheckBox("to end")
        self.to_end_check.setAccessibleName("Duration to end")
        row = QHBoxLayout()
        row.addWidget(self.duration_spin, 1)
        row.addWidget(self.to_end_check)
        form.addRow("Duration", row)

        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setAccessibleName("Speed")
        self.speed_spin.setRange(MIN_SPEED, MAX_SPEED)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setSuffix(TIMES)
        self.speed_spin.setKeyboardTracking(False)
        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setAccessibleName("Speed slider")
        # The slider works in hundredths: 25..400 == 0.25x..4.0x.
        self.speed_slider.setRange(round(MIN_SPEED * 100), round(MAX_SPEED * 100))
        self.speed_slider.setSingleStep(5)
        self.speed_slider.setPageStep(25)
        speed_box = QVBoxLayout()
        speed_box.setSpacing(2)
        speed_box.addWidget(self.speed_spin)
        speed_box.addWidget(self.speed_slider)
        form.addRow("Speed", speed_box)

        self.fps_check = QCheckBox("Limit FPS")
        self.fps_check.setAccessibleName("Limit FPS")
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setAccessibleName("Maximum FPS")
        self.fps_spin.setRange(1.0, MAX_FPS)
        self.fps_spin.setDecimals(1)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setValue(25.0)
        self.fps_spin.setKeyboardTracking(False)
        row = QHBoxLayout()
        row.addWidget(self.fps_check)
        row.addWidget(self.fps_spin, 1)
        form.addRow("FPS", row)
        return self.timing_group

    def _build_size(self) -> QGroupBox:
        self.size_group = QGroupBox("Output size")
        form = QFormLayout(self.size_group)
        self.width_spin = QSpinBox()
        self.width_spin.setAccessibleName("Output width")
        self.height_spin = QSpinBox()
        self.height_spin.setAccessibleName("Output height")
        for spin in (self.width_spin, self.height_spin):
            spin.setRange(1, MAX_SIDE)
            spin.setSuffix(" px")
            spin.setKeyboardTracking(False)
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)

        self.lock_check = QCheckBox("Lock aspect")
        self.lock_check.setAccessibleName("Lock aspect ratio")
        self.lock_check.setChecked(True)
        form.addRow("", self.lock_check)

        self.scale_spin = QSpinBox()
        self.scale_spin.setAccessibleName("Scale percent")
        self.scale_spin.setRange(1, 400)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setKeyboardTracking(False)
        self.reset_size_button = QPushButton("Reset")
        self.reset_size_button.setAccessibleName("Reset output size")
        self.reset_size_button.setToolTip("Use the crop size (or the original size)")
        row = QHBoxLayout()
        row.addWidget(self.scale_spin, 1)
        row.addWidget(self.reset_size_button)
        form.addRow("Scale", row)
        return self.size_group

    def _build_quality(self) -> QGroupBox:
        self.quality_group = QGroupBox("Quality")
        form = QFormLayout(self.quality_group)
        self.preset_combo = QComboBox()
        self.preset_combo.setAccessibleName("Quality preset")
        for label, key in PRESETS:
            self.preset_combo.addItem(label, key)
        form.addRow("Preset", self.preset_combo)

        self.colors_spin = QSpinBox()
        self.colors_spin.setAccessibleName("Colours")
        self.colors_spin.setRange(2, 256)
        self.colors_spin.setKeyboardTracking(False)
        form.addRow("Colours", self.colors_spin)

        self.dither_check = QCheckBox("Dither")
        self.dither_check.setAccessibleName("Dither")
        form.addRow("", self.dither_check)
        return self.quality_group

    def _build_summary(self) -> QGroupBox:
        self.summary_group = QGroupBox("Summary")
        box = QVBoxLayout(self.summary_group)
        self.summary_label = QLabel()
        self.summary_label.setAccessibleName("Output summary")
        self.summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.summary_label)
        return self.summary_group

    def _connect_controls(self) -> None:
        self.start_spin.valueChanged.connect(self._on_trim_edited)
        self.duration_spin.valueChanged.connect(self._on_trim_edited)
        self.to_end_check.toggled.connect(self._on_trim_edited)
        self.speed_spin.valueChanged.connect(self._on_speed_spin)
        self.speed_slider.valueChanged.connect(self._on_speed_slider)
        self.fps_check.toggled.connect(self._on_fps_edited)
        self.fps_spin.valueChanged.connect(self._on_fps_edited)
        self.width_spin.valueChanged.connect(self._on_width_edited)
        self.height_spin.valueChanged.connect(self._on_height_edited)
        self.scale_spin.valueChanged.connect(self._on_scale_edited)
        self.reset_size_button.clicked.connect(self._on_reset_size)
        self.preset_combo.activated.connect(self._on_preset_chosen)
        self.colors_spin.valueChanged.connect(self._on_quality_edited)
        self.dither_check.toggled.connect(self._on_quality_edited)

    # ---------------------------------------------------------------- helpers
    def _total_ms(self) -> int:
        meta = self._doc.meta
        return meta.total_duration_ms if meta is not None else 0

    def _base_size(self) -> tuple[int, int]:
        """Size the output has without an explicit ``size``: crop size, else canvas."""
        meta = self._doc.meta
        if meta is None:
            return (1, 1)
        crop = self._doc.state.crop
        if crop is not None:
            return (crop.w, crop.h)
        return (meta.width, meta.height)

    def _output_size(self) -> tuple[int, int]:
        size = self._doc.state.size
        return (size.width, size.height) if size is not None else self._base_size()

    def _try(self, edit: Callable[[], None]) -> None:
        """Run an edit; on ``ValueError`` revert the controls and show the message."""
        try:
            edit()
        except ValueError as exc:
            self._error = str(exc)
            self._refresh_controls()
            self._refresh_summary()

    def _apply(self, new: EditState, text: str, merge_key: str) -> None:
        self._try(lambda: self._doc.apply(new, text, merge_key=merge_key))

    @contextmanager
    def _blocked(self) -> Iterator[None]:
        """Block signals of every input control while refreshing them from the state."""
        widgets = [
            self.start_spin,
            self.duration_spin,
            self.to_end_check,
            self.speed_spin,
            self.speed_slider,
            self.fps_check,
            self.fps_spin,
            self.width_spin,
            self.height_spin,
            self.scale_spin,
            self.preset_combo,
            self.colors_spin,
            self.dither_check,
        ]
        blockers = [QSignalBlocker(w) for w in widgets]
        try:
            yield
        finally:
            for b in blockers:
                b.unblock()

    # ---------------------------------------------------------- edit handlers
    def _on_trim_edited(self, *_args: object) -> None:
        if not self._doc.is_open:
            return
        total = self._total_ms()
        start = max(0, min(round(self.start_spin.value() * 1000), max(0, total - 10)))
        duration: int | None
        if self.to_end_check.isChecked():
            duration = None
        else:
            # Clamp rather than reject: a duration past the end just means "to the end".
            duration = round(self.duration_spin.value() * 1000)
            duration = max(10, min(duration, total - start))
        self._try(lambda: self._doc.set_trim(start, duration, merge_key="trim"))
        self._refresh_controls()  # show clamped values even if the state didn't change

    def _on_speed_spin(self, value: float) -> None:
        self._set_speed(value)

    def _on_speed_slider(self, value: int) -> None:
        self._set_speed(value / 100)

    def _set_speed(self, speed: float) -> None:
        if not self._doc.is_open:
            return
        speed = max(MIN_SPEED, min(MAX_SPEED, round(speed, 2)))
        self._try(
            lambda: self._doc.apply(self._doc.state.with_(speed=speed), "Change speed", "speed")
        )
        self._refresh_controls()

    def _on_fps_edited(self, *_args: object) -> None:
        if not self._doc.is_open:
            return
        fps = float(self.fps_spin.value()) if self.fps_check.isChecked() else None
        self._try(lambda: self._doc.apply(self._doc.state.with_(fps=fps), "Change FPS", "fps"))
        self._refresh_controls()

    def _set_size(self, w: int, h: int) -> None:
        w = max(1, min(MAX_SIDE, int(w)))
        h = max(1, min(MAX_SIDE, int(h)))
        # The base size needs no explicit size: storing None keeps "follow the crop".
        size = None if (w, h) == self._base_size() else OutputSize(w, h)
        self._try(
            lambda: self._doc.apply(self._doc.state.with_(size=size), "Change output size", "size")
        )
        self._refresh_controls()

    def _on_width_edited(self, w: int) -> None:
        if not self._doc.is_open:
            return
        bw, bh = self._base_size()
        h = round(w * bh / bw) if self.lock_check.isChecked() else self.height_spin.value()
        self._set_size(w, h)

    def _on_height_edited(self, h: int) -> None:
        if not self._doc.is_open:
            return
        bw, bh = self._base_size()
        w = round(h * bw / bh) if self.lock_check.isChecked() else self.width_spin.value()
        self._set_size(w, h)

    def _on_scale_edited(self, pct: int) -> None:
        if not self._doc.is_open:
            return
        bw, bh = self._base_size()
        self._set_size(round(bw * pct / 100), round(bh * pct / 100))

    def _on_reset_size(self) -> None:
        if not self._doc.is_open:
            return
        self._apply(self._doc.state.with_(size=None), "Reset output size", "size")
        self._refresh_controls()

    def _on_preset_chosen(self, index: int) -> None:
        if not self._doc.is_open:
            return
        key = self.preset_combo.itemData(index)
        if key is None:  # "Custom": nothing to change, the user edits colours/dither next
            return
        self._apply(self._doc.state.with_(quality=Quality.preset(key)), "Change quality", "quality")
        self._refresh_controls()

    def _on_quality_edited(self, *_args: object) -> None:
        if not self._doc.is_open:
            return
        q = Quality(self.colors_spin.value(), self.dither_check.isChecked())
        self._try(
            lambda: self._doc.apply(self._doc.state.with_(quality=q), "Change quality", "quality")
        )
        self._refresh_controls()

    # ------------------------------------------------------------- doc events
    def _on_source_changed(self) -> None:
        """New file (or closed): reset ranges, enabled state and every control."""
        self._error = None
        is_open = self._doc.is_open
        for w in self._controls:
            w.setEnabled(is_open)
        total_s = self._total_ms() / 1000
        with self._blocked():
            self.start_spin.setRange(0.0, max(0.0, total_s - 0.01))
            self.duration_spin.setRange(0.01, max(0.01, total_s))
            meta = self._doc.meta
            if meta is not None and meta.frame_count:
                # Sensible default for "Limit FPS": the source's own average rate (<= 50).
                avg = meta.total_duration_ms / meta.frame_count
                self.fps_spin.setValue(max(1.0, min(MAX_FPS, round(1000 / avg))))
        self._refresh_controls()
        self._refresh_summary()

    def _on_state_changed(self, _state: object) -> None:
        self._error = None  # a successful edit (or undo) clears the last error
        self._refresh_controls()
        self._refresh_summary()

    # --------------------------------------------------------------- refresh
    def _refresh_controls(self) -> None:
        """Mirror ``doc.state`` into every control without emitting edit signals."""
        st = self._doc.state
        total = self._total_ms()
        with self._blocked():
            _set(self.start_spin, st.trim_start_ms / 1000)
            to_end = st.trim_duration_ms is None
            self.to_end_check.setChecked(to_end)
            remaining = max(0, total - st.trim_start_ms)
            shown = remaining if to_end else min(st.trim_duration_ms, remaining)
            _set(self.duration_spin, max(10, shown) / 1000)
            self.duration_spin.setEnabled(not to_end)

            _set(self.speed_spin, st.speed)
            _set(self.speed_slider, round(st.speed * 100))

            self.fps_check.setChecked(st.fps is not None)
            if st.fps is not None:
                _set(self.fps_spin, st.fps)
            self.fps_spin.setEnabled(st.fps is not None)

            w, h = self._output_size()
            bw, _bh = self._base_size()
            _set(self.width_spin, w)
            _set(self.height_spin, h)
            _set(self.scale_spin, max(1, min(400, round(w * 100 / bw))))
            self.reset_size_button.setEnabled(st.size is not None)

            _set(self.colors_spin, st.quality.colors)
            self.dither_check.setChecked(st.quality.dither)
            self.preset_combo.setCurrentIndex(_preset_index(st.quality))

    def _refresh_summary(self) -> None:
        """Rebuild the rich-text summary card and the Generate button state."""
        meta = self._doc.meta
        if meta is None:
            self.summary_label.setText("<i>No file open</i>")
            self.generate_button.setEnabled(False)
            return
        lines = [
            f"<b>Source:</b> {meta.frame_count} frames · "
            f"{_fmt_seconds(meta.total_duration_ms)} · {meta.width}{TIMES}{meta.height}"
        ]
        frames = 0
        try:
            s = self._doc.summary()
        except ValueError as exc:
            lines.append(f'<span style="color:{ERROR_COLOR}">{escape(str(exc))}</span>')
        else:
            assert s is not None
            frames = s.frame_count
            lines.append(
                f"<b>Output:</b> {s.frame_count} frames · "
                f"{_fmt_seconds(s.duration_ms)} · {s.width}{TIMES}{s.height}"
            )
            if s.frame_count == 0:
                lines.append(
                    f'<span style="color:{ERROR_COLOR}">'
                    "The output is empty: adjust the trim or restore frames.</span>"
                )
            lines.extend(
                f'<span style="color:{WARNING_COLOR}">⚠ {escape(w)}</span>' for w in s.warnings
            )
        if self._error:
            lines.append(f'<span style="color:{ERROR_COLOR}">{escape(self._error)}</span>')
        self.summary_label.setText("<br>".join(lines))
        self.generate_button.setEnabled(frames >= 1)


def _set(widget: QSpinBox | QDoubleSpinBox | QSlider, value: float) -> None:
    """Set a value only if it differs, so an in-progress edit isn't disturbed."""
    if widget.value() != value:
        widget.setValue(value)


def _preset_index(q: Quality) -> int:
    """Combo index of the preset matching ``q``, or of "Custom"."""
    for i, (_label, key) in enumerate(PRESETS):
        if key is not None and Quality.preset(key) == q:
            return i
    return len(PRESETS) - 1
