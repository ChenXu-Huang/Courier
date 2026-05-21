"""Square floating window — drag-drop file staging surface."""

import math
import uuid
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QMimeData, QRectF, QUrl, QPoint
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget, QGridLayout, QScrollArea

from .._meta import IS_MACOS, IS_WINDOWS, RESOURCES_DIR
from ..config import config_manager
from ..logger import get_logger, set_trace_id
from ..utils import FileBasket, cleanup_temp_zip, create_temp_zip, tr, language_changed
from .theme import theme_manager

logger = get_logger(__name__)


# ------------------------------------------------------------------
# Platform-specific window hacks
# ------------------------------------------------------------------

def _enforce_macos_topmost(window: QWidget) -> bool:
    """Float the window above all others via the Objective-C runtime."""
    import ctypes
    from ctypes import c_bool, c_char_p, c_long, c_void_p, c_ulong

    try:
        objc = ctypes.CDLL("/usr/lib/libobjc.dylib")
        objc.sel_registerName.restype = c_void_p
        objc.sel_registerName.argtypes = [c_char_p]
        objc.objc_getClass.restype = c_void_p
        objc.objc_getClass.argtypes = [c_char_p]
        objc.class_getInstanceMethod.restype = c_void_p
        objc.class_getInstanceMethod.argtypes = [c_void_p, c_void_p]
        objc.method_getImplementation.restype = c_void_p
        objc.method_getImplementation.argtypes = [c_void_p]

        view = c_void_p(int(window.winId()))
        ns_view_cls = objc.objc_getClass(b"NSView")
        ns_window_cls = objc.objc_getClass(b"NSWindow")

        sel_window = objc.sel_registerName(b"window")
        imp_window = objc.method_getImplementation(objc.class_getInstanceMethod(ns_view_cls, sel_window))
        get_window = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)(imp_window)
        ns_window = get_window(view, sel_window)
        if not ns_window:
            logger.warning("Failed to obtain NSWindow via ctypes")
            return False

        sel_level = objc.sel_registerName(b"setLevel:")
        imp_level = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_level))
        set_level = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_long)(imp_level)
        set_level(ns_window, sel_level, 3)

        sel_hides = objc.sel_registerName(b"setHidesOnDeactivate:")
        imp_hides = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_hides))
        set_hides = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(imp_hides)
        set_hides(ns_window, sel_hides, False)

        sel_behavior = objc.sel_registerName(b"setCollectionBehavior:")
        imp_behavior = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_behavior))
        set_behavior = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(imp_behavior)
        set_behavior(ns_window, sel_behavior, 1 | 256 | 1024)

        logger.debug("macOS topmost and multi-space behavior enforced via IMP (safe path)")
        return True
    except Exception as exc:
        logger.warning("macOS topmost ctypes failed: %s", exc)
        return False


def _suppress_dwm_rounding(window: QWidget) -> bool:
    """Disable Windows 11 DWM automatic corner rounding for this window."""
    import ctypes

    _DWMWA_WINDOW_CORNER_PREFERENCE = 33
    _DWMWCP_DONOTROUND = 1

    try:
        hwnd = ctypes.c_void_p(int(window.winId()))
        preference = ctypes.c_int(_DWMWCP_DONOTROUND)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            hwnd,
            _DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
        if result != 0:
            logger.debug(
                "DWM corner suppression returned HRESULT=0x%08X",
                result & 0xFFFFFFFF,
            )
            return False
        logger.debug("DWM automatic corner rounding suppressed")
        return True
    except Exception as exc:
        logger.warning("DwmSetWindowAttribute failed: %s", exc)
        return False


class _ThumbnailWidget(QWidget):
    """Renders the actual image thumbnail or SVG placeholder."""

    _IMAGE_EXTS = frozenset({
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
        ".svg", ".ico", ".tiff", ".tif", ".avif",
    })

    def __init__(self, path: Path, font_scale: float, blank_renderer: QSvgRenderer, card_size: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._font_scale = font_scale
        self._blank_renderer = blank_renderer
        self.setFixedSize(card_size, card_size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = self.width()
        icon_size = int(size * 0.8)
        margin = (size - icon_size) / 2

        if self._path.suffix.lower() in self._IMAGE_EXTS:
            # Image thumbnail (no background)
            pix = QPixmap(str(self._path))
            if not pix.isNull():
                scaled = pix.scaled(
                    icon_size, icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                px = (size - scaled.width()) / 2
                py = (size - scaled.height()) / 2
                painter.drawPixmap(int(px), int(py), scaled)
        else:
            # Blank-file.svg with extension badge
            pix = QPixmap(icon_size, icon_size)
            pix.fill(Qt.GlobalColor.transparent)
            ip = QPainter(pix)
            self._blank_renderer.render(ip, QRectF(0, 0, icon_size, icon_size))
            ip.end()
            painter.drawPixmap(int(margin), int(margin), pix)

            ext = self._path.suffix[1:].upper() or "?"
            f = QFont()
            f.setPointSize(round(icon_size * 0.14))
            painter.setFont(f)
            painter.setPen(QColor(100, 110, 140))
            text_rect = QRectF(
                margin + 4,
                margin + icon_size * 0.62,
                icon_size - 8,
                icon_size * 0.35,
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, ext)


class _FileGridItem(QWidget):
    """A single file thumbnail card with its filename below."""

    def __init__(self, path: Path, font_scale: float, blank_renderer: QSvgRenderer, card_size: int, parent=None):
        super().__init__(parent)
        self.setFixedWidth(card_size)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)  # gap between thumbnail and label

        # 1. Thumbnail
        self.thumb = _ThumbnailWidget(path, font_scale, blank_renderer, card_size)
        layout.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignCenter)

        # 2. Filename label
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


class _FileGridWindow(QWidget):
    """An expanded floating window displaying files in a responsive grid."""

    def __init__(self, files: list[Path], font_scale: float, blank_renderer: QSvgRenderer, card_size: int, radius: int, parent=None):
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
        content.setStyleSheet("background: transparent;")
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
            item = _FileGridItem(path, font_scale, blank_renderer, card_size)
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
        win_h = vis_rows * item_h + (vis_rows - 1) * 10 + 30 # 30 = top + bottom margins
        self.setFixedSize(win_w, win_h)
        self.setStyleSheet(theme_manager.window_stylesheet())

    def showEvent(self, event) -> None:
        """Re-apply platform-specific window hacks after the native window is created."""
        super().showEvent(event)
        if IS_MACOS and not getattr(self, "_macos_level_set", False):
            if _enforce_macos_topmost(self):
                self._macos_level_set = True
        elif IS_WINDOWS and not getattr(self, "_dwm_rounding_suppressed", False):
            if _suppress_dwm_rounding(self):
                self._dwm_rounding_suppressed = True

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
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


class _FileStackWidget(QWidget):
    """Draws files as stacked cards — blank placeholders for older files,
    real thumbnail for the most recent file."""

    _MAX_BLANK = 4
    _STACK_OFFSET_X = 10
    _STACK_OFFSET_Y = 6
    _IMAGE_EXTS = frozenset({
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
        ".svg", ".ico", ".tiff", ".tif", ".avif",
    })  # fmt: skip

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files: list[Path] = []
        self._empty_text = ""
        self._font_scale = 1.0
        self._blank_renderer = QSvgRenderer(str(RESOURCES_DIR / "icons" / "blank-file.svg"))

    def set_files(self, files: list[Path]) -> None:
        self._files = list(files)
        self.update()

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text

    def set_font_scale(self, scale: float) -> None:
        self._font_scale = scale

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._files:
            self._draw_empty(painter)
            return

        w, h = self.width(), self.height()
        window_size = int(config_manager.get("window_size"))
        card_size = min(window_size * 0.5, 160)
        radius = max(9, card_size * 0.1)

        blanks = self._files[:-1]
        blank_count = min(len(blanks), self._MAX_BLANK)
        blank_start = max(0, len(blanks) - blank_count)

        cx, cy = w / 2, h / 2
        rx = cx - card_size / 2 + max(blank_count - 1, 0) * self._STACK_OFFSET_X / 2
        ry = cy - card_size / 2 + max(blank_count - 1, 0) * self._STACK_OFFSET_Y / 2

        # Draw blank cards from deepest to nearest
        for i in range(blank_count):
            depth = blank_count - i
            bx = rx - depth * self._STACK_OFFSET_X
            by = ry - depth * self._STACK_OFFSET_Y
            self._draw_blank(painter, bx, by, card_size, radius, blanks[blank_start + i])

        # Draw latest file card on top
        self._draw_file_card(painter, rx, ry, card_size, radius, self._files[-1])

    def _draw_empty(self, painter: QPainter) -> None:
        if not self._empty_text:
            return
        painter.setPen(QColor(160, 160, 160))
        f = QFont()
        f.setPointSize(round(10 * self._font_scale))
        painter.setFont(f)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._empty_text)

    def _draw_blank(self, painter: QPainter, x: float, y: float, size: float, radius: float, path: Path) -> None:
        icon_size = int(size * 0.8)
        pix = QPixmap(icon_size, icon_size)
        pix.fill(Qt.GlobalColor.transparent)
        ip = QPainter(pix)
        self._blank_renderer.render(ip, QRectF(0, 0, icon_size, icon_size))
        ip.end()
        px = x + (size - icon_size) / 2
        py = y + (size - icon_size) / 2
        painter.drawPixmap(int(px), int(py), pix)

    def _draw_file_card(self, painter: QPainter, x: float, y: float, size: float, radius: float, path: Path) -> None:
        icon_size = int(size * 0.8)
        margin = (size - icon_size) / 2

        if path.suffix.lower() in self._IMAGE_EXTS:
            # Image thumbnail (no background)
            pix = QPixmap(str(path))
            if not pix.isNull():
                scaled = pix.scaled(
                    icon_size, icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                px = x + (size - scaled.width()) / 2
                py = y + (size - scaled.height()) / 2
                painter.drawPixmap(int(px), int(py), scaled)
        else:
            # Blank-file.svg with extension badge at bottom-right
            pix = QPixmap(icon_size, icon_size)
            pix.fill(Qt.GlobalColor.transparent)
            ip = QPainter(pix)
            self._blank_renderer.render(ip, QRectF(0, 0, icon_size, icon_size))
            ip.end()
            painter.drawPixmap(int(x + margin), int(y + margin), pix)

            ext = path.suffix[1:].upper() or "?"
            f = QFont()
            f.setPointSize(round(icon_size * 0.14))
            painter.setFont(f)
            painter.setPen(QColor(100, 110, 140))
            text_rect = QRectF(
                x + margin + 4,
                y + margin + icon_size * 0.62,
                icon_size - 8,
                icon_size * 0.35,
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, ext)


class CourierBasketWindow(QWidget):
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
        self._pill_btn: QPushButton

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

    @property
    def _font_scale(self) -> float:
        """DPI-aware font scale factor, platform-adjusted."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0

        dpi = screen.logicalDotsPerInch()
        if IS_MACOS:  # MacOS: baseline 72 DPI
            return max(1.0, min(3.0, (dpi / 72.0) * 1.2))
        return max(0.8, min(3.0, dpi / 96.0))  # Windows / Linux: baseline 96 DPI

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
        tf.setPointSize(round(11 * self._font_scale))
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
        self._file_stack = _FileStackWidget()
        self._file_stack.setObjectName("courier-file-list")
        self._file_stack.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._file_stack.set_empty_text(tr("basket.empty_hint"))
        self._file_stack.set_font_scale(self._font_scale)

        # -- Footer with pill button --
        self._footer = QWidget()
        self._footer.setObjectName("courier-footer")
        self._footer.setFixedHeight(int(base_size * self._FOOTER_RATIO))

        self._chevron_down = theme_manager.chevron_down_icon
        self._chevron_up = theme_manager.chevron_up_icon

        self._pill_btn = QPushButton(self._footer)
        self._pill_btn.setObjectName("courier-pill-btn")
        self._pill_btn.setIcon(self._chevron_down)
        self._pill_btn.setIconSize(QSize(14, 14))
        self._pill_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill_btn.setFixedHeight(30)
        pf = QFont()
        pf.setPointSize(round(10 * self._font_scale))
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

    # ------------------------------------------------------------------
    # Drag-in (accept files from external)
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if IS_MACOS and not getattr(self, "_macos_level_set", False):
            if _enforce_macos_topmost(self):
                self._macos_level_set = True
        elif IS_WINDOWS and not getattr(self, "_dwm_rounding_suppressed", False):
            if _suppress_dwm_rounding(self):
                self._dwm_rounding_suppressed = True

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
                "Files dropped | added=%d paths=[%s] total=%d size=%s",
                added,
                paths_str,
                self._basket.count,
                self._format_size(self._basket.total_size),
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

    @staticmethod
    def _format_size(n: int) -> str:
        if n <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        idx = min(int(math.log(n, 1024)), len(units) - 1)
        return f"{n / (1024**idx):.1f} {units[idx]}"

    def _show_menu(self) -> None:
        menu = QMenu(self)
        mfs = round(9 * self._font_scale)
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
            window_size = int(config_manager.get("window_size"))
            card_size = int(min(window_size * 0.5, 160))

            self._grid_window = _FileGridWindow(
                files=self._basket.files,
                font_scale=self._font_scale,
                blank_renderer=self._file_stack._blank_renderer,
                card_size=card_size,
                radius=self._radius,
            )
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

    def closeEvent(self, event) -> None:
        if self._grid_window:
            self._grid_window.close()
        cleanup_temp_zip(self._temp_zip)
        logger.debug("Window closed")
        event.accept()
