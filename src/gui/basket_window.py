"""Square floating window — drag-drop file staging surface."""

import random
import uuid
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QMimeData, QPoint, QRectF, QSize, Qt, QUrl, QVariantAnimation
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
    QGridLayout, QScrollArea,
)  # fmt: skip

from ..config import config_manager
from ..logger import get_logger, set_trace_id
from ..utils import FileBasket, cleanup_temp_zip, create_temp_zip, tr, language_changed
from .platform import PlatformCompatMixin
from .thumbnail import ThumbnailProvider
from .theme import theme_manager

logger = get_logger(__name__)


class _ThumbnailWidget(QWidget):
    """Renders the system file icon as thumbnail."""

    def __init__(self, path: Path, card_size: int, provider: ThumbnailProvider, parent=None):
        super().__init__(parent)
        self._path = path
        self._provider = provider
        self.setFixedSize(card_size, card_size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._provider.draw(painter, self._path, 0, 0, self.width())
        finally:
            painter.end()


class _FileGridItem(QWidget):
    """A single file thumbnail card with its filename below."""

    def __init__(
        self,
        path: Path,
        font_scale: float,
        card_size: int,
        provider: ThumbnailProvider,
        on_close=None,
        parent=None
    ):
        super().__init__(parent)
        self._path = path
        self.setFixedWidth(card_size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)  # gap between thumbnail and label

        # Thumbnail with close-button overlay
        thumb_container = QWidget()
        thumb_container.setFixedSize(card_size, card_size)
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        self.thumb = _ThumbnailWidget(path, card_size, provider)
        thumb_layout.addWidget(self.thumb)

        self._close_btn = QPushButton(thumb_container)
        self._close_btn.setObjectName("courier-close-btn-small")
        self._close_btn.setIconSize(QSize(10, 10))
        self._close_btn.setIcon(theme_manager.close_icon)
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_margin = 3
        self._close_btn.move(card_size - 20 - btn_margin, btn_margin)
        self._close_btn.raise_()
        if on_close:
            self._close_btn.clicked.connect(lambda: on_close(self._path))

        layout.addWidget(thumb_container, 0, Qt.AlignmentFlag.AlignCenter)

        # Filename label
        self.label = QLabel()
        self.label.setObjectName("courier-file-label")  # mount theme color from theme.py
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        f = QFont()
        f.setPointSize(round(9 * font_scale))
        self.label.setFont(f)

        # Elide middle for long filenames (e.g. "very_long_file...name.pdf")
        metrics = self.label.fontMetrics()
        elided_text = metrics.elidedText(path.name, Qt.TextElideMode.ElideMiddle, card_size)
        self.label.setText(elided_text)
        self.label.setToolTip(path.name)  # shows full filename on hover

        layout.addWidget(self.label)


class _FileGridWindow(QWidget, PlatformCompatMixin):
    """An expanded floating window displaying files in a responsive grid."""

    def __init__(
        self,
        files: list[Path],
        font_scale: float,
        card_size: int,
        radius: int,
        provider: ThumbnailProvider,
        on_file_remove=None,
        parent=None,
    ):
        super().__init__(parent)
        self._radius = radius
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("courier-grid-content")
        content.setStyleSheet("#courier-grid-content { background: transparent; }")
        grid = QGridLayout(content)
        grid.setSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)

        N = len(files)
        if N == 1:
            cols, vis_rows = 1, 1
        elif N == 2:
            cols, vis_rows = 2, 1
        elif N in (3, 4):
            cols, vis_rows = 2, 2
        else:
            cols, vis_rows = 3, 2

        for i, path in enumerate(files):
            item = _FileGridItem(path, font_scale, card_size, provider, on_close=on_file_remove)
            r, c = divmod(i, cols)
            grid.addWidget(item, r, c)

        self.scroll_area.setWidget(content)
        layout.addWidget(self.scroll_area)

        # Calculate exact window size based on grid parameters
        dummy_f = QFont()
        dummy_f.setPointSize(round(9 * font_scale))
        from PySide6.QtGui import QFontMetrics
        label_h = QFontMetrics(dummy_f).height()

        item_w = card_size
        item_h = card_size + 4 + label_h

        win_w = cols * item_w + (cols - 1) * 10 + 30  # 30 = left + right margins
        win_h = vis_rows * item_h + (vis_rows - 1) * 10 + 30  # 30 = top + bottom margins
        self.setFixedSize(win_w, win_h)
        self.setStyleSheet(theme_manager.window_stylesheet())

    def showEvent(self, event) -> None:
        """Re-apply platform-specific window hacks after the native window is created."""
        super().showEvent(event)
        self.apply_platform_hacks()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, self._radius, self._radius)

            painter.setPen(QPen(theme_manager.border_color(), 1))
            painter.fillPath(path, theme_manager.bg_color())
            painter.drawPath(path)
        finally:
            painter.end()


class _FileStackWidget(QWidget):
    """Draws files as stacked cards with alternating random rotations."""

    _STACK_DEPTH = 4
    _ROTATION_MIN_DEG = 5
    _ROTATION_MAX_DEG = 10

    def __init__(self, provider: ThumbnailProvider, seed: str | int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._provider = provider
        self._seed = seed
        self._files: list[Path] = []
        self._empty_text = ""
        self._font_scale = 1.0
        self._rotations: list[float] = []
        self._anim_progress: float = 1.0
        self._anim_from: list[float] = []
        self._anim_to: list[float] = []
        self._animation: QVariantAnimation | None = None
        self._prev_display: list[Path] = []

    def set_files(self, files: list[Path]) -> None:
        new_display = self._display_files(files) if files else []

        if not self._prev_display:
            self._files = list(files)
            self._compute_rotations()
            self._anim_progress = 1.0
            self._prev_display = new_display
            self.update()
            return

        self._files = list(files)
        self._compute_rotations()

        if len(new_display) >= len(self._prev_display) and files:
            self._anim_from = []
            self._anim_to = []
            for i, path in enumerate(new_display):
                try:
                    old_idx = self._prev_display.index(path)
                    old_rot = 0.0 if old_idx == len(self._prev_display) - 1 else self._rotations[old_idx]
                    self._anim_from.append(old_rot)
                except ValueError:
                    self._anim_from.append(0.0)
                new_rot = 0.0 if i == len(new_display) - 1 else self._rotations[i]
                self._anim_to.append(new_rot)
            self._anim_progress = 0.0
            self._start_animation()
        else:
            self._anim_progress = 1.0
            self.update()

        self._prev_display = new_display

    def _start_animation(self) -> None:
        if self._animation is not None:
            try:
                self._animation.valueChanged.disconnect(self._on_animation_tick)
            except Exception:
                pass
            self._animation.stop()
            self._animation.deleteLater()
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(300)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animation_tick)
        self._animation.finished.connect(self._on_animation_done)
        self._animation.start()

    def _on_animation_tick(self, value: float) -> None:
        self._anim_progress = value
        self.update()

    def _on_animation_done(self) -> None:
        self._anim_progress = 1.0
        self.update()

    def _interpolated_rotation(self, index: int, display_len: int) -> float:
        if self._anim_progress >= 1.0 or not self._anim_from or index >= len(self._anim_from):
            return 0.0 if index == display_len - 1 else self._rotations[index]
        from_rot = self._anim_from[index]
        to_rot = self._anim_to[index]
        return from_rot + (to_rot - from_rot) * self._anim_progress

    def _compute_rotations(self) -> None:
        """Pre-compute deterministic rotation angles for the stack."""
        rng = random.Random(self._seed)
        self._rotations = []
        for i in range(self._STACK_DEPTH):
            direction = 1 if i % 2 == 0 else -1  # alternate CW/CCW
            angle = rng.uniform(self._ROTATION_MIN_DEG, self._ROTATION_MAX_DEG)
            self._rotations.append(direction * angle)

    @staticmethod
    def _display_files(files: list[Path]) -> list[Path]:
        blanks = files[:-1]
        blank_count = min(len(blanks), _FileStackWidget._STACK_DEPTH)
        blank_start = max(0, len(blanks) - blank_count)
        return blanks[blank_start:blank_start + blank_count] + [files[-1]]

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text

    def set_font_scale(self, scale: float) -> None:
        self._font_scale = scale

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

            if not self._files:
                self._draw_empty(painter)
                return

            w, h = self.width(), self.height()
            window_size = int(config_manager.get("window_size"))
            card_size = min(window_size * 0.55, 160)

            cx, cy = w / 2, h / 2
            card_x = cx - card_size / 2
            card_y = cy - card_size / 2

            display = self._display_files(self._files)

            for i, path in enumerate(display):
                painter.save()
                painter.translate(cx, cy)
                rotation = self._interpolated_rotation(i, len(display))
                if rotation != 0.0:
                    painter.rotate(rotation)
                painter.translate(-cx, -cy)
                self._provider.draw(painter, path, card_x, card_y, card_size)
                painter.restore()
        finally:
            painter.end()

    def _draw_empty(self, painter: QPainter) -> None:
        if not self._empty_text:
            return
        painter.setPen(QColor(160, 160, 160))
        f = QFont()
        f.setPointSize(round(10 * self._font_scale))
        painter.setFont(f)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)


class _TopMenu(QMenu, PlatformCompatMixin):
    """QMenu subclass that enforces macOS topmost behavior."""

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_platform_hacks()


class _PillButton(QAbstractButton):
    """Pill-shaped button with text on the left and a circular icon on the right."""

    _CIRCLE_DIAM = 20
    _RIGHT_MARGIN = 8
    _TEXT_LEFT = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hovered = False
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            w = self.width()
            h = self.height()
            pal = theme_manager._palette

            # Pill background + border
            bg = pal.pill_btn_hover_bg if self._hovered else pal.pill_btn_bg
            painter.setPen(QPen(QColor(*pal.pill_btn_border), 1))
            painter.setBrush(QColor(*bg))
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            painter.drawRoundedRect(rect, 15, 15)

            # Text (left-aligned, vertically centered)
            text_color = pal.pill_btn_hover_color if self._hovered else pal.pill_btn_color
            painter.setFont(self.font())
            painter.setPen(QColor(*text_color))
            text_r = QRectF(
                self._TEXT_LEFT, 0,
                w - self._TEXT_LEFT - self._RIGHT_MARGIN - self._CIRCLE_DIAM - 4,
                h,
            )
            painter.drawText(text_r, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())

            # Circle background on the right
            cx = w - self._RIGHT_MARGIN - self._CIRCLE_DIAM
            cy = (h - self._CIRCLE_DIAM) / 2
            circle_bg = pal.overlay_btn_hover_bg if self._hovered else pal.overlay_btn_bg
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*circle_bg))
            painter.drawEllipse(int(cx), int(cy), self._CIRCLE_DIAM, self._CIRCLE_DIAM)

            # Chevron icon centered in the circle
            icon = self.icon()
            if not icon.isNull():
                icon_size = 12
                pix = icon.pixmap(icon_size, icon_size)
                ix = cx + (self._CIRCLE_DIAM - icon_size) / 2
                iy = (h - icon_size) / 2
                painter.drawPixmap(int(ix), int(iy), pix)
        finally:
            painter.end()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text_w = metrics.horizontalAdvance(self.text())
        total = text_w + self._TEXT_LEFT + self._CIRCLE_DIAM + self._RIGHT_MARGIN + 12
        return QSize(total, 30)


class CourierBasketWindow(QWidget, PlatformCompatMixin):
    """A square, always-on-top, frameless window for staging file transfers."""

    _HEADER_RATIO = 0.15
    _FOOTER_RATIO = 0.15

    def __init__(self) -> None:
        super().__init__()
        self._trace_id = uuid.uuid4().hex[:6]
        set_trace_id(self._trace_id)
        self._basket = FileBasket()
        self._drag_start_pos: QPoint | None = None
        self._drag_out_started = False
        self._temp_zip: Path | None = None
        self._expanded = False
        self._grid_window: _FileGridWindow | None = None
        self._pill_btn: _PillButton
        self._thumb_provider = ThumbnailProvider(ffmpeg_path=config_manager.get("ffmpeg_path"))

        self._setup_window()
        self._create_ui()
        self._apply_opacity()
        self._apply_theme_stylesheet()
        self._update_display()
        language_changed.connect(self._retranslate_ui)
        theme_manager.theme_changed.connect(self._on_theme_changed)

    def _setup_window(self) -> None:
        size = int(config_manager.get("window_size"))
        size = max(200, min(600, size))

        self.setFixedSize(size, size)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAcceptDrops(True)
        logger.debug("Window created | size=%d", size)

    def _apply_opacity(self) -> None:
        opacity = float(config_manager.get("window_opacity"))
        self.setWindowOpacity(opacity)
        if self._grid_window:
            self._grid_window.setWindowOpacity(opacity)
        logger.debug("Opacity applied | opacity=%.2f", opacity)

    def _apply_theme_stylesheet(self) -> None:
        self._radius = int(config_manager.get("window_radius"))
        self.setStyleSheet(theme_manager.window_stylesheet())
        if self._grid_window:
            self._grid_window._radius = self._radius
            self._grid_window.setStyleSheet(theme_manager.window_stylesheet())
            self._grid_window.update()
        self._pill_btn.update()
        self.update()
        logger.debug("Theme stylesheet applied | radius=%d", self._radius)

    def _on_theme_changed(self, theme: str) -> None:
        logger.debug("Theme changed to %s, re-applying stylesheet", theme)
        self._apply_theme_stylesheet()
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        """Recreate all SVG icons with the current theme stroke colour."""
        self._close_icon = theme_manager.close_icon
        self._title_close_btn.setIcon(self._close_icon)
        self._menu_icon = theme_manager.menu_icon
        self._menu_btn.setIcon(self._menu_icon)
        self._chevron_down = theme_manager.chevron_down_icon
        self._chevron_up = theme_manager.chevron_up_icon
        self._pill_btn.setIcon(self._chevron_up if self._expanded else self._chevron_down)

    def _create_ui(self) -> None:
        base_size = self.height()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Square content area --
        self._square_container = QWidget()
        self._square_container.setObjectName("courier-square-container")
        self._square_container.setFixedHeight(base_size)
        square_layout = QVBoxLayout(self._square_container)
        square_layout.setContentsMargins(0, 0, 0, 0)
        square_layout.setSpacing(0)

        # -- Header (transparent — enables window drag) --
        self._header = QWidget()
        self._header.setObjectName("courier-header")
        self._header.setFixedHeight(int(base_size * self._HEADER_RATIO))
        self._header.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(44, 0, 44, 0)
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title_label = QLabel(tr("app.name"))
        self._title_label.setObjectName("courier-title")
        tf = QFont()
        tf.setPointSize(round(11 * self.font_scale))
        tf.setBold(True)
        self._title_label.setFont(tf)

        header_text_col = QVBoxLayout()
        header_text_col.setContentsMargins(0, 10, 0, 4)
        header_text_col.setSpacing(1)
        header_text_col.addWidget(self._title_label)

        hl.addLayout(header_text_col)

        # -- X close button --
        self._close_icon = theme_manager.close_icon

        self._title_close_btn = QPushButton(self)
        self._title_close_btn.setObjectName("courier-close-btn")
        self._title_close_btn.setIcon(self._close_icon)
        self._title_close_btn.setIconSize(QSize(16, 16))
        self._title_close_btn.setFlat(True)
        self._title_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title_close_btn.setFixedSize(28, 28)
        self._title_close_btn.clicked.connect(self.close)
        btn_size = 28
        margin = 8
        self._title_close_btn.setGeometry(self.width() - btn_size - margin, margin, btn_size, btn_size)
        self._title_close_btn.raise_()

        # -- Menu button (top-left) --
        self._menu_icon = theme_manager.menu_icon

        self._menu_btn = QPushButton(self)
        self._menu_btn.setObjectName("courier-menu-btn")
        self._menu_btn.setIcon(self._menu_icon)
        self._menu_btn.setIconSize(QSize(16, 16))
        self._menu_btn.setFlat(True)
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.setFixedSize(btn_size, btn_size)
        self._menu_btn.setGeometry(margin, margin, btn_size, btn_size)
        self._menu_btn.clicked.connect(self._show_menu)

        # -- File stack (cards) --
        self._file_stack = _FileStackWidget(self._thumb_provider, seed=self._trace_id)
        self._file_stack.setObjectName("courier-file-list")
        self._file_stack.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._file_stack.set_empty_text(tr("basket.empty_hint"))
        self._file_stack.set_font_scale(self.font_scale)

        # -- Footer with pill button --
        self._footer = QWidget()
        self._footer.setObjectName("courier-footer")
        self._footer.setFixedHeight(int(base_size * self._FOOTER_RATIO))

        self._chevron_down = theme_manager.chevron_down_icon
        self._chevron_up = theme_manager.chevron_up_icon

        self._pill_btn = _PillButton(self._footer)
        self._pill_btn.setIcon(self._chevron_down)
        pf = QFont()
        pf.setPointSize(round(10 * self.font_scale))
        self._pill_btn.setFont(pf)
        self._pill_btn.hide()
        self._pill_btn.clicked.connect(self._toggle_expand)

        fl = QHBoxLayout(self._footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(self._pill_btn)

        # -- Assemble square container --
        square_layout.addWidget(self._header)
        square_layout.addWidget(self._file_stack, 1)
        square_layout.addWidget(self._footer)

        # -- Assemble window --
        layout.addWidget(self._square_container)

        # Re-raise buttons so they stack above the container widgets
        self._title_close_btn.raise_()
        self._menu_btn.raise_()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(rect, self._radius, self._radius)

            painter.setPen(QPen(theme_manager.border_color(), 1))
            painter.fillPath(path, theme_manager.bg_color())
            painter.drawPath(path)
        finally:
            painter.end()

    # ------------------------------------------------------------------
    # Drag-in (accept files from external)
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_platform_hacks()

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        set_trace_id(self._trace_id)
        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))

        if paths:
            added = self._basket.add(paths)
            paths_str = ", ".join(str(p) for p in paths)
            logger.info(
                "Files dropped | added=%d paths=[%s] total=%d",
                added,
                paths_str,
                self._basket.count,
            )
            self._update_display()
        else:
            logger.warning("Drop event with no valid file URLs")

        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Drag-out (drag files to external target) & window move
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self._drag_out_started = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_start_pos is None or self._drag_out_started:
            return

        pos = event.position().toPoint()
        dist = (pos - self._drag_start_pos).manhattanLength()
        if dist < 10:
            return

        y = self._drag_start_pos.y()
        header_h = int(self.height() * self._HEADER_RATIO)

        if y < header_h or self._basket.is_empty:
            # Drag from header or empty basket → move window
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
            if self._expanded:  # Auto-close expanded grid on window move
                self._toggle_expand()
        else:
            # Drag from file area with files → start file drag-out
            self._drag_out_started = True
            self._start_drag_out()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_start_pos = None
        self._drag_out_started = False

    def _start_drag_out(self) -> None:
        """Initiate QDrag with all staged file URLs."""
        set_trace_id(self._trace_id)
        self._drag_start_pos = None  # prevent re-entry

        stale_files = self._basket.validate()
        for p in stale_files:
            self._basket.remove(p)

        if self._basket.is_empty:
            logger.warning("All files stale, drag-out cancelled")
            self._update_display()
            return

        valid_files = self._basket.files
        compress = config_manager.get("compress_on_drag")

        if compress:
            zip_path = create_temp_zip(valid_files)
            if zip_path is None:
                logger.warning("Compression failed, drag-out cancelled")
                return
            self._temp_zip = zip_path
            urls = [QUrl.fromLocalFile(str(zip_path))]
            action = Qt.DropAction.CopyAction
        else:
            is_shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            is_move = (config_manager.get("default_transfer_mode") == "move") != is_shift
            action = Qt.DropAction.MoveAction if is_move else Qt.DropAction.CopyAction
            urls = [QUrl.fromLocalFile(str(p)) for p in valid_files]

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls(urls)
        drag.setMimeData(mime)
        result = drag.exec(action)

        if compress:
            cleanup_temp_zip(self._temp_zip)

        if stale_files:
            names = "\n".join(p.name for p in stale_files[:5])
            QMessageBox.warning(self, tr("app.name"), tr("basket.files_missing", names=names))

        self._apply_after_drop(result, None if compress else valid_files)

    def _apply_after_drop(self, result: Qt.DropAction, tracked_files: list[Path] | None = None) -> None:
        """Handle after-drop action and optional move bookkeeping."""
        action = config_manager.get("after_drop_action")
        if action == "close":
            self.close()
        elif action == "clear":
            self._basket.clear()
            self._update_display()
        else:  # keep
            if tracked_files and result == Qt.DropAction.MoveAction:
                for p in tracked_files:
                    if not p.exists():
                        self._basket.remove(p)
            self._update_display()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _retranslate_ui(self) -> None:
        self._title_label.setText(tr("app.name"))
        self._file_stack.set_empty_text(tr("basket.empty_hint"))
        self._update_display()

    def _update_display(self) -> None:
        self._file_stack.set_files(self._basket.files)
        cnt = self._basket.count

        if self._expanded:
            # Auto-close the grid window if the basket state updates (prevent stale grids)
            self._expanded = False
            self._pill_btn.setIcon(self._chevron_down)
            if self._grid_window:
                self._grid_window.close()
                self._grid_window = None

        if cnt == 0:
            self._pill_btn.hide()
        else:
            self._pill_btn.setText(tr("basket.file_count", count=cnt))
            self._pill_btn.show()

        self.setStyleSheet(theme_manager.window_stylesheet())

    def _show_menu(self) -> None:
        menu = _TopMenu(self)
        mfs = round(9 * self.font_scale)
        menu.setStyleSheet(theme_manager.menu_stylesheet(mfs))

        clear_act = QAction(tr("basket.clear"), self)
        clear_act.triggered.connect(self._on_clear)
        menu.addAction(clear_act)

        compress_act = QAction(tr("basket.compress"), self)
        compress_act.setCheckable(True)
        compress_act.setChecked(config_manager.get("compress_on_drag"))
        compress_act.triggered.connect(
            lambda checked: config_manager.set("compress_on_drag", checked)
        )
        menu.addAction(compress_act)

        menu.addSeparator()

        settings_act = QAction(tr("tray.settings"), self)
        settings_act.triggered.connect(self._open_settings)
        menu.addAction(settings_act)

        menu.exec(self._menu_btn.mapToGlobal(
            self._menu_btn.rect().bottomLeft() + QPoint(4, 0)
        ))

    def _open_settings(self) -> None:
        from .settings_dialog import CourierSettingsDialog
        dialog = CourierSettingsDialog(self)
        dialog.exec()

    def _on_clear(self) -> None:
        count = self._basket.count
        self._basket.clear()
        logger.info("Basket cleared | removed=%d", count)
        self._update_display()

    # ------------------------------------------------------------------
    # Pill button
    # ------------------------------------------------------------------

    def _toggle_expand(self) -> None:
        if self._basket.is_empty:
            return

        self._expanded = not self._expanded
        self._pill_btn.setIcon(self._chevron_up if self._expanded else self._chevron_down)

        if self._expanded:
            self._grid_window = self._build_grid_window()
            self._grid_window.setWindowOpacity(self.windowOpacity())

            # Anchor below the main window
            geo = self.geometry()
            gw_w = self._grid_window.width()
            x = geo.center().x() - gw_w // 2
            y = geo.bottom() + 10
            self._grid_window.move(x, y)

            self._grid_window.show()
        else:
            if self._grid_window:
                self._grid_window.close()
                self._grid_window = None

    def _build_grid_window(self) -> _FileGridWindow:
        """Create a new grid window for the current basket contents."""
        window_size = int(config_manager.get("window_size"))
        card_size = int(min(window_size * 0.55, 160))
        return _FileGridWindow(
            files=self._basket.files,
            font_scale=self.font_scale,
            card_size=card_size,
            radius=self._radius,
            provider=self._thumb_provider,
            on_file_remove=self._on_grid_file_remove,
        )

    def _on_grid_file_remove(self, path: Path) -> None:
        """Remove a file from the basket and refresh the grid view."""
        self._basket.remove(path)
        cnt = self._basket.count

        self._file_stack.set_files(self._basket.files)

        if cnt == 0:
            self._expanded = False
            self._pill_btn.setIcon(self._chevron_down)
            self._pill_btn.hide()
            if self._grid_window:
                self._grid_window.close()
                self._grid_window = None
        else:
            self._pill_btn.setText(tr("basket.file_count", count=cnt))
            self._pill_btn.show()
            if self._grid_window:
                self._grid_window.close()
            self._grid_window = self._build_grid_window()

            geo = self.geometry()
            gw_w = self._grid_window.width()
            x = geo.center().x() - gw_w // 2
            y = geo.bottom() + 10
            self._grid_window.move(x, y)
            self._grid_window.show()

        self.setStyleSheet(theme_manager.window_stylesheet())

    def closeEvent(self, event) -> None:
        if self._grid_window:
            self._grid_window.close()
        self._thumb_provider.clear_cache()
        cleanup_temp_zip(self._temp_zip)
        logger.debug("Window closed")
        event.accept()
