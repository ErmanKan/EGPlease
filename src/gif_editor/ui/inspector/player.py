"""Playback engine: steps ``Document.current_index`` through a frame sequence in time.

``Player`` is a non-visual ``QObject``. It owns a single-shot ``QTimer`` and, while
playing, moves the document's current frame forward one frame at a time, forever
(looping). Views (canvas, timebar, filmstrip, transport) simply react to
``Document.currentIndexChanged``; they never talk to the player directly, except the
transport bar, which is given the player to drive it.

Two sequences can be played (``preview_edits``):

* ``False`` (default): every *source* frame in order, each for its effective delay
  (``doc.meta.delays_ms``).
* ``True``: the *output* timeline, ``doc.plan().frames``, each for ``delay_cs * 10`` ms.
  Trimmed and deleted frames are skipped, speed / FPS are applied. This previews
  timing only; crop and resize preview arrive in Milestone 3.

Timing is drift-free: each frame's end is scheduled on an *ideal* timeline measured
by a monotonic clock (``QElapsedTimer``), not "now + delay". If the event loop was
late by more than a frame, frames are skipped so playback catches up instead of
slowly lagging behind.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal

from gif_editor.ui.document import Document

# (source frame index, how long it is shown in ms)
Step = tuple[int, float]

# A timer firing up to this many ms early still counts as "on time" (timer jitter).
_EARLY_TOLERANCE_MS = 1.0


class Player(QObject):
    """Plays the open document by advancing ``doc.current_index`` on a timer.

    ``clock`` (returns milliseconds as a float, monotonic) and ``time_scale`` (every
    delay is multiplied by it) exist for tests; the app uses the defaults.
    """

    playingChanged = Signal(bool)
    previewEditsChanged = Signal(bool)

    def __init__(
        self,
        doc: Document,
        parent: QObject | None = None,
        *,
        clock: Callable[[], float] | None = None,
        time_scale: float = 1.0,
    ) -> None:
        super().__init__(parent)
        if time_scale <= 0:
            raise ValueError("time_scale must be > 0")
        self._doc = doc
        self._time_scale = float(time_scale)
        if clock is None:
            self._elapsed = QElapsedTimer()
            self._elapsed.start()
            clock = lambda: self._elapsed.nsecsElapsed() / 1e6  # noqa: E731
        self._clock = clock

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_timeout)

        self._playing = False
        self._preview = False
        self._seq: list[Step] = []
        self._pos = 0  # index into _seq of the frame on screen
        self._due = 0.0  # clock time (ms) at which the frame at _pos ends
        self._setting_index = False  # True while *we* call doc.set_current_index

        doc.sourceChanged.connect(self._on_source_changed)
        doc.stateChanged.connect(self._on_state_changed)
        doc.currentIndexChanged.connect(self._on_index_changed)

    # ----------------------------------------------------------- properties
    @property
    def is_playing(self) -> bool:
        """True while the timer is driving the current frame."""
        return self._playing

    @property
    def preview_edits(self) -> bool:
        """False: play all source frames. True: play the edited output timeline."""
        return self._preview

    @preview_edits.setter
    def preview_edits(self, value: bool) -> None:
        value = bool(value)
        if value == self._preview:
            return
        self._preview = value
        if self._playing:
            self._resync(keep_due=False)
        self.previewEditsChanged.emit(value)

    def set_preview_edits(self, value: bool) -> None:
        """Slot-friendly setter for ``preview_edits`` (e.g. ``QCheckBox.toggled``)."""
        self.preview_edits = value

    def sequence(self) -> list[Step]:
        """The frames the player would play right now: ``[(src_index, ms), ...]``.

        Empty when nothing is open or the edited plan has no frames.
        """
        meta = self._doc.meta
        if meta is None:
            return []
        s = self._time_scale
        if not self._preview:
            return [(i, d * s) for i, d in enumerate(meta.delays_ms)]
        plan = self._doc.plan()
        return [(f.src_index, f.delay_cs * 10 * s) for f in plan.frames] if plan else []

    # -------------------------------------------------------------- control
    def play(self) -> None:
        """Start playing from the current frame (or the next one in the sequence)."""
        if self._playing:
            return
        self._seq = self.sequence()
        if not self._seq:
            # Nothing to play: tell listeners (e.g. a checked play button) we are stopped.
            self.playingChanged.emit(False)
            return
        self._pos = self._locate(self._doc.current_index)
        self._show(self._pos)
        self._due = self._clock() + self._seq[self._pos][1]
        self._playing = True
        self._arm()
        self.playingChanged.emit(True)

    def pause(self) -> None:
        """Stop advancing; the current frame stays where it is."""
        self._timer.stop()
        if self._playing:
            self._playing = False
            self.playingChanged.emit(False)

    def toggle(self) -> None:
        """Play if paused, pause if playing."""
        if self._playing:
            self.pause()
        else:
            self.play()

    def stop(self) -> None:
        """Pause and go to the first frame of the current sequence."""
        self.pause()
        self.go_first()

    def go_first(self) -> None:
        """Show the first frame of the current sequence (keeps playing if playing)."""
        self._jump_to_seq_pos(0)

    def go_last(self) -> None:
        """Show the last frame of the current sequence (keeps playing if playing)."""
        self._jump_to_seq_pos(-1)

    def step(self, n: int) -> None:
        """Move ``n`` frames (negative = backwards) within the current sequence, wrapping.

        If the current frame is not in the sequence (e.g. it is deleted and edits are
        previewed), ``+1`` goes to the next kept frame and ``-1`` to the previous one.
        """
        seq = self.sequence()
        if not seq:
            return
        # Collapse consecutive repeats (a very long delay can be split into several
        # entries of the same source frame) so one step always changes the picture.
        srcs = [s for k, (s, _) in enumerate(seq) if k == 0 or seq[k - 1][0] != s]
        cur = self._doc.current_index
        k = _first_ge(srcs, cur)  # plans keep source order, so this is the slot of cur
        exact = k < len(srcs) and srcs[k] == cur
        # When cur is not in srcs, srcs[k] is already the next kept frame (so +1 means
        # "k") and srcs[k - 1] the previous one (so -1 means "k - 1").
        target = k + n if exact or n <= 0 else k + n - 1
        dest = srcs[target % len(srcs)]
        if self._playing:
            self._seq = seq
            self._pos = seq.index(next(s for s in seq if s[0] == dest))
            self._show(self._pos)
            self._due = self._clock() + seq[self._pos][1]
            self._arm()
        else:
            self._show_src(dest)

    # ------------------------------------------------------------- internals
    def _locate(self, src: int) -> int:
        """Position of ``src`` in ``_seq``, else of the nearest following frame (wraps)."""
        for k, (s, _) in enumerate(self._seq):
            if s == src:
                return k
        for k, (s, _) in enumerate(self._seq):
            if s > src:
                return k
        return 0

    def _show(self, pos: int) -> None:
        self._show_src(self._seq[pos][0])

    def _show_src(self, src: int) -> None:
        self._setting_index = True
        try:
            self._doc.set_current_index(src)
        finally:
            self._setting_index = False

    def _arm(self) -> None:
        wait = max(0.0, self._due - self._clock())
        self._timer.start(int(wait + 0.5))

    def _jump_to_seq_pos(self, which: int) -> None:
        seq = self.sequence()
        if not seq:
            return
        if self._playing:
            self._seq = seq
            self._pos = which % len(seq)
            self._show(self._pos)
            self._due = self._clock() + seq[self._pos][1]
            self._arm()
        else:
            self._show_src(seq[which][0])

    def _on_timeout(self) -> None:
        """Advance to the frame that should be visible now on the ideal timeline."""
        if not self._playing or not self._seq:
            return
        now = self._clock()
        if now < self._due - _EARLY_TOLERANCE_MS:
            self._arm()  # woke up early: wait the rest
            return
        n = len(self._seq)
        cycle = sum(d for _, d in self._seq)
        if now - self._due > cycle:
            # Hugely late (debugger, sleep): don't replay whole loops, just rebase.
            self._due = now
        # Move on at least one frame, then skip every frame whose time already passed.
        self._pos = (self._pos + 1) % n
        self._due += self._seq[self._pos][1]
        while self._due <= now:
            self._pos = (self._pos + 1) % n
            self._due += self._seq[self._pos][1]
        self._show(self._pos)
        self._arm()

    def _resync(self, *, keep_due: bool) -> None:
        """Rebuild the sequence while playing and continue from the current frame."""
        self._seq = self.sequence()
        if not self._seq:
            self.pause()
            return
        cur = self._doc.current_index
        pos = self._locate(cur)
        still_there = self._seq[pos][0] == cur
        self._pos = pos
        if not (keep_due and still_there):
            self._due = self._clock() + self._seq[pos][1]
        if not still_there:
            self._show(pos)
        self._arm()

    def _on_state_changed(self, _state: object) -> None:
        # Only the edited timeline depends on EditState.
        if self._playing and self._preview:
            self._resync(keep_due=True)

    def _on_index_changed(self, index: int) -> None:
        # Someone else (filmstrip click, timebar scrub) moved the frame while playing:
        # continue playing from there with a fresh timing base.
        if self._playing and not self._setting_index:
            self._resync(keep_due=False)

    def _on_source_changed(self) -> None:
        self.pause()
        self._seq = []
        self._pos = 0


def _first_ge(values: list[int], x: int) -> int:
    """Index of the first value >= x, or ``len(values)`` if there is none."""
    for k, v in enumerate(values):
        if v >= x:
            return k
    return len(values)
