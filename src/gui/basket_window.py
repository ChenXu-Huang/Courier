"""Square floating window — drag-drop file staging surface."""

import math
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QMimeData, QRectF, QUrl, QPoint
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QIcon, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .._meta import IS_MACOS, RESOURCES_DIR
from ..config import config_manager
from ..logger import get_logger, set_trace_id
from ..utils import FileBasket
from ..utils.i18n import tr, language_changed

logger = get_logger(__name__)

_CLOSE_ICON_PATH = RESOURCES_DIR / "icons" / "close.svg"
_MENU_ICON_PATH = RESOURCES_DIR / "icons" / "menu.svg"

_HEADER_RATIO = 0.15
_FOOTER_RATIO = 0.15
_MAX_VISIBLE_FILES = 8


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
        self._apply_theme()
        self._update_display()
        language_changed.connect(self._retranslate_ui)

    def _setup_window(self) -> None:
        size = int(config_manager.get("window_size"))
        size = max(200, min(600, size))

        self.setFixedSize(size, size)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAcceptDrops(True)
        logger.debug("Window created | size=%d", size)

    def _apply_theme(self) -> None:
        self._bg_color = QColor(30, 30, 40, 235)
        self._radius = int(config_manager.get("window_radius"))
        self._border_color = QColor(255, 255, 255, 25)

        opacity = float(config_manager.get("window_opacity"))
        self.setWindowOpacity(opacity)
        logger.debug("Theme applied | radius=%d opacity=%.2f", self._radius, opacity)

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
        from ctypes import c_bool, c_char_p, c_long, c_void_p

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

            logger.debug("macOS topmost enforced via IMP (safe path)")
            return True
        except Exception as exc:
            logger.warning("macOS topmost ctypes failed: %s", exc)
            return False

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Header (transparent — enables window drag) --
        self._header = QWidget()
        self._header.setFixedHeight(int(self.height() * _HEADER_RATIO))
        self._header.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(44, 0, 44, 0)
        hl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title_label = QLabel(tr("app.name"))
        tf = QFont()
        tf.setPointSize(round(11 * self._font_scale))
        tf.setBold(True)
        self._title_label.setFont(tf)
        self._title_label.setStyleSheet("color: rgba(255,255,255,200);")

        self._info_label = QLabel()
        inf = QFont()
        inf.setPointSize(round(8 * self._font_scale))
        self._info_label.setFont(inf)
        self._info_label.setStyleSheet("color: rgba(255,255,255,110);")

        header_text_col = QVBoxLayout()
        header_text_col.setContentsMargins(0, 10, 0, 4)
        header_text_col.setSpacing(1)
        header_text_col.addWidget(self._title_label)
        header_text_col.addWidget(self._info_label)

        hl.addLayout(header_text_col)

        # -- X close button (direct child of window, overlaid at top-right) --
        close_icon = QIcon(str(_CLOSE_ICON_PATH))
        close_icon.setIsMask(True)

        self._title_close_btn = QPushButton(self)
        self._title_close_btn.setIcon(close_icon)
        self._title_close_btn.setIconSize(QSize(16, 16))
        self._title_close_btn.setFlat(True)
        self._title_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._title_close_btn.setFixedSize(28, 28)
        self._title_close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,30);
                border: none;
                border-radius: 14px;
                color: rgba(255,255,255,200);
            }
            QPushButton:hover {
                background: rgba(255,255,255,60);
                color: rgba(255,255,255,255);
            }
        """)
        self._title_close_btn.clicked.connect(self.close)
        btn_size = 28
        margin = 8
        self._title_close_btn.setGeometry(self.width() - btn_size - margin, margin, btn_size, btn_size)
        self._title_close_btn.raise_()

        # -- Menu button (top-left) --
        menu_icon = QIcon(str(_MENU_ICON_PATH))
        menu_icon.setIsMask(True)

        btn_style_menu = """
            QPushButton {
                background: rgba(255,255,255,30);
                border: none;
                border-radius: 14px;
                color: rgba(255,255,255,200);
            }
            QPushButton:hover {
                background: rgba(255,255,255,60);
                color: rgba(255,255,255,255);
            }
        """
        self._menu_btn = QPushButton(self)
        self._menu_btn.setIcon(menu_icon)
        self._menu_btn.setIconSize(QSize(16, 16))
        self._menu_btn.setFlat(True)
        self._menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._menu_btn.setFixedSize(btn_size, btn_size)
        self._menu_btn.setStyleSheet(btn_style_menu)
        self._menu_btn.setGeometry(margin, margin, btn_size, btn_size)
        self._menu_btn.clicked.connect(self._show_menu)

        # -- File list --
        self._file_list = QWidget()
        self._file_list.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._file_list.setStyleSheet("background: transparent;")
        self._fl_layout = QVBoxLayout(self._file_list)
        self._fl_layout.setContentsMargins(20, 4, 20, 4)
        self._fl_layout.setSpacing(3)
        self._fl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_label = QLabel(tr("basket.empty_hint"))
        ef = QFont()
        ef.setPointSize(round(10 * self._font_scale))
        self._empty_label.setFont(ef)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: rgba(255,255,255,80);")
        self._fl_layout.addWidget(self._empty_label)

        # -- Footer --
        self._footer = QWidget()
        self._footer.setFixedHeight(int(self.height() * _FOOTER_RATIO))

        # -- Assemble --
        layout.addWidget(self._header)
        layout.addWidget(self._file_list, 1)
        layout.addWidget(self._footer)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)

        painter.setPen(QPen(self._border_color, 1))
        painter.fillPath(path, self._bg_color)
        painter.drawPath(path)

    # ------------------------------------------------------------------
    # Drag-in (accept files from external)
    # ------------------------------------------------------------------

    # Show event (macOS topmost activation)
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if IS_MACOS and not getattr(self, "_macos_level_set", False):
            if self._enforce_macos_topmost():
                self._macos_level_set = True

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
            logger.info("Files dropped | added=%d paths=[%s] total=%d size=%s",
                        added, paths_str, self._basket.count, self._format_size(self._basket.total_size))
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

            drag = QDrag(self)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(zip_path))])
            drag.setMimeData(mime)
            result = drag.exec(Qt.DropAction.CopyAction)

            self._cleanup_temp_zip()

            if stale_files:
                names = "\n".join(p.name for p in stale_files[:5])
                QMessageBox.warning(self, tr("app.name"), tr("basket.files_missing", names=names))

            action = config_manager.get("after_drop_action")
            if action == "close":
                self.close()
            elif action == "clear":
                self._basket.clear()
                self._update_display()
            else:  # keep
                self._update_display()
        else:
            is_shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            is_move = (config_manager.get("default_transfer_mode") == "move") != is_shift
            expected_action = Qt.DropAction.MoveAction if is_move else Qt.DropAction.CopyAction

            drag = QDrag(self)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(p)) for p in valid_files])
            drag.setMimeData(mime)
            result = drag.exec(expected_action)

            if stale_files:
                names = "\n".join(p.name for p in stale_files[:5])
                QMessageBox.warning(self, tr("app.name"), tr("basket.files_missing", names=names))

            action = config_manager.get("after_drop_action")
            if action == "close":
                self.close()
            elif action == "clear":
                self._basket.clear()
                self._update_display()
            else:  # keep
                if result == Qt.DropAction.MoveAction:
                    for p in valid_files:
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
            self._info_label.setText("")
            return

        self._empty_label.hide()

        cnt = self._basket.count
        self._info_label.setText(tr("info.items", count=cnt, size=self._format_size(self._basket.total_size)))

        remaining = self._basket.count - _MAX_VISIBLE_FILES

        for p, label in self._basket.display_labels(_MAX_VISIBLE_FILES):
            lb = QLabel(label)
            lb.setToolTip(str(p))
            fl = QFont()
            fl.setPointSize(round(9 * self._font_scale))
            lb.setFont(fl)
            lb.setStyleSheet("color: rgba(255,255,255,180);")
            self._fl_layout.addWidget(lb)
            self._file_labels.append(lb)

        if remaining > 0:
            more = QLabel(tr("basket.more", count=remaining))
            ml = QFont()
            ml.setPointSize(round(9 * self._font_scale))
            more.setFont(ml)
            more.setStyleSheet("color: rgba(255,255,255,100);")
            self._fl_layout.addWidget(more)
            self._file_labels.append(more)

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
        menu.setStyleSheet(f"""
            QMenu {{
                background: rgba(30, 30, 40, 235);
                border: 1px solid rgba(255,255,255,25);
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                color: rgba(255,255,255,180);
                padding: 6px 20px;
                border-radius: 4px;
                font-size: {mfs}pt;
            }}
            QMenu::item:selected {{
                background: rgba(255,255,255,30);
                color: rgba(255,255,255,255);
            }}
        """)

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

    def closeEvent(self, event) -> None:
        self._cleanup_temp_zip()
        logger.debug("Window closed")
        event.accept()
