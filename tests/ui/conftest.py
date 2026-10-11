import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from gif_editor.core.decoder import GifSource
from gif_editor.ui.document import Document
from gifgen import make_gif, solid_frames


@pytest.fixture(autouse=True)
def _drain_workers(qtbot):
    """Let no background task outlive its test.

    Depends on ``qtbot`` so it is torn down BEFORE qtbot closes the test's widgets: every
    pool task finishes and its GUI-thread callback runs while its objects still exist.
    Without this, a worker started by one test could still be running (and calling back)
    while the next test sets up, an ordering that never happens in the app and once
    crashed the suite with a segmentation fault in a pool thread.
    """
    yield
    pool = QThreadPool.globalInstance()
    for _ in range(10):  # a callback may start a follow-up task (e.g. the next preview)
        pool.waitForDone(10_000)
        QApplication.processEvents()
        if pool.activeThreadCount() == 0:
            break


@pytest.fixture
def gif_path(tmp_path):
    """8 solid-colour frames, 40x30, 100 ms each."""
    return make_gif(tmp_path / "in.gif", solid_frames(8, (40, 30)), 100)


@pytest.fixture
def doc(qtbot, gif_path):
    d = Document()
    d.set_source(GifSource.open(gif_path), gif_path)
    yield d
    d.close()
