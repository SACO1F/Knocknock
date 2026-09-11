"""Screenshot region capture: a full-screen translucent mask, drag-to-select and a magnifier.

Multi-monitor aware: the whole virtual desktop is stitched into one large image
and the selection is cropped out of it.
"""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from . import i18n
from . import theme

DIM_ALPHA = 118          # mask opacity
MAGNIFIER_SIZE = 132     # magnifier edge length
MAGNIFIER_ZOOM = 7       # magnification factor


class ScreenOverlay(QWidget):
    """Full-screen capture overlay.

    Signals:
        captured(QPixmap)  -- the user finished selecting a region
        cancelled()        -- the user cancelled
    """

    captured = Signal(QPixmap)
    cancelled = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self._composite: Optional[QPixmap] = None
        self._dpr: float = 1.0
        self._start: Optional[QPoint] = None
        self._current: Optional[QPoint] = None
        self._dragging = False

    # ------------------------------------------------------------ startup
    def start(self) -> None:
        """Grab the entire virtual desktop and show the overlay."""
        composite, virtual, dpr = grab_virtual_desktop()
        if composite is None:
            self.cancelled.emit()
            return

        self._composite = composite
        self._dpr = dpr
        self._start = None
        self._current = None
        self._dragging = False

        self.setGeometry(virtual)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.update()

    # ------------------------------------------------------------ painting
    def paintEvent(self, event) -> None:  # noqa: N802
        if self._composite is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(self.rect(), self._composite)

        selection = self._selection_rect()

        # Mask: dim the whole screen, with the selection punched out
        mask = QPainterPath()
        mask.addRect(QRectF(self.rect()))
        if selection and selection.width() > 0 and selection.height() > 0:
            mask.addRect(QRectF(selection))
        mask.setFillRule(Qt.FillRule.OddEvenFill)
        painter.fillPath(mask, QColor(0, 0, 0, DIM_ALPHA))

        if selection and selection.width() > 1 and selection.height() > 1:
            self._draw_selection(painter, selection)
            self._draw_size_label(painter, selection)
            self._draw_magnifier(painter, selection)
        else:
            self._draw_hint(painter)
            self._draw_crosshair(painter)

        painter.end()

    def _selection_rect(self) -> Optional[QRect]:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    def _draw_selection(self, painter: QPainter, rect: QRect) -> None:
        pen = QPen(QColor(theme.palette().accent), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))

        # Corner handles
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        size = 5
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawRect(
                QRect(point.x() - size // 2, point.y() - size // 2, size, size)
            )

    def _draw_size_label(self, painter: QPainter, rect: QRect) -> None:
        dpr = self._dpr or 1.0
        text = f"{int(rect.width() * dpr)} × {int(rect.height() * dpr)}"
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        padding = 7
        box = QRect(0, 0, metrics.horizontalAdvance(text) + padding * 2, metrics.height() + 6)

        x = rect.left()
        y = rect.top() - box.height() - 8
        if y < 4:
            y = rect.top() + 8
        x = max(4, min(x, self.width() - box.width() - 4))
        box.moveTo(x, y)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 175))
        painter.drawRoundedRect(box, 6, 6)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_magnifier(self, painter: QPainter, rect: QRect) -> None:
        """Pixel magnifier near the cursor, plus a coordinate readout."""
        if self._composite is None or self._current is None:
            return
        cursor = self._current
        src_size = MAGNIFIER_SIZE // MAGNIFIER_ZOOM
        src = QRect(
            cursor.x() - src_size // 2,
            cursor.y() - src_size // 2,
            src_size,
            src_size,
        )

        # Bottom-right by default; flip when it would overflow
        box_x = cursor.x() + 18
        box_y = cursor.y() + 18
        if box_x + MAGNIFIER_SIZE > self.width():
            box_x = cursor.x() - MAGNIFIER_SIZE - 18
        if box_y + MAGNIFIER_SIZE + 20 > self.height():
            box_y = cursor.y() - MAGNIFIER_SIZE - 38
        box_x = max(4, box_x)
        box_y = max(4, box_y)

        dpr = self._dpr or 1.0
        src_device = QRect(
            int(src.x() * dpr), int(src.y() * dpr),
            int(src.width() * dpr), int(src.height() * dpr),
        )

        painter.save()
        frame = QRect(box_x, box_y, MAGNIFIER_SIZE, MAGNIFIER_SIZE)
        path = QPainterPath()
        path.addRoundedRect(QRectF(frame), 8, 8)
        painter.setClipPath(path)
        painter.drawPixmap(frame, self._composite, src_device)

        # Crosshair
        painter.setPen(QPen(QColor(theme.palette().accent), 1))
        center = frame.center()
        painter.drawLine(center.x(), frame.top(), center.x(), frame.bottom())
        painter.drawLine(frame.left(), center.y(), frame.right(), center.y())
        painter.restore()

        painter.setPen(QPen(QColor(255, 255, 255, 210), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 8, 8)

        # Coordinate text
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        coord_text = f"({int(cursor.x() * dpr)}, {int(cursor.y() * dpr)})"
        metrics = painter.fontMetrics()
        info = QRect(
            frame.left(),
            frame.bottom() + 3,
            max(frame.width(), metrics.horizontalAdvance(coord_text) + 10),
            metrics.height() + 4,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 165))
        painter.drawRoundedRect(info, 5, 5)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(info, Qt.AlignmentFlag.AlignCenter, coord_text)

    def _draw_hint(self, painter: QPainter) -> None:
        text = i18n.t("capture.hint")
        font = QFont()
        font.setPointSize(11)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 40
        height = metrics.height() + 22
        box = QRect(
            (self.width() - width) // 2,
            int(self.height() * 0.5) - height - 60,
            width,
            height,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 168))
        painter.drawRoundedRect(box, 11, 11)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_crosshair(self, painter: QPainter) -> None:
        if self._current is None:
            return
        pen = QPen(QColor(255, 255, 255, 130), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, self._current.y(), self.width(), self._current.y())
        painter.drawLine(self._current.x(), 0, self._current.x(), self.height())

    # ------------------------------------------------------------ interaction
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._cancel()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._current = self._start
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        self._current = event.position().toPoint()
        rect = self._selection_rect()
        if rect is None or rect.width() < 4 or rect.height() < 4:
            self._start = None
            self._current = None
            self.update()
            return
        self._finish(rect)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Double-click = full screen."""
        self._finish(QRect(self.rect()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self._cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            rect = self._selection_rect()
            self._finish(rect if rect and rect.width() > 3 else QRect(self.rect()))
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------ finishing up
    def _finish(self, rect: QRect) -> None:
        pixmap = self._crop(rect)
        self.hide()
        self._composite = None
        if pixmap is None or pixmap.isNull():
            self.cancelled.emit()
        else:
            self.captured.emit(pixmap)

    def _cancel(self) -> None:
        self.hide()
        self._composite = None
        self._start = None
        self._current = None
        self.cancelled.emit()

    def _crop(self, rect: QRect) -> Optional[QPixmap]:
        if self._composite is None:
            return None
        dpr = self._dpr or 1.0
        device_rect = QRect(
            int(round(rect.x() * dpr)),
            int(round(rect.y() * dpr)),
            max(1, int(round(rect.width() * dpr))),
            max(1, int(round(rect.height() * dpr))),
        ).intersected(self._composite.rect())
        if device_rect.isEmpty():
            return None
        return self._composite.copy(device_rect)


# ---------------------------------------------------------------- helpers
def grab_virtual_desktop() -> Tuple[Optional[QPixmap], QRect, float]:
    """Grab the whole virtual desktop (all monitors).

    Returns (stitched image, virtual-desktop logical rect, devicePixelRatio).

    The stitched image is deliberately stored in **device pixels** (no
    devicePixelRatio set on it), so cropping later only needs to multiply the
    logical coordinates by the dpr. This sidesteps Qt's coordinate-conversion
    ambiguity on high-DPI displays.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None, QRect(), 1.0

    virtual: QRect = screen.virtualGeometry()
    dpr = float(screen.devicePixelRatio() or 1.0)

    composite = QPixmap(
        max(1, int(virtual.width() * dpr)),
        max(1, int(virtual.height() * dpr)),
    )
    composite.fill(QColor("#000000"))

    painter = QPainter(composite)
    for scr in QGuiApplication.screens():
        geometry = scr.geometry()
        shot = scr.grabWindow(0)
        if shot.isNull():
            continue
        target = QRect(
            int((geometry.x() - virtual.x()) * dpr),
            int((geometry.y() - virtual.y()) * dpr),
            max(1, int(geometry.width() * dpr)),
            max(1, int(geometry.height() * dpr)),
        )
        painter.drawPixmap(target, shot)
    painter.end()

    return composite, virtual, dpr


def crop_device_rect(composite: QPixmap, rect: QRect, dpr: float) -> Optional[QPixmap]:
    """Crop from the device-pixel image using logical coordinates (rect is relative to the virtual desktop's top-left)."""
    if composite is None or composite.isNull():
        return None
    device_rect = QRect(
        int(round(rect.x() * dpr)),
        int(round(rect.y() * dpr)),
        max(1, int(round(rect.width() * dpr))),
        max(1, int(round(rect.height() * dpr))),
    ).intersected(composite.rect())
    if device_rect.isEmpty():
        return None
    return composite.copy(device_rect)


def pixmap_to_png_bytes(pixmap: QPixmap, quality: int = 90) -> bytes:
    """Encode a QPixmap as a PNG byte stream (for sending to a vision model)."""
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG", quality)
    buffer.close()
    return bytes(byte_array)


def image_to_png_bytes(image: QImage) -> bytes:
    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(byte_array)


def scale_to_fit(pixmap: QPixmap, max_width: int, max_height: int) -> QPixmap:
    """Scale proportionally, capped at the given maximum size."""
    if pixmap.width() <= max_width and pixmap.height() <= max_height:
        return pixmap
    return pixmap.scaled(
        max_width,
        max_height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
