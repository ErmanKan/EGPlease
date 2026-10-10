from PIL import Image

from gif_editor.ui.qt_image import checkerboard_brush, pil_to_qimage


def test_pil_to_qimage_pixels(qtbot):
    img = Image.new("RGBA", (3, 2), (10, 20, 30, 128))
    img.putpixel((2, 1), (255, 0, 0, 255))
    q = pil_to_qimage(img)
    assert (q.width(), q.height()) == (3, 2)
    c = q.pixelColor(2, 1)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (255, 0, 0, 255)
    assert q.pixelColor(0, 0).alpha() == 128
    del img  # the QImage must own its buffer
    assert q.pixelColor(2, 1).red() == 255


def test_p_mode_and_brush(qtbot):
    q = pil_to_qimage(Image.new("P", (4, 4)))
    assert q.width() == 4
    assert not checkerboard_brush().texture().isNull()
