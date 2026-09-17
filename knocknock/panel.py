"""Main floating panel: an Apple-style input / result window.

Features: frameless rounded card with a drop shadow, draggable, resizable,
always-on-top, preset instructions, streaming answers, multi-turn follow-ups and
light / dark theme switching.

Layout strategy (so that frequent controls are always fully visible):
  * Preset buttons live in a ChipBar. The bar recomputes how many rows it needs
    for the current width and pins its own height to exactly that value — so no
    matter how narrow the window gets, the buttons wrap instead of being clipped.
  * The panel keeps Qt's default SetDefaultConstraint, letting the layout derive
    the window's minimum size, and resizeEvent clamps as a safety net. As a
    result it can never be dragged smaller than "fits everything".
  * The result area is the only stretchy region: it grows when the window grows
    and gets squeezed first when the window shrinks.
  * A screenshot is the one thing that resizes the window itself: the panel is
    built around the picture and grows around it step by step rather than
    squeezing it into a fixed strip (see `_start_reveal`).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Property,
    Signal,
)
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import capture as capture_mod
from . import i18n
from . import theme
from . import widgets as w
from .config import DEFAULT_IMAGE_PREVIEW, double_tap_key_label, presets_for
from .llm import LLMWorker, build_user_content

# ---------------------------------------------------------------- size constants
# The shadow margin must be at least as large as the shadow's actual reach,
# otherwise the window edge cuts a hard line through the shadow.
# Measured (selftest group 12 asserts this):
#   blur=26 + offsetY=7 reaches roughly 28px, so 30px fits it comfortably.
SHADOW_MARGIN = 30          # blank space around the card for the shadow (also the resize hot zone)
SHADOW_BLUR = 26
SHADOW_OFFSET_Y = 7
CARD_PADDING = 16
HEADER_HEIGHT = 30
INPUT_HEIGHT = 66
RESULT_MIN_HEIGHT = 130     # minimum result height (a few lines must always fit)
RESULT_IDEAL_HEIGHT = 240   # ideal result height when laying out automatically
CONTEXT_MAX_HEIGHT = 190    # maximum height of the context block when it holds text
CONTEXT_CHROME_HEIGHT = 46  # badge row + paddings inside the context frame (everything but the picture)
CONTEXT_PADDING_X = 22      # left + right padding inside the context frame
RESIZE_BORDER = 9           # how many pixels from an edge count as a resize hot zone
GRIP_INSET = 5
GRIP_SIZE = 9
DEFAULT_PANEL_WIDTH = 520
DEFAULT_MIN_WIDTH = 420

# ---------------------------------------------------------------- screenshot sizing
# A screenshot is context for the question, not the point of the window, so it is
# kept to a preview strip: the panel is built around the picture (see _start_reveal)
# but the picture never gets wider than IMAGE_MAX_WIDTH.
IMAGE_MAX_WIDTH = 400       # hard ceiling on the preview width, whatever the tier or the config
IMAGE_MIN_WIDTH = 240       # below this a screenshot stops being readable
IMAGE_PREVIEW_BOXES = {
    "small": QSize(240, 160),
    "medium": QSize(320, 220),   # default
    "large": QSize(400, 300),    # the ceiling: as wide as a preview is allowed to get
}
IMAGE_SCREEN_SHARE = 0.62   # hard ceiling on the window width, as a share of the screen
SCREEN_EDGE_GAP = 20        # keep at least this much room between panel and screen edge
REVEAL_MS = 760             # how long the panel takes to grow around a new screenshot
REVEAL_MIN_SCALE = 0.14     # where that growth starts (a window cannot start at zero)

# Qt's "no maximum" sentinel for widget sizes. PySide does not export
# QWIDGETSIZE_MAX from QtWidgets, so it is spelled out here.
WIDGET_SIZE_MAX = 16777215


class CardFrame(QFrame):
    """The card itself.

    A resize grip is painted in the bottom-right corner. The grip has to be
    painted **on the card**, not on the shadow margin outside it: on Windows the
    fully transparent area of a layered window (WA_TranslucentBackground) is
    **click-through**, so mouse events there go straight to the window beneath —
    they never arrive as hover or clicks.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._grip_hot = False

    def set_grip_hot(self, hot: bool) -> None:
        if hot != self._grip_hot:
            self._grip_hot = hot
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        color = QColor(theme.palette().text_tertiary)
        color.setAlpha(185 if self._grip_hot else 95)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(color, 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        x0 = self.width() - GRIP_INSET
        y0 = self.height() - GRIP_INSET
        for index in range(3):
            offset = index * 3
            painter.drawLine(
                x0 - GRIP_SIZE + offset, y0,
                x0, y0 - GRIP_SIZE + offset,
            )
        painter.end()


class ChipBar(QWidget):
    """Preset button bar: wraps automatically and is always exactly tall enough for its buttons."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.flow = w.FlowLayout(self, 0, 6, 6)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    # -------------------------------------------------- height calculation
    def _height_for(self, width: int) -> int:
        return max(26, self.flow.heightForWidth(max(1, width)))

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._height_for(width)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, self._height_for(self.width() or 320))

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(320, self._height_for(self.width() or 320))

    # -------------------------------------------------- width change -> re-wrap rows
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        wanted = self._height_for(self.width())
        # Pin the height: neither clips the buttons nor wastes vertical space
        if self.minimumHeight() != wanted or self.maximumHeight() != wanted:
            self.setFixedHeight(wanted)
        self.updateGeometry()


class ChatInput(QTextEdit):
    """Multi-line input: Enter sends, Shift+Enter inserts a newline, Esc hides the panel."""

    submitted = Signal()
    escape_pressed = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submitted.emit()
            return
        if key == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


class KnockPanel(QWidget):
    """The floating question-and-answer panel."""

    screenshot_requested = Signal()
    settings_requested = Signal()
    panel_hidden = Signal()
    theme_toggled = Signal(str)      # argument is the new mode: "light" / "dark"
    size_changed = Signal(int, int)  # the user resized the panel manually

    def __init__(self, cfg: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self._busy = False
        self._worker: Optional[LLMWorker] = None
        self._stream_buffer = ""
        self._messages: List[Dict[str, Any]] = []
        self._ctx: Dict[str, Any] = {"text": "", "image": None, "image_png": None, "source": "selection"}
        self._context_set = False      # whether set_context has been called (picks status vs. default subtitle)
        self._drag_offset: Optional[QPoint] = None
        self._on_top = bool(cfg.get("ui", {}).get("always_on_top", True))

        # screenshot sizing / growth animation
        self._image_target = QSize()          # size the picture is heading for while the panel grows
        self._image_source = None             # picture already scaled to _image_target (cheap to re-scale)
        self._image_reveal = 1.0              # 0..1 progress of the growth animation
        self._reveal_step = 1000              # the same, as per-mille for QPropertyAnimation
        self._reveal_from_width = 0
        self._reveal_from_height = 0
        self._reveal_target_height = 0
        self._reveal_animation: Optional[QPropertyAnimation] = None
        self._animating = False

        # resize state
        self._resize_edges = Qt.Edge(0)
        self._resize_origin = QPoint()
        self._resize_start = QRect()
        self._clamping = False
        self._user_size = QSize()      # the size the user dragged out (not one the panel took by itself)

        ui_cfg = cfg.get("ui", {})
        self._preferred_width = int(ui_cfg.get("width", DEFAULT_PANEL_WIDTH))
        self._min_width_cfg = int(ui_cfg.get("min_width", DEFAULT_MIN_WIDTH))
        self._user_resized = False

        self._build_ui()
        self._apply_window_flags()
        self.setMouseTracking(True)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(90)
        self._flush_timer.timeout.connect(self._flush_stream)

        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(80)
        self._thumb_timer.timeout.connect(self._on_thumb_timer)

        self._restore_saved_size()

    # ================================================================ UI
    def _build_ui(self) -> None:
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle(i18n.t("panel.title"))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN)
        outer.setSpacing(0)
        # Qt's default SetDefaultConstraint: the minimum window size is derived
        # from the layout, so it resizes freely but cannot be dragged too small.

        self.card = CardFrame(self)
        self.card.setObjectName("Card")
        outer.addWidget(self.card)
        # The card itself is the resize hot zone (the transparent margin around
        # it is not clickable on Windows).
        self.card.installEventFilter(self)

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(SHADOW_BLUR)
        self._shadow.setOffset(0, SHADOW_OFFSET_Y)
        self._shadow.setColor(theme.shadow_color())
        self.card.setGraphicsEffect(self._shadow)

        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(CARD_PADDING, 12, CARD_PADDING, 14)
        layout.setSpacing(10)

        # The whole top block (title bar / context / preset buttons / input /
        # action row) always stays pinned to the top of the card.
        #
        # It has to live in its own container with a **stretch at the bottom**:
        # otherwise, when the result area is hidden there is no stretchable item
        # left in the card layout, and Qt distributes the extra vertical space
        # across the gaps between the Preferred items — which shows up as
        # "the title bar drifts down whenever the window grows".
        top = QWidget(self.card)
        top_box = QVBoxLayout(top)
        top_box.setContentsMargins(0, 0, 0, 0)
        top_box.setSpacing(10)

        top_box.addWidget(self._build_header())
        top_box.addWidget(self._build_context())
        self.chips = self._build_chips()
        top_box.addWidget(self.chips)
        top_box.addWidget(self._build_input())
        top_box.addLayout(self._build_actions())
        top_box.addStretch(1)          # all surplus space lands here, so top items never move

        layout.addWidget(top)          # fixed content, does not stretch
        layout.addWidget(self._build_result(), 1)   # the only stretchable item

        self.setWindowOpacity(float(self.cfg.get("ui", {}).get("opacity", 0.99)))
        self.retranslate()
        self._refresh_compact()

    def _set_subtitle(self, long_text: str, short_text: str = "") -> None:
        self._subtitle_long = long_text
        self._subtitle_short = short_text or long_text
        self._refresh_compact()

    def _refresh_compact(self) -> None:
        """On a narrow panel swap long copy for short copy, so common controls always fit."""
        if not hasattr(self, "hint_label"):
            return
        narrow = self._content_width() < 420
        subtitle = self._subtitle_short if narrow else self._subtitle_long
        if self.subtitle_label.text() != subtitle:
            self.subtitle_label.setText(subtitle)
        hint = "" if narrow else i18n.t("panel.hint.send")
        if self.hint_label.text() != hint:
            self.hint_label.setText(hint)

    # ---------------------------------------------------------------- header
    def _build_header(self) -> QWidget:
        header = QWidget(self.card)
        header.setFixedHeight(HEADER_HEIGHT)
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(8)

        self.status_dot = QLabel("●", header)
        self._refresh_status_dot()
        row.addWidget(self.status_dot)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        self.title_label = QLabel("", header)
        self.title_label.setObjectName("Title")
        self.subtitle_label = w.ShrinkableLabel("", header)
        self.subtitle_label.setObjectName("Subtitle")
        self._subtitle_long = ""
        self._subtitle_short = ""
        title_box.addWidget(self.title_label)
        title_box.addWidget(self.subtitle_label)
        row.addLayout(title_box)
        row.addStretch(1)

        # All labels are set centrally in retranslate() (re-run to switch language)
        self.theme_btn = w.IconButton(w.glyph_icon("moon"), "", 26, parent=header)
        self.theme_btn.clicked.connect(self._toggle_theme)
        row.addWidget(self.theme_btn)

        self.pin_btn = w.IconButton(w.glyph_icon("pin"), "", 26, checkable=True, parent=header)
        self.pin_btn.setChecked(self._on_top)
        self.pin_btn.toggled.connect(self._toggle_on_top)
        row.addWidget(self.pin_btn)

        self.shot_btn = w.IconButton(w.glyph_icon("crop"), "", 26, parent=header)
        self.shot_btn.clicked.connect(self.screenshot_requested.emit)
        row.addWidget(self.shot_btn)

        self.gear_btn = w.IconButton(w.glyph_icon("gear"), "", 26, parent=header)
        self.gear_btn.clicked.connect(self.settings_requested.emit)
        row.addWidget(self.gear_btn)

        self.close_btn = w.IconButton(w.glyph_icon("close"), "", 26, parent=header)
        self.close_btn.clicked.connect(self.hide_panel)
        row.addWidget(self.close_btn)

        header.mousePressEvent = self._header_press  # type: ignore[method-assign]
        header.mouseMoveEvent = self._header_move  # type: ignore[method-assign]
        header.mouseReleaseEvent = self._header_release  # type: ignore[method-assign]
        self._refresh_icons()
        return header

    def retranslate(self) -> None:
        """Reapply every label in the current language (called after switching zh/en).

        The labels carry no state, so this only swaps the text; the subtitle and
        preset buttons depend on context and are recomputed along with it.
        """
        self.setWindowTitle(i18n.t("panel.title"))
        if hasattr(self, "title_label"):
            self.title_label.setText(i18n.t("panel.title"))
        if hasattr(self, "pin_btn"):
            self.pin_btn.setToolTip(i18n.t("panel.tooltip.pin"))
            self.shot_btn.setToolTip(i18n.t("panel.tooltip.crop"))
            self.gear_btn.setToolTip(i18n.t("panel.tooltip.settings"))
            self.close_btn.setToolTip(i18n.t("panel.tooltip.close"))
            self._refresh_icons()
        if hasattr(self, "input"):
            self.input.setPlaceholderText(i18n.t("panel.placeholder"))
        if hasattr(self, "copy_btn"):
            self.copy_btn.setText(i18n.t("panel.button.copy"))
            self.stop_btn.setText(i18n.t("panel.button.stop"))
            self.send_btn.setText(
                i18n.t("panel.button.sending") if self._busy else i18n.t("panel.button.send")
            )

        if self._context_set:
            self._refresh_context_view(animate=False)
        else:
            # The subtitle names the trigger key, so it has to follow the setting.
            label = double_tap_key_label(self.cfg)
            self._set_subtitle(
                i18n.t("panel.subtitle.long", key=label),
                i18n.t("panel.subtitle.short", key=label),
            )
        self._refresh_compact()
        self._rebuild_chips()

    def _refresh_icons(self) -> None:
        """Regenerate every icon for the current theme (icon colours are baked into the bitmaps)."""
        if not hasattr(self, "theme_btn"):
            return
        self.theme_btn.setIcon(w.glyph_icon("sun" if theme.is_dark() else "moon"))
        self.theme_btn.setToolTip(
            i18n.t("theme.switch_to_light") if theme.is_dark() else i18n.t("theme.switch_to_dark")
        )
        self.pin_btn.setIcon(w.glyph_icon("pin"))
        self.shot_btn.setIcon(w.glyph_icon("crop"))
        self.gear_btn.setIcon(w.glyph_icon("gear"))
        self.close_btn.setIcon(w.glyph_icon("close"))

    def _refresh_status_dot(self) -> None:
        palette = theme.palette()
        color = palette.warning if self._busy else palette.accent
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 10px;")

    # ---------------------------------------------------------------- context
    def _build_context(self) -> QWidget:
        self.context_frame = QFrame(self.card)
        self.context_frame.setObjectName("Context")
        self.context_frame.setMaximumHeight(CONTEXT_MAX_HEIGHT)
        box = QVBoxLayout(self.context_frame)
        box.setContentsMargins(11, 9, 11, 10)
        box.setSpacing(6)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.context_badge = QLabel("", self.context_frame)
        self.context_badge.setObjectName("Badge")
        top.addWidget(self.context_badge)
        top.addStretch(1)
        self.context_meta = QLabel("", self.context_frame)
        self.context_meta.setObjectName("Hint")
        top.addWidget(self.context_meta)
        box.addLayout(top)

        self.context_text = QLabel("", self.context_frame)
        self.context_text.setObjectName("ContextText")
        self.context_text.setWordWrap(True)
        self.context_text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.context_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.context_text, 1)

        self.context_image = QLabel("", self.context_frame)
        self.context_image.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.context_image.hide()
        box.addWidget(self.context_image)

        self.context_frame.hide()
        return self.context_frame

    # ---------------------------------------------------------------- screenshot block
    def _screen_available(self) -> QRect:
        """Available geometry of the screen the panel currently lives on."""
        screen = QGuiApplication.screenAt(self.frameGeometry().topLeft())
        if screen is None:
            screen = QGuiApplication.screenAt(self.frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect(0, 0, 1280, 800)

    def _panel_chrome_height(self) -> int:
        """Vertical space the panel needs besides the picture itself.

        Spelled out from the layout constants on purpose: the height budget for a
        screenshot must not depend on the size the panel happens to have right
        now, or the first estimate would feed back into itself.
        """
        chips = max(26, self.chips._height_for(self._content_width()))
        actions = max(30, self.send_btn.sizeHint().height())
        return (
            SHADOW_MARGIN * 2 + 12 + 14      # window margin + card padding
            + HEADER_HEIGHT + 10             # title bar
            + CONTEXT_CHROME_HEIGHT + 10     # context badge row
            + chips + 10                     # preset buttons
            + INPUT_HEIGHT + 10              # input box
            + actions + 10                   # action row
            + RESULT_MIN_HEIGHT              # result area at its minimum
        )

    def _image_height_budget(self) -> int:
        """Hard ceiling on the picture height: beyond this the panel leaves the screen."""
        room = self._screen_available().height() - SCREEN_EDGE_GAP * 2 - self._panel_chrome_height()
        return int(max(1, room))

    def _window_width_for(self, image_width: int) -> int:
        """Window width that leaves exactly `image_width` for the picture itself."""
        return image_width + (SHADOW_MARGIN + CARD_PADDING) * 2 + CONTEXT_PADDING_X

    def _image_box(self) -> QSize:
        """The room a screenshot may take, from the "screenshot size" preference.

        The preference is a box, not just a height: a tall capture would otherwise
        keep its full width and turn the panel into a big empty frame. The width is
        then clamped to IMAGE_MAX_WIDTH, so no tier — and no hand-edited config —
        can make the preview wider than that.
        """
        wanted = str(self.cfg.get("ui", {}).get("image_preview", DEFAULT_IMAGE_PREVIEW)).lower()
        box = IMAGE_PREVIEW_BOXES.get(wanted, IMAGE_PREVIEW_BOXES[DEFAULT_IMAGE_PREVIEW])
        screen = self._screen_available()
        frame = (SHADOW_MARGIN + CARD_PADDING) * 2 + CONTEXT_PADDING_X
        # Never wider than the ceiling or the screen, and never so tall that the
        # panel (chrome included) would run off the bottom of the display.
        width = min(box.width(), IMAGE_MAX_WIDTH,
                    max(IMAGE_MIN_WIDTH, int(screen.width() * IMAGE_SCREEN_SHARE) - frame))
        height = min(box.height(), self._image_height_budget())
        return QSize(width, max(1, height))

    def _image_display_size(self, image: QPixmap) -> QSize:
        """How large a screenshot should be drawn inside the panel.

        The picture is fitted into the preferred box — scaled down but never up,
        except up to the minimum readable width — and its aspect ratio is kept.
        """
        box = self._image_box()
        ratio = image.height() / max(1, image.width())

        width = min(image.width(), box.width())
        height = width * ratio
        if height > box.height():
            width, height = box.height() / ratio, float(box.height())
        if width < IMAGE_MIN_WIDTH:
            width = min(IMAGE_MIN_WIDTH, box.width())
            height = width * ratio
        if width > box.width() or height > box.height():
            # The minimum readable width can still overshoot a small box; the box
            # wins, because the panel always has to fit on the screen.
            shrink = min(box.width() / max(width, 1), box.height() / max(height, 1))
            width, height = width * shrink, height * shrink
        return QSize(max(1, int(round(width))), max(1, int(round(height))))

    def _prepare_image(self, animate: bool) -> None:
        """Work out the picture size and either grow the panel around it or just apply it."""
        image = self._ctx.get("image")
        if image is None:
            return
        target = self._image_display_size(image)
        if target.isEmpty():
            return
        self._image_target = target
        # Scale once to the final size; the growth animation then only has to
        # re-scale this already-small pixmap, which is cheap enough to do per frame.
        self._image_source = w.fit_pixmap(image, target)
        if animate:
            self._start_reveal()
        else:
            self._image_reveal = 1.0
            self._apply_image_size(target)
            self._apply_natural_size()

    def _apply_image_size(self, size: QSize) -> None:
        """Draw the picture at `size` and pin the context frame to exactly fit it."""
        if self._image_source is None or size.isEmpty():
            return
        self.context_image.setPixmap(
            w.rounded_thumbnail(self._image_source, size.width(), size.height(), 8)
        )
        self.context_image.setFixedSize(size)
        self.context_frame.setFixedHeight(CONTEXT_CHROME_HEIGHT + size.height())
        self.layout().activate()

    def _reset_image_block(self) -> None:
        """Drop the screenshot sizing constraints so the context frame can size itself again."""
        self._image_target = QSize()
        self._image_source = None
        self._image_reveal = 1.0
        self.context_image.setMinimumSize(0, 0)
        self.context_image.setMaximumSize(WIDGET_SIZE_MAX, WIDGET_SIZE_MAX)
        self.context_frame.setMinimumHeight(0)
        self.context_frame.setMaximumHeight(CONTEXT_MAX_HEIGHT)

    def _refresh_context_image(self) -> None:
        """Re-render the thumbnail after a width change (keeps it rounded and proportional)."""
        image = self._ctx.get("image")
        if image is None or self.context_image.isHidden() or self._animating:
            return
        target = self._image_display_size(image)
        if target.isEmpty():
            return
        self._image_target = target
        self._image_source = w.fit_pixmap(image, target)
        self._apply_image_size(target)

    def _on_thumb_timer(self) -> None:
        """After a resize settled, redraw the thumbnail and make sure the content still fits."""
        if self._animating:
            return
        self._refresh_context_image()
        self._ensure_fits()

    # ---------------------------------------------------------------- growth animation
    def _start_reveal(self) -> None:
        """Grow the panel around a brand-new screenshot, step by step instead of in one jump."""
        target = self._image_target
        if target.isEmpty():
            self._apply_natural_size()
            return

        self._cancel_reveal()
        self._reveal_from_width = self.width()
        self._reveal_from_height = self.height()
        # Apply the final picture size once, purely to measure the panel it needs,
        # then collapse back and grow into that size.
        self._apply_image_size(target)
        self._reveal_target_height = self._min_height()
        if self.result.isVisible():
            self._reveal_target_height += RESULT_IDEAL_HEIGHT - RESULT_MIN_HEIGHT

        self._animating = True
        self._reveal_step = int(REVEAL_MIN_SCALE * 1000)
        self._apply_reveal(self._reveal_step / 1000.0)

        animation = QPropertyAnimation(self, b"revealStep", self)
        animation.setDuration(REVEAL_MS)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animation.setStartValue(self._reveal_step)
        animation.setEndValue(1000)
        animation.finished.connect(self._on_reveal_finished)
        self._reveal_animation = animation
        animation.start()

    def _apply_reveal(self, scale: float) -> None:
        """One frame of the growth animation: scale the picture, then the window around it."""
        target = self._image_target
        if self._image_source is None or target.isEmpty():
            return
        scale = max(1e-3, min(1.0, float(scale)))
        self._image_reveal = scale

        size = QSize(
            max(1, int(round(target.width() * scale))),
            max(1, int(round(target.height() * scale))),
        )
        self.context_image.setPixmap(
            w.rounded_thumbnail(self._image_source, size.width(), size.height(),
                                max(1, int(round(8 * scale))))
        )
        self.context_image.setFixedSize(size)
        self.context_frame.setFixedHeight(CONTEXT_CHROME_HEIGHT + size.height())
        self.layout().activate()

        # Window size: interpolated from wherever the panel was to the size the
        # finished picture needs — so a small picture also lets the panel settle
        # back down — but never smaller than the picture or the panel minimum.
        final_width = self._window_width_for(target.width())
        width = self._reveal_from_width + (final_width - self._reveal_from_width) * scale
        width = max(width,
                    size.width() + (SHADOW_MARGIN + CARD_PADDING) * 2 + CONTEXT_PADDING_X,
                    self._min_width())
        limit = max(self._min_width(), self._screen_available().width() - SCREEN_EDGE_GAP * 2)
        width = int(min(width, limit))

        height = self._reveal_from_height + (self._reveal_target_height - self._reveal_from_height) * scale
        height = int(max(round(height), self._min_height()))
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)
        self._clamp_to_screen()

    def _on_reveal_finished(self) -> None:
        self._animating = False
        self._reveal_animation = None
        self._reveal_step = 1000
        self._apply_reveal(1.0)
        self._apply_natural_size()
        self._thumb_timer.start()

    def _cancel_reveal(self) -> None:
        if self._reveal_animation is not None:
            self._reveal_animation.stop()
            self._reveal_animation = None
        self._animating = False

    def _clamp_to_screen(self) -> None:
        """Keep the panel on screen while it grows (it expands downwards by default)."""
        area = self._screen_available()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    # ---------------------------------------------------------------- presets
    def _build_chips(self) -> QWidget:
        bar = ChipBar(self.card)
        self.chips_layout = bar.flow
        self.chip_buttons: List[QPushButton] = []
        self._rebuild_chips()
        return bar

    def _rebuild_chips(self) -> None:
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self.chip_buttons = []

        parent = self.chips_layout.parentWidget()
        for preset in presets_for(self.cfg):
            name = str(preset.get("name", "")).strip()
            if not name:
                continue
            button = QPushButton(name, parent)
            button.setObjectName("Chip")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _=False, p=preset: self._on_preset(p))
            self.chips_layout.addWidget(button)
            self.chip_buttons.append(button)

        if parent is not None:
            parent.setFixedHeight(max(26, self.chips_layout.heightForWidth(max(1, parent.width()))))
            parent.updateGeometry()

    # ---------------------------------------------------------------- input area
    def _build_input(self) -> QWidget:
        self.input = ChatInput(self.card)
        self.input.setObjectName("Input")
        self.input.setFixedHeight(INPUT_HEIGHT)
        self.input.setPlaceholderText(i18n.t("panel.placeholder"))
        self.input.setTabChangesFocus(True)
        self.input.submitted.connect(lambda: self._send(None))
        self.input.escape_pressed.connect(self.hide_panel)
        return self.input

    # ---------------------------------------------------------------- action row
    def _build_actions(self):
        row = QHBoxLayout()
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(6)

        self.hint_label = w.ShrinkableLabel("", self.card)
        self.hint_label.setObjectName("Hint")
        row.addWidget(self.hint_label)
        row.addStretch(1)

        self.copy_btn = QPushButton(i18n.t("panel.button.copy"), self.card)
        self.copy_btn.setObjectName("Ghost")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_result)
        row.addWidget(self.copy_btn)

        self.stop_btn = QPushButton(i18n.t("panel.button.stop"), self.card)
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.hide()
        self.stop_btn.clicked.connect(self._stop_request)
        row.addWidget(self.stop_btn)

        self.send_btn = QPushButton(i18n.t("panel.button.send"), self.card)
        self.send_btn.setObjectName("Primary")
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setDefault(True)
        self.send_btn.clicked.connect(lambda: self._send(None))
        row.addWidget(self.send_btn)
        return row

    # ---------------------------------------------------------------- result area
    def _build_result(self) -> QWidget:
        self.result = QTextBrowser(self.card)
        self.result.setObjectName("Result")
        self.result.setOpenExternalLinks(True)
        self.result.setMinimumHeight(RESULT_MIN_HEIGHT)
        self.result.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.result.hide()
        return self.result

    # ================================================================ sizing
    def _content_width(self) -> int:
        return max(160, self.card.width() - CARD_PADDING * 2)

    def _min_height(self) -> int:
        """Minimum height the layout requires (changes as preset buttons wrap)."""
        return max(240, self.layout().minimumSize().height())

    def _min_width(self) -> int:
        return max(self._min_width_cfg, self.layout().minimumSize().width())

    def _natural_size(self) -> QSize:
        """The size that exactly fits the current content (result area at its ideal height)."""
        width = self._preferred_width
        target = self._image_target
        if self._ctx.get("image") is not None and not target.isEmpty():
            # A screenshot decides the width: the panel is built around the picture
            # (this is what keeps "grow to fit the picture" from being undone).
            width = self._window_width_for(target.width())
        height = self._min_height()
        if self.result.isVisible():
            height += RESULT_IDEAL_HEIGHT - RESULT_MIN_HEIGHT
        return QSize(width, height)

    def _apply_natural_size(self) -> None:
        """Resize to the natural size; if the user resized manually, only guarantee it fits."""
        if self._user_resized:
            self._ensure_fits()
            return
        size = self._natural_size()
        self.resize(max(size.width(), self._min_width()), max(size.height(), self._min_height()))
        self._clamp_to_screen()

    def _ensure_fits(self) -> None:
        """Make sure the window is no smaller than the layout's minimum size.

        This has to be called explicitly: when the result area expands the window
        does not fire resizeEvent by itself, and without an active clamp the
        layout would overflow the card and be clipped (which looks like "the model
        returned nothing").
        """
        width = max(self.width(), self._min_width())
        height = max(self.height(), self._min_height())
        if (width, height) == (self.width(), self.height()):
            return
        self._clamping = True
        self.resize(width, height)
        self._clamping = False
        self._clamp_to_screen()

    def _remember_size(self) -> None:
        """Persist the size the user chose — but only while the panel still has it.

        The panel resizes itself around a screenshot. That size is not a size the
        user ever asked for, and saving it would quietly replace the one they did
        ask for (which is how a capture ends up resizing the panel *permanently*:
        the next launch would restore the picture-fitted size instead).
        """
        if not self._user_resized or self._user_size != self.size():
            return
        self.size_changed.emit(self.width(), self.height())

    def reset_size(self) -> None:
        """Return to the default natural size (called when "Reset panel size" is clicked)."""
        self._cancel_reveal()
        self._user_resized = False
        self._user_size = QSize()
        self.cfg.get("ui", {}).pop("last_size", None)
        self._apply_natural_size()

    def _restore_saved_size(self) -> None:
        saved = self.cfg.get("ui", {}).get("last_size")
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            try:
                width, height = int(saved[0]), int(saved[1])
            except (TypeError, ValueError):
                width = height = 0
            if width > 0 and height > 0:
                self._user_resized = True
                self._user_size = QSize(width, height)
                self.resize(width, height)
                return
        self._apply_natural_size()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Safety clamp: however it is dragged, it can never go below the size
        # needed to fit all the content.
        if not self._clamping:
            width = max(self.width(), self._min_width())
            height = max(self.height(), self._min_height())
            if (width, height) != (self.width(), self.height()):
                self._clamping = True
                self.resize(width, height)
                self._clamping = False
        self._thumb_timer.start()
        self._refresh_compact()
        self.update()

    # ---------------------------------------------------------------- resize interaction
    def _edges_for(self, pos: QPoint, rect: QRect) -> Qt.Edge:
        """Whether pos falls within the four edge hot zones of rect (same coordinate system)."""
        edges = Qt.Edge(0)
        if abs(pos.x() - rect.left()) <= RESIZE_BORDER:
            edges |= Qt.Edge.LeftEdge
        elif abs(pos.x() - rect.right()) <= RESIZE_BORDER:
            edges |= Qt.Edge.RightEdge
        if abs(pos.y() - rect.top()) <= RESIZE_BORDER:
            edges |= Qt.Edge.TopEdge
        elif abs(pos.y() - rect.bottom()) <= RESIZE_BORDER:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _edges_at(self, pos: QPoint) -> Qt.Edge:
        """Hot zones in window coordinates = card edges ∪ window edges.

        Only the card edges are genuinely clickable (the transparent margin
        around the card is click-through on Windows).
        """
        return self._edges_for(pos, self.card.geometry()) | self._edges_for(pos, self.rect())

    @staticmethod
    def _cursor_for(edges: Qt.Edge) -> Qt.CursorShape:
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        if top or bottom:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def _begin_resize(self, edges: Qt.Edge, global_pos: QPoint) -> None:
        self._resize_edges = edges
        self._resize_origin = global_pos
        self._resize_start = QRect(self.geometry())

    def _finish_resize(self) -> bool:
        if not self._resize_edges:
            return False
        self._resize_edges = Qt.Edge(0)
        self._user_resized = True
        self._user_size = QSize(self.size())
        self.size_changed.emit(self.width(), self.height())
        return True

    def _perform_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_origin
        rect = QRect(self._resize_start)
        min_width = self._min_width()
        min_height = self._min_height()
        edges = self._resize_edges

        if edges & Qt.Edge.LeftEdge:
            rect.setLeft(min(rect.left() + delta.x(), rect.right() - min_width + 1))
        if edges & Qt.Edge.RightEdge:
            rect.setRight(max(rect.right() + delta.x(), rect.left() + min_width - 1))
        if edges & Qt.Edge.TopEdge:
            rect.setTop(min(rect.top() + delta.y(), rect.bottom() - min_height + 1))
        if edges & Qt.Edge.BottomEdge:
            rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + min_height - 1))

        self.setGeometry(rect)
        self._user_resized = True
        self._user_size = QSize(rect.size())

    # -------------------------------------------------- mouse on the card (the path that actually works)
    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.card:
            etype = event.type()
            if etype == QEvent.Type.MouseMove:
                self._on_card_mouse_move(event)
            elif etype == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    edges = self._edges_for(event.position().toPoint(), self.card.rect())
                    if edges:
                        self._begin_resize(edges, event.globalPosition().toPoint())
                        return True
            elif etype == QEvent.Type.MouseButtonRelease:
                if self._finish_resize():
                    return True
            elif etype == QEvent.Type.Leave:
                self.card.set_grip_hot(False)
                self.card.unsetCursor()
        return super().eventFilter(obj, event)

    def _on_card_mouse_move(self, event) -> None:
        pos = event.position().toPoint()
        if self._resize_edges and (event.buttons() & Qt.MouseButton.LeftButton):
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return
        card_rect = self.card.rect()
        edges = self._edges_for(pos, card_rect)
        self.card.setCursor(self._cursor_for(edges))
        self.card.set_grip_hot(
            pos.x() > card_rect.width() - 60 and pos.y() > card_rect.height() - 60
        )

    # -------------------------------------------------- mouse on the panel (margin area; clickable on some platforms)
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._begin_resize(edges, event.globalPosition().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resize_edges and (event.buttons() & Qt.MouseButton.LeftButton):
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return
        self.setCursor(self._cursor_for(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._finish_resize():
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ================================================================ window behaviour
    def _apply_window_flags(self) -> None:
        flags = (
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        )
        if self._on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()

    def _toggle_on_top(self, checked: bool) -> None:
        self._on_top = checked
        self.cfg.setdefault("ui", {})["always_on_top"] = checked
        self._apply_window_flags()
        self.raise_()

    def _toggle_theme(self) -> None:
        self.theme_toggled.emit("light" if theme.is_dark() else "dark")

    # ---------------------------------------------------------------- dragging
    def _header_press(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _header_move(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def _header_release(self, event) -> None:
        self._drag_offset = None

    # ================================================================ public API
    def set_context(self, text: str = "", image: Optional[QPixmap] = None,
                    source: str = "selection", clear_result: bool = True) -> None:
        """Set the "selected content" for this question."""
        self._cancel_reveal()
        self._ctx = {
            "text": (text or "").strip(),
            "image": image,
            "image_png": capture_mod.pixmap_to_png_bytes(image) if image is not None else None,
            "source": source,
        }
        self._messages = []  # new context -> reset the multi-turn conversation
        self._context_set = True

        if clear_result:
            # Without the relayout: the context view below decides the new size in
            # one step, so the panel must not shrink and grow again on the way.
            self._clear_result(relayout=False)

        # The preset buttons are rebuilt first: their row count feeds the height
        # budget the screenshot is fitted into.
        self._rebuild_chips()
        self._refresh_context_view()

    def _refresh_context_view(self, animate: bool = True) -> None:
        """Refresh the badge, character count and subtitle for the current context (text / screenshot / empty).

        Split into its own method so a language switch can recompute in place
        without throwing the context away and re-setting it. Only a context that
        just arrived is grown into view; re-rendering an existing one (language
        switch, theme switch) applies its size straight away.
        """
        text = self._ctx.get("text") or ""
        image = self._ctx.get("image")
        has_text = bool(text)
        has_image = image is not None

        if not has_text and not has_image:
            self.context_frame.hide()
            self._reset_image_block()
            self._set_subtitle(
                i18n.t("panel.state.no_context.long"), i18n.t("panel.state.no_context.short")
            )
            self._apply_natural_size()
            return

        self.context_frame.show()
        if has_image:
            self.context_badge.setText(i18n.t("panel.badge.image"))
            self.context_text.hide()
            self.context_image.show()
            self.context_meta.setText(f"{image.width()} × {image.height()} px")
            self._prepare_image(animate and not self._animating)
        else:
            self.context_badge.setText(i18n.t("panel.badge.text"))
            self.context_image.hide()
            self._reset_image_block()
            # Roughly 13px per Chinese character and 7px per English character;
            # estimate the line width per language so English is not cut mid-line.
            char_px = 7 if i18n.is_english() else 13
            limit = max(120, (self._content_width() // char_px) * 5)
            preview = text
            if len(preview) > limit:
                preview = preview[:limit] + " …"
            self.context_text.setText(preview)
            self.context_text.show()
            self.context_meta.setText(i18n.t("panel.meta.chars", count=len(text)))
            self._apply_natural_size()

        self._set_subtitle(
            i18n.t("panel.state.image.long") if has_image else i18n.t("panel.state.text.long"),
            i18n.t("panel.state.image.short") if has_image else i18n.t("panel.state.text.short"),
        )

    def show_panel(self, near_cursor: bool = True) -> None:
        if near_cursor:
            self._move_near_cursor()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.FocusReason.OtherFocusReason)

    def hide_panel(self) -> None:
        self._remember_size()
        self.hide()
        self.panel_hidden.emit()
        self.panel_hidden.emit()

    def apply_config(self, cfg: Dict[str, Any]) -> None:
        """Called after the settings dialog saves."""
        self.cfg = cfg
        ui_cfg = cfg.get("ui", {})
        self._on_top = bool(ui_cfg.get("always_on_top", True))
        self.pin_btn.setChecked(self._on_top)
        self.setWindowOpacity(float(ui_cfg.get("opacity", 0.99)))

        new_width = int(ui_cfg.get("width", DEFAULT_PANEL_WIDTH))
        self._min_width_cfg = int(ui_cfg.get("min_width", DEFAULT_MIN_WIDTH))
        if new_width != self._preferred_width:
            # Panel width changed -> discard the user's manual size, back to natural
            self._preferred_width = new_width
            self._user_resized = False
            self.cfg.get("ui", {}).pop("last_size", None)

        self._apply_window_flags()
        self._rebuild_chips()

        # A screenshot may still be on screen: re-fit it in place, so a changed
        # "screenshot size" preference takes effect without another capture.
        refit = False
        image = self._ctx.get("image")
        if image is not None and not self.context_image.isHidden():
            self._cancel_reveal()
            target = self._image_display_size(image)
            refit = target != self._image_target
            if refit:
                self._image_target = target
                self._image_source = w.fit_pixmap(image, target)

        if refit:
            self._start_reveal()      # grows — or settles back down — smoothly
        else:
            self._apply_natural_size()

    def apply_theme(self) -> None:
        """Refresh colour-dependent elements after a theme switch."""
        self._shadow.setColor(theme.shadow_color())
        self._refresh_icons()
        self._refresh_status_dot()
        self.update()

    # ---------------------------------------------------------------- positioning
    def _move_near_cursor(self) -> None:
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available: QRect = screen.availableGeometry()
        size = self.size()

        x = cursor.x() + 16
        y = cursor.y() + 16
        if x + size.width() > available.right():
            x = cursor.x() - size.width() - 16
        if y + size.height() > available.bottom():
            y = cursor.y() - size.height() - 16
        x = max(available.left(), min(x, available.right() - size.width()))
        y = max(available.top(), min(y, available.bottom() - size.height()))
        self.move(QPoint(x, y))

    # ================================================================ request flow
    def _on_preset(self, preset: Dict[str, Any]) -> None:
        prompt = str(preset.get("prompt", "")).strip()
        self.input.setPlainText(prompt)
        if self.cfg.get("behavior", {}).get("auto_send_on_preset", True):
            self._send(prompt)

    def _send(self, instruction: Optional[str]) -> None:
        if self._busy:
            return
        text = (instruction if instruction is not None else self.input.toPlainText()).strip()
        has_context = bool(self._ctx.get("text")) or self._ctx.get("image_png") is not None

        if not text and not has_context:
            self._show_result_text(i18n.t("panel.msg.need_context"))
            return
        if not text and has_context:
            text = i18n.t("llm.wrap.ask_default")

        api_cfg = dict(self.cfg.get("api", {}))
        if not str(api_cfg.get("api_key", "")).strip():
            self._show_result_text(i18n.t("panel.msg.no_api_key"))
            return

        if not self._messages:
            system_prompt = str(api_cfg.get("system_prompt") or "").strip()
            self._messages.append(
                {"role": "system", "content": system_prompt or i18n.t("llm.fallback_system")}
            )
            self._messages.append({"role": "user", "content": build_user_content(self._ctx, text)})
        else:
            self._messages.append({"role": "user", "content": text})

        self._trim_history()

        self._stream_buffer = ""
        self._show_result_text("")
        self._set_busy(True)
        self.input.clear()

        self._worker = LLMWorker(api_cfg, self._messages, self)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _trim_history(self) -> None:
        limit = int(self.cfg.get("behavior", {}).get("max_history_turns", 6)) * 2
        if len(self._messages) <= limit + 1:
            return
        system = self._messages[0]
        self._messages = [system] + self._messages[-limit:]

    # ---------------------------------------------------------------- streaming rendering
    def _on_chunk(self, delta: str) -> None:
        self._stream_buffer += delta
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_stream(self) -> None:
        if not self._stream_buffer:
            self._flush_timer.stop()
            return
        self._render_markdown(self._stream_buffer)
        self._flush_timer.stop()

    def _on_succeeded(self, full_text: str) -> None:
        self._flush_timer.stop()
        text = full_text or self._stream_buffer
        if text:
            self._render_markdown(text)
            self._messages.append({"role": "assistant", "content": text})
            self.copy_btn.setEnabled(True)
        elif not self._stream_buffer:
            self._render_markdown(i18n.t("panel.msg.empty_reply"))
        self._set_busy(False)

    def _on_failed(self, message: str) -> None:
        self._flush_timer.stop()
        prefix = self._stream_buffer
        body = (prefix + "\n\n" if prefix else "") + \
            f"{i18n.t('panel.msg.request_failed')}\n\n{message}"
        self._render_markdown(body)
        self._set_busy(False)

    def _render_markdown(self, text: str) -> None:
        self._ensure_result_visible()
        self.result.setMarkdown(text)
        scrollbar = self.result.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _ensure_result_visible(self) -> None:
        """Make sure the result area is expanded (whichever path got us into rendering)."""
        if self.result.isHidden():
            self.result.show()
            self._apply_natural_size()

    def _show_result_text(self, text: str) -> None:
        if not text:
            self._clear_result()
            return
        self._render_markdown(text)

    def _clear_result(self, relayout: bool = True) -> None:
        self._stream_buffer = ""
        self.copy_btn.setEnabled(False)
        self.result.setPlainText("")
        self.result.hide()
        if relayout:
            self._apply_natural_size()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.send_btn.setEnabled(not busy)
        self.send_btn.setText(
            i18n.t("panel.button.sending") if busy else i18n.t("panel.button.send")
        )
        self.stop_btn.setVisible(busy)
        self._refresh_status_dot()
        if busy:
            self._render_markdown(i18n.t("panel.msg.generating"))

    def _stop_request(self) -> None:
        if self._worker is not None:
            self._worker.stop()
        self._set_busy(False)

    def _copy_result(self) -> None:
        text = self._stream_buffer or self.result.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    # ================================================================ events
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.cfg.get("behavior", {}).get("close_on_esc", True):
            self.hide_panel()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- animation property
    # QPropertyAnimation needs a real Qt property to interpolate, so the growth
    # progress is exposed in per-mille (integers interpolate cleanly, and a
    # third decimal of a pixel is not worth animating).
    def _get_reveal_step(self) -> int:
        return self._reveal_step

    def _set_reveal_step(self, value: int) -> None:
        self._reveal_step = int(value)
        if self._animating:
            self._apply_reveal(self._reveal_step / 1000.0)

    revealStep = Property(int, _get_reveal_step, _set_reveal_step)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._remember_size()
        self.hide()
        event.ignore()
