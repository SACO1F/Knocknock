"""Generate the application's .ico file from the same vector design used in the UI.

The app draws its own icon procedurally (``knocknock.widgets.app_icon``) so it
ships no image assets. For the Windows executable we still need a real ``.ico``
file, so this script renders that drawing at several sizes and packs them into a
multi-resolution icon.

Run it from the project root:

    .venv\\Scripts\\python.exe packaging\\make_icon.py
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Qt must not need a real display for this to work.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from knocknock.widgets import app_icon  # noqa: E402

# Windows Explorer picks the best match from the sizes embedded in the file.
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

# Render each frame at 4x and downsample: this keeps the small sizes readable.
SUPERSAMPLE = 4


def render_frame(size: int) -> QImage:
    """Render the app icon at one size, supersampled for a crisp result."""
    big = size * SUPERSAMPLE
    image = app_icon(big).pixmap(big, big).toImage()
    return image.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(image: QImage) -> bytes:
    """Encode a QImage as PNG bytes."""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def ico_bytes(frames: list[tuple[int, QImage]]) -> bytes:
    """Pack PNG-encoded images into a single .ico container.

    Windows Vista and later accept PNG-compressed entries inside an .ico, which
    keeps the 256x256 frame small while remaining fully compatible.
    """
    count = len(frames)
    directory = b""
    payload = b""
    offset = 6 + count * 16

    for size, image in frames:
        data = png_bytes(image)
        # A dimension of 256 is encoded as 0 in the directory entry.
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII",
            dimension,      # width
            dimension,      # height
            0,              # palette size (0 = true colour)
            0,              # reserved
            1,              # colour planes
            32,             # bits per pixel
            len(data),      # size of the image data
            offset,         # offset of the image data
        )
        payload += data
        offset += len(data)

    header = struct.pack("<HHH", 0, 1, count)  # reserved, type=icon, count
    return header + directory + payload


def main() -> int:
    QApplication.instance() or QApplication(sys.argv)

    frames = [(size, render_frame(size)) for size in ICON_SIZES]

    target = ROOT / "packaging" / "knocknock.ico"
    target.write_bytes(ico_bytes(frames))
    print(f"Wrote {target} ({target.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
