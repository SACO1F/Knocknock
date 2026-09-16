"""Reusable UI pieces: flow layout, icon buttons, programmatically drawn icons."""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QLabel, QLayout, QPushButton, QSizePolicy, QWidget

from . import theme


class FlowLayout(QLayout):
    """A wrapping horizontal layout (a simplified take on Qt's official FlowLayout)."""

    def __init__(self, parent: Optional[QWidget] = None, margin: int = 0,
                 h_spacing: int = 6, v_spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    # -------------------------------------------------- QLayout interface
    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    # -------------------------------------------------- layout core
    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0

        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()


class ShrinkableLabel(QLabel):
    """A label that can be squeezed narrower than its text.

    A QLabel's minimumSizeHint equals the full width of its text, so a long
    string pins the window's minimum width and stops the panel from being
    narrowed. Here the minimum width is relaxed to 0: the label shows at its
    natural width when there is room, and is allowed to be compressed when
    there is not (the panel switches to shorter copy when narrow).
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())


class IconButton(QPushButton):
    """A borderless icon button."""

    def __init__(self, icon: QIcon, tooltip: str = "", size: int = 26,
                 checkable: bool = False, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("IconBtn")
        self.setIcon(icon)
        self.setIconSize(QSize(size - 10, size - 10))
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(checkable)
        if tooltip:
            self.setToolTip(tooltip)


# ---------------------------------------------------------------- icon drawing
def _blank_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def app_icon(size: int = 128) -> QIcon:
    """Draw the app icon procedurally: a blue rounded square with a white speech bubble and a cursor."""
    pixmap = _blank_pixmap(size)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    margin = size * 0.08
    body = QRect(int(margin), int(margin), int(size - margin * 2), int(size - margin * 2))
    path = QPainterPath()
    path.addRoundedRect(body, size * 0.24, size * 0.24)

    from PySide6.QtGui import QLinearGradient

    gradient = QLinearGradient(body.topLeft(), body.bottomRight())
    gradient.setColorAt(0.0, QColor("#4FA8FF"))
    gradient.setColorAt(1.0, QColor("#0A6CFF"))
    painter.fillPath(path, gradient)

    # speech bubble
    bubble = QPainterPath()
    b = QRect(int(size * 0.24), int(size * 0.28), int(size * 0.52), int(size * 0.36))
    bubble.addRoundedRect(b, size * 0.11, size * 0.11)
    tail = QPainterPath()
    tail.moveTo(size * 0.36, size * 0.62)
    tail.lineTo(size * 0.36, size * 0.74)
    tail.lineTo(size * 0.48, size * 0.62)
    tail.closeSubpath()
    bubble = bubble.united(tail)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawPath(bubble)

    # three lines inside the bubble
    pen = QPen(QColor("#0A6CFF"), max(1.0, size * 0.028))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for index, width_ratio in enumerate((0.30, 0.30, 0.18)):
        y = int(size * (0.375 + index * 0.075))
        painter.drawLine(
            int(size * 0.30),
            y,
            int(size * (0.30 + width_ratio)),
            y,
        )

    painter.end()
    return QIcon(pixmap)


def glyph_icon(name: str, size: int = 18, color: Optional[str] = None,
               background: Optional[str] = None) -> QIcon:
    """Draw the common small icons from vector paths (no image assets needed).

    Note: the bitmap is created at 2x supersampling with devicePixelRatio=2. Qt
    already doubles the coordinate system for us, so **do not call
    painter.scale()** — that would produce a 4x scale and clip the artwork.

    When color is None the current theme's secondary text colour is used, which
    is why icons must be regenerated after a theme switch.
    """
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    s = float(size)  # the logical coordinate system is size × size

    if background:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.28, s * 0.28)

    stroke = QColor(color or theme.palette().text_secondary)
    pen = QPen(stroke, max(1.2, s * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def p(x: float, y: float) -> QPointF:
        return QPointF(x * s, y * s)

    if name == "close":
        painter.drawLine(p(0.32, 0.32), p(0.68, 0.68))
        painter.drawLine(p(0.68, 0.32), p(0.32, 0.68))

    elif name == "pin":
        # pin: cap plus needle
        painter.drawRoundedRect(
            QRectF(s * 0.34, s * 0.16, s * 0.32, s * 0.24), s * 0.06, s * 0.06
        )
        painter.drawLine(p(0.50, 0.40), p(0.50, 0.82))

    elif name == "crop":
        # region select: four corner brackets
        arm = 0.17
        painter.drawPolyline([p(0.16, 0.33), p(0.16, 0.16), p(0.33, 0.16)])
        painter.drawPolyline([p(0.67, 0.16), p(0.84, 0.16), p(0.84, 0.33)])
        painter.drawPolyline([p(0.84, 0.67), p(0.84, 0.84), p(0.67, 0.84)])
        painter.drawPolyline([p(0.33, 0.84), p(0.16, 0.84), p(0.16, 0.67)])

    elif name == "gear":
        # sliders: far clearer than a gear at this size
        for index, (y, knob_x) in enumerate(((0.28, 0.36), (0.50, 0.66), (0.72, 0.44))):
            painter.drawLine(p(0.18, y), p(0.82, y))
            painter.setBrush(stroke)
            painter.drawEllipse(QPointF(knob_x * s, y * s), s * 0.085, s * 0.085)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    elif name == "copy":
        painter.drawRoundedRect(QRectF(s * 0.30, s * 0.14, s * 0.44, s * 0.44), s * 0.10, s * 0.10)
        painter.drawRoundedRect(QRectF(s * 0.16, s * 0.32, s * 0.44, s * 0.44), s * 0.10, s * 0.10)

    elif name == "stop":
        painter.setBrush(stroke)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(s * 0.30, s * 0.30, s * 0.40, s * 0.40), s * 0.10, s * 0.10)

    elif name == "sparkle":
        path = QPainterPath()
        path.moveTo(p(0.50, 0.12))
        path.cubicTo(p(0.56, 0.38), p(0.62, 0.44), p(0.88, 0.50))
        path.cubicTo(p(0.62, 0.56), p(0.56, 0.62), p(0.50, 0.88))
        path.cubicTo(p(0.44, 0.62), p(0.38, 0.56), p(0.12, 0.50))
        path.cubicTo(p(0.38, 0.44), p(0.44, 0.38), p(0.50, 0.12))
        painter.setBrush(stroke)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path)

    elif name == "sun":
        # light mode: a sun (click to switch to dark)
        painter.drawEllipse(QPointF(0.5 * s, 0.5 * s), s * 0.20, s * 0.20)
        for index in range(8):
            angle = math.radians(index * 45)
            painter.drawLine(
                QPointF(0.5 * s + math.cos(angle) * s * 0.30,
                        0.5 * s + math.sin(angle) * s * 0.30),
                QPointF(0.5 * s + math.cos(angle) * s * 0.43,
                        0.5 * s + math.sin(angle) * s * 0.43),
            )

    elif name == "moon":
        # dark mode: a crescent (click to switch to light)
        path = QPainterPath()
        path.addEllipse(QPointF(0.52 * s, 0.50 * s), s * 0.34, s * 0.34)
        cut = QPainterPath()
        cut.addEllipse(QPointF(0.68 * s, 0.38 * s), s * 0.30, s * 0.30)
        crescent = path.subtracted(cut)
        painter.setBrush(stroke)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(crescent)

    painter.end()
    return QIcon(pixmap)


def fit_pixmap(pixmap: QPixmap, size: QSize) -> QPixmap:
    """Scale a pixmap to fit exactly inside `size`, keeping the aspect ratio.

    Used to bake a screenshot down to its final display size once; the growth
    animation then rescales that already-small pixmap instead of the full-resolution
    original, which is what keeps the animation cheap.
    """
    if size.isEmpty() or size.width() <= 0 or size.height() <= 0:
        return pixmap
    return pixmap.scaled(
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def rounded_thumbnail(pixmap: QPixmap, width: int, height: int, radius: int = 8) -> QPixmap:
    """Return a copy of `pixmap` scaled to fit and clipped to rounded corners."""
    scaled = pixmap.scaled(
        width, height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    target = QPixmap(scaled.size())
    target.fill(Qt.GlobalColor.transparent)
    painter = QPainter(target)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRect(0, 0, scaled.width(), scaled.height()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    return target
