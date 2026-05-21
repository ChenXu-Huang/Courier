"""Square floating window — drag-drop file staging surface."""

import math
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QMimeData, QRectF, QUrl, QPoint
from PySide6.QtGui import QAction, QDrag, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .._meta import IS_MACOS, IS_WINDOWS
from ..config import config_manager
from ..logger import get_logger, set_trace_id
from ..utils import FileBasket
from ..utils.i18n import tr, language_changed
from .theme import theme_manager

logger = get_logger(__name__)

_EXPAND_PANEL_HEIGHT = 160
_HEADER_RATIO = 0.15
_FOOTER_RATIO = 0.15
_MAX_VISIBLE_FILES = 8


class _ExpandFooter:
    """Manages the collapsible footer pill button and expand panel."""

    def __init__(self, base_size: int, font_scale: float, parent: QWidget | None = None) -> None:
        self._font_scale = font_scale
        self._expanded = False
        self._count = 0

        # -- Footer widget --
        self._footer = QWidget(parent)
        self._footer.setObjectName("courier-footer")
        self._footer.setFixedHeight(int(base_size * _FOOTER_RATIO))

        # -- Icons --
        self._chevron_down = theme_manager.chevron_down_icon
        self._chevron_up = theme_manager.chevron_up_icon

        # -- Pill button --
        self._pill_btn = QPushButton(self._footer)
        self._pill_btn.setObjectName("courier-pill-btn")
        self._pill_btn.setIcon(self._chevron_down)
        self._pill_btn.setIconSize(QSize(14, 14))
        self._pill_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self._pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pill_btn.setFixedHeight(30)
        pf = QFont()
        pf.setPointSize(round(10 * font_scale))
        self._pill_btn.setFont(pf)
        self._pill_btn.hide()

        fl = QHBoxLayout(self._footer)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fl.addWidget(self._pill_btn)

        # -- Expand panel --
        self._panel = QWidget(parent)
        self._panel.setObjectName("courier-expand-panel")
        self._panel.setFixedHeight(_EXPAND_PANEL_HEIGHT)
        self._panel.hide()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def footer(self) -> QWidget:
        return self._footer

    @property
    def panel(self) -> QWidget:
        return self._panel

    @property
    def pill(self) -> QPushButton:
        return self._pill_btn

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    @property
    def expand_height(self) -> int:
        return _EXPAND_PANEL_HEIGHT

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def set_count(self, count: int) -> None:
        """Update visible state according to staged file count."""
        self._count = count
        if count == 0:
            if self._expanded:
                self._expanded = False
                self._panel.hide()
                self._pill_btn.setIcon(self._chevron_down)
            self._pill_btn.hide()
        else:
            self._pill_btn.setText(tr("basket.file_count", count=count))
            self._pill_btn.show()

    def toggle(self) -> None:
        """Flip expanded / collapsed."""
        self._expanded = not self._expanded
        self._pill_btn.setIcon(self._chevron_up if self._expanded else self._chevron_down)
        self._panel.setVisible(self._expanded)

    def refresh_icons(self) -> None:
        """Recreate icons with current theme colour."""
        self._chevron_down = theme_manager.chevron_down_icon
        self._chevron_up = theme_manager.chevron_up_icon
        self._pill_btn.setIcon(self._chevron_up if self._expanded else self._chevron_down)


class CourierBasketWindow(QWidget):
    """A square, always-on-top, frameless window for staging file transfers."""

    def __init__(self) -> None:
        super().__init__()
        self._trace_id = uuid.uuid4().hex[:6]
        set_trace_id(self._trace_id)
        self._basket = FileBasket()
        self._drag_start_pos: QPoint | None = None
        self._drag_out_started = False
        self._file_labels: list[QLabel] = []
        self._temp_zip: Path | None = None

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
        logger.debug("Opacity applied | opacity=%.2f", opacity)

    def _apply_theme_stylesheet(self) -> None:
        self._radius = int(config_manager.get("window_radius"))
        self.setStyleSheet(theme_manager.window_stylesheet())
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
        self._expander.refresh_icons()

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

    def _enforce_macos_topmost(self) -> bool:
        """Float the window above all others via the Objective-C runtime.

        Uses ``method_getImplementation`` to get plain C function pointers
        (IMP) for each ObjC message, then calls them through
        ``ctypes.CFUNCTYPE``.  This avoids ``objc_msgSend``, which is an
        assembly trampoline whose ABI is incompatible with libffi on arm64.

        Returns ``True`` on success, ``False`` if the NSWindow could not
        be configured (so callers can decide whether to cache the result).
        """
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

            view = c_void_p(int(self.winId()))
            ns_view_cls = objc.objc_getClass(b"NSView")
            ns_window_cls = objc.objc_getClass(b"NSWindow")

            # --- Get NSWindow from NSView using IMP (regular C func) ---
            sel_window = objc.sel_registerName(b"window")
            imp_window = objc.method_getImplementation(objc.class_getInstanceMethod(ns_view_cls, sel_window))
            get_window = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)(imp_window)
            ns_window = get_window(view, sel_window)
            if not ns_window:
                logger.warning("Failed to obtain NSWindow via ctypes")
                return False

            # --- setLevel: via IMP ---
            sel_level = objc.sel_registerName(b"setLevel:")
            imp_level = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_level))
            set_level = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_long)(imp_level)
            set_level(ns_window, sel_level, 3)

            # --- setHidesOnDeactivate: via IMP ---
            sel_hides = objc.sel_registerName(b"setHidesOnDeactivate:")
            imp_hides = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_hides))
            set_hides = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(imp_hides)
            set_hides(ns_window, sel_hides, False)

            # --- setCollectionBehavior: via IMP ---
            sel_behavior = objc.sel_registerName(b"setCollectionBehavior:")
            imp_behavior = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_behavior))
            set_behavior = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(imp_behavior)
            set_behavior(ns_window, sel_behavior, 1 | 256 | 1024)

            logger.debug("macOS topmost and multi-space behavior enforced via IMP (safe path)")
            return True
        except Exception as exc:
            logger.warning("macOS topmost ctypes failed: %s", exc)
            return False

    def _suppress_dwm_rounding(self) -> bool:
        """Disable Windows 11 DWM automatic corner rounding for this window.

        When ``WA_TranslucentBackground`` is active, the DWM clips the window
        with its own rounded corners (≈ 8–10 px radius on Windows 11).  That
        clip outline appears as a thin arc *outside* the painted round-rect,
        producing a ghost border at a smaller radius than ``window_radius``.
        Setting ``DWMWA_WINDOW_CORNER_PREFERENCE`` to ``DWMWCP_DONOTROUND``
        (1) disables the DWM rounding entirely, so that only the radius
        painted in :meth:`paintEvent` is visible.

        Returns ``True`` on success, ``False`` if the attribute could not be
        set (e.g. Windows 10 where the attribute is a no-op, or when running
        on a non-Windows platform where ``windll`` is unavailable).
        """
        import ctypes

        # Defined in <dwmapi.h> — present since Windows 11 Build 22000.
        _DWMWA_WINDOW_CORNER_PREFERENCE = 33
        _DWMWCP_DONOTROUND = 1

        try:
            hwnd = ctypes.c_void_p(int(self.winId()))
            preference = ctypes.c_int(_DWMWCP_DONOTROUND)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
            if result != 0:  # S_OK == 0
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
        self._header.setFixedHeight(int(base_size * _HEADER_RATIO))
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

        # -- X close button (direct child of window, overlaid at top-right) --
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

        # -- File list --
        self._file_list = QWidget()
        self._file_list.setObjectName("courier-file-list")
        self._file_list.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fl_layout = QVBoxLayout(self._file_list)
        self._fl_layout.setContentsMargins(20, 4, 20, 4)
        self._fl_layout.setSpacing(3)
        self._fl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_label = QLabel(tr("basket.empty_hint"))
        self._empty_label.setObjectName("courier-empty-label")
        ef = QFont()
        ef.setPointSize(round(10 * self._font_scale))
        self._empty_label.setFont(ef)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fl_layout.addWidget(self._empty_label)

        # -- Footer & expand panel (managed by _ExpandFooter) --
        self._expander = _ExpandFooter(base_size, self._font_scale, self)
        self._expander.pill.clicked.connect(self._toggle_expand)

        # -- Assemble square container --
        square_layout.addWidget(self._header)
        square_layout.addWidget(self._file_list, 1)
        square_layout.addWidget(self._expander.footer)

        # -- Assemble window --
        layout.addWidget(self._square_container)
        layout.addWidget(self._expander.panel)

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

    # Show event — platform-specific one-time fixups
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if IS_MACOS and not getattr(self, "_macos_level_set", False):
            if self._enforce_macos_topmost():
                self._macos_level_set = True
        elif IS_WINDOWS and not getattr(self, "_dwm_rounding_suppressed", False):
            if self._suppress_dwm_rounding():
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
        header_h = int(self.height() * _HEADER_RATIO)

        if y < header_h or self._basket.is_empty:
            # Drag from header or empty basket → move window
            self.move(event.globalPosition().toPoint() - self._drag_start_pos)
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
            zip_path = self._create_temp_zip(valid_files)
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
            self._cleanup_temp_zip()

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
        self._empty_label.setText(tr("basket.empty_hint"))
        self._update_display()

    def _update_display(self) -> None:
        for lb in self._file_labels:
            lb.deleteLater()
        self._file_labels.clear()

        if self._basket.is_empty:
            self._empty_label.show()
            was_expanded = self._expander.is_expanded
            self._expander.set_count(0)
            if was_expanded:
                base_size = self._square_container.height()
                self.setFixedSize(base_size, base_size)
            return

        self._empty_label.hide()

        cnt = self._basket.count
        remaining = self._basket.count - _MAX_VISIBLE_FILES

        for p, label in self._basket.display_labels(_MAX_VISIBLE_FILES):
            lb = QLabel(label)
            lb.setObjectName("courier-file-label")
            lb.setToolTip(str(p))
            fl = QFont()
            fl.setPointSize(round(9 * self._font_scale))
            lb.setFont(fl)
            self._fl_layout.addWidget(lb)
            self._file_labels.append(lb)

        if remaining > 0:
            more = QLabel(tr("basket.more", count=remaining))
            more.setObjectName("courier-more-label")
            ml = QFont()
            ml.setPointSize(round(9 * self._font_scale))
            more.setFont(ml)
            self._fl_layout.addWidget(more)
            self._file_labels.append(more)

        self._expander.set_count(cnt)
        self.setStyleSheet(theme_manager.window_stylesheet())

    @staticmethod
    def _format_size(n: int) -> str:
        if n <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        idx = min(int(math.log(n, 1024)), len(units) - 1)
        return f"{n / (1024**idx):.1f} {units[idx]}"

    # ------------------------------------------------------------------
    # Compression helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_temp_zip(files: list[Path]) -> Path | None:
        """Bundle *files* into a temporary zip and return its path."""
        try:
            fd, path = tempfile.mkstemp(suffix=".zip", prefix="courier_")
            os.close(fd)

            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    zf.write(f, f.name)
            return Path(path)
        except Exception as exc:
            logger.exception("Failed to create temp zip: %s", exc)
            return None

    def _cleanup_temp_zip(self) -> None:
        if self._temp_zip is not None:
            try:
                self._temp_zip.unlink(missing_ok=True)
            except Exception:
                logger.warning("Failed to clean up temp zip: %s", self._temp_zip)
            self._temp_zip = None

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
    # Pill button & expand panel
    # ------------------------------------------------------------------

    def _toggle_expand(self) -> None:
        base_size = self._square_container.height()
        self._expander.toggle()
        if self._expander.is_expanded:
            self.setFixedSize(base_size, base_size + self._expander.expand_height)
        else:
            self.setFixedSize(base_size, base_size)

    def closeEvent(self, event) -> None:
        self._cleanup_temp_zip()
        logger.debug("Window closed")
        event.accept()
