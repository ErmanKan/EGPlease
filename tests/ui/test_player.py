"""Tests for the playback engine (``ui/inspector/player.py``).

The ``doc`` fixture has 8 frames of 100 ms. Timer-driven tests use ``time_scale=0.2`` so
each frame lasts 20 ms of real time; drift/skip logic is tested with a fake clock by
calling the timeout slot directly (deterministic, no sleeping).
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from gif_editor.ui.document import Document
from gif_editor.ui.inspector.player import Player

FAST = 0.2  # 100 ms source delays -> 20 ms real time


def record(doc: Document) -> list[int]:
    seen: list[int] = []
    doc.currentIndexChanged.connect(seen.append)
    return seen


def assert_forward(seen: list[int], order: list[int]) -> None:
    """Every visit moves 1..3 positions forward in ``order`` (cyclically).

    Normally each step is exactly +1. A slow test machine may make the player skip a
    frame or two (by design: it catches up instead of lagging), so small forward
    jumps are tolerated; going backwards or standing still never is.
    """
    n = len(order)
    for a, b in pairwise(seen):
        assert 1 <= (order.index(b) - order.index(a)) % n <= 3, (a, b, seen)


def test_play_advances_in_source_order_and_loops(doc, qtbot):
    p = Player(doc, time_scale=FAST)
    seen = record(doc)
    p.play()
    assert p.is_playing
    qtbot.waitUntil(lambda: len(seen) >= 12, timeout=3000)
    p.pause()
    assert_forward(seen, list(range(8)))
    assert set(seen) == set(range(8))
    assert 0 in seen  # it wrapped around (looped)


def test_preview_edits_skips_deleted_and_follows_plan(doc, qtbot):
    doc.delete_frames({2, 5})
    p = Player(doc, time_scale=FAST)
    p.preview_edits = True
    order = list(doc.plan().src_indices)
    assert order == [0, 1, 3, 4, 6, 7]
    seen = record(doc)
    p.play()
    qtbot.waitUntil(lambda: len(seen) >= 10, timeout=3000)
    p.pause()
    assert not {2, 5} & set(seen)
    assert_forward(seen, order)


def test_pause_stops_advancing(doc, qtbot):
    p = Player(doc, time_scale=FAST)
    seen = record(doc)
    p.play()
    qtbot.waitUntil(lambda: len(seen) >= 2, timeout=2000)
    p.pause()
    assert not p.is_playing
    n = len(seen)
    qtbot.wait(120)
    assert len(seen) == n


def test_toggle_flips_and_emits(doc, qtbot):
    p = Player(doc, time_scale=FAST)
    states: list[bool] = []
    p.playingChanged.connect(states.append)
    p.toggle()
    assert p.is_playing
    p.toggle()
    assert not p.is_playing
    assert states == [True, False]


def test_empty_plan_does_not_play(doc, qtbot):
    doc.apply(doc.state.with_(trim_start_ms=10_000), "trim past end")
    assert doc.plan().frame_count == 0
    p = Player(doc, time_scale=FAST)
    p.preview_edits = True
    with qtbot.waitSignal(p.playingChanged) as blocker:
        p.play()
    assert blocker.args == [False]
    assert not p.is_playing


def test_plan_becoming_empty_while_playing_pauses(doc, qtbot):
    p = Player(doc, time_scale=FAST)
    p.preview_edits = True
    p.play()
    doc.apply(doc.state.with_(trim_start_ms=10_000), "trim past end")
    assert not p.is_playing


def test_source_changed_stops(doc, qtbot, gif_path):
    p = Player(doc, time_scale=FAST)
    p.play()
    with qtbot.waitSignal(p.playingChanged) as blocker:
        doc.close()
    assert blocker.args == [False] and not p.is_playing


def test_play_without_source_does_nothing(qtbot):
    p = Player(Document())
    p.play()
    assert not p.is_playing
    p.step(1)  # no crash


def test_step_wraps(doc):
    p = Player(doc)
    p.step(-1)
    assert doc.current_index == 7
    p.step(1)
    assert doc.current_index == 0
    p.step(3)
    assert doc.current_index == 3


def test_step_in_preview_skips_deleted(doc):
    doc.delete_frames({1, 2})
    p = Player(doc)
    p.preview_edits = True
    p.step(1)
    assert doc.current_index == 3
    p.step(-1)
    assert doc.current_index == 0
    doc.set_current_index(2)  # a deleted frame
    p.step(1)
    assert doc.current_index == 3
    doc.set_current_index(2)
    p.step(-1)
    assert doc.current_index == 0


def test_play_from_deleted_frame_jumps_to_next_kept(doc, qtbot):
    doc.delete_frames({3, 4})
    doc.set_current_index(3)
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.preview_edits = True
    p.play()
    assert doc.current_index == 5
    p.pause()


def test_play_starts_from_current_frame(doc):
    doc.set_current_index(4)
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.play()
    assert doc.current_index == 4
    t[0] = 100.0
    p._on_timeout()
    assert doc.current_index == 5
    p.pause()


def test_late_timer_skips_ahead_without_lag(doc):
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.play()  # frame 0 ends at 100; frame k is visible during [100k, 100k+100)
    t[0] = 350.0  # 2.5 frames late
    p._on_timeout()
    assert doc.current_index == 3
    t[0] = 400.0  # exactly on the ideal schedule again: no accumulated lag
    p._on_timeout()
    assert doc.current_index == 4
    p.pause()


def test_early_wakeup_waits(doc):
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.play()
    t[0] = 50.0
    p._on_timeout()
    assert doc.current_index == 0
    p.pause()


def test_hugely_late_rebases_instead_of_replaying_loops(doc):
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.play()
    t[0] = 100_000.0  # e.g. the app was suspended
    p._on_timeout()
    assert doc.current_index == 1
    t[0] = 100_100.0
    p._on_timeout()
    assert doc.current_index == 2
    p.pause()


def test_state_change_while_previewing_resyncs(doc):
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.preview_edits = True
    doc.set_current_index(2)
    p.play()
    doc.delete_frames({2})  # current frame vanishes from the plan
    assert p.is_playing
    assert doc.current_index == 3
    p.pause()


def test_external_scrub_while_playing_continues_from_there(doc):
    t = [0.0]
    p = Player(doc, clock=lambda: t[0])
    p.play()
    t[0] = 30.0
    doc.set_current_index(6)  # user clicked the filmstrip
    t[0] = 130.0
    p._on_timeout()
    assert doc.current_index == 7
    p.pause()


def test_stop_goes_to_first_of_sequence(doc):
    doc.apply(doc.state.with_(trim_start_ms=300), "trim")
    p = Player(doc)
    p.preview_edits = True
    doc.set_current_index(6)
    p.play()
    p.stop()
    assert not p.is_playing
    assert doc.current_index == 3


def test_go_last(doc):
    p = Player(doc)
    p.go_last()
    assert doc.current_index == 7
    p.go_first()
    assert doc.current_index == 0


def test_preview_edits_property_emits_once(doc, qtbot):
    p = Player(doc)
    seen: list[bool] = []
    p.previewEditsChanged.connect(seen.append)
    p.preview_edits = True
    p.preview_edits = True
    p.set_preview_edits(False)
    assert seen == [True, False]


def test_preview_sequence_uses_plan_delays(doc):
    doc.apply(doc.state.with_(speed=2.0), "speed")
    p = Player(doc)
    assert p.sequence()[0] == (0, 100.0)
    p.preview_edits = True
    assert p.sequence()[0] == (0, 50.0)


def test_invalid_time_scale(doc):
    with pytest.raises(ValueError):
        Player(doc, time_scale=0)
