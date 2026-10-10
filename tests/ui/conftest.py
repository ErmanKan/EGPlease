import pytest

from gif_editor.core.decoder import GifSource
from gif_editor.ui.document import Document
from gifgen import make_gif, solid_frames


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
