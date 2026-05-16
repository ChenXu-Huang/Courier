"""Square floating window — drag-drop file staging surface."""

import math
import sys
from pathlib import Path
from PySide6.QtCore import QSize, Qt, QMimeData, QRectF, QUrl, QPoint
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .._meta import RESOURCES_DIR
from ..config import config_manager
from ..logger import get_logger
from ..utils import FileBasket
from ..utils.i18n import tr, language_changed

logger = get_logger(__name__)

_CLOSE_ICON_PATH = RESOURCES_DIR / "icons" / "close.svg"

_HEADER_RATIO = 0.15
_FOOTER_RATIO = 0.15
_MAX_VISIBLE_FILES = 8


class CourierBasketWindow(QWidget):
    """A square, always-on-top, frameless window for staging file transfers."""

    def __init__(self) -> None:
        super().__init__()
        self._basket = FileBasket()
        self._drag_start_pos: QPoint | None = None
        self._drag_out_started = False
        self._file_labels: list[QLabel] = []

        self._setup_window()
        self._create_ui()
        self._apply_theme()
        self._update_display()
        language_changed.connect(self._retranslate_ui)

    def _setup_window(self) -> None:
        size = int(config_manager.get("window_size", 320))
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
        self._radius = int(config_manager.get("window_radius", 20))
        self._border_color = QColor(255, 255, 255, 25)

        opacity = float(config_manager.get("window_opacity", 0.92))
        self.setWindowOpacity(opacity)
        logger.debug("Theme applied | radius=%d opacity=%.2f", self._radius, opacity)

    def _enforce_macos_topmost(self) -> bool:
        """Use ctypes + Objective-C runtime to float above all apps.

        Returns ``True`` on success, ``False`` if the NSWindow could not
        be configured (so callers can decide whether to cache the result).
        """
        import ctypes
        from ctypes import c_bool, c_char_p, c_long, c_void_p

        try:
            objc = ctypes.CDLL("/usr/lib/libobjc.dylib")
            objc.sel_registerName.restype = c_void_p
            objc.sel_registerName.argtypes = [c_char_p]

            msg = objc.objc_msgSend
            msg_i = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_long)(msg)
            msg_b = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p, c_bool)(msg)

            view = c_void_p(self.winId())
            sel_window = objc.sel_registerName(b"window")
            window = msg(view, sel_window)
            if not window:
                logger.warning("Failed to obtain NSWindow via ctypes")
                return False

            msg_i(window, objc.sel_registerName(b"setLevel:"), 3)
            msg_b(window, objc.sel_registerName(b"setHidesOnDeactivate:"), False)
            logger.debug("macOS topmost enforced via ctypes")
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
        hl.setContentsMargins(20, 0, 44, 0)

        self._title_label = QLabel(tr("app.name"))
        tf = QFont()
        tf.setPointSize(11)
        tf.setBold(True)
        self._title_label.setFont(tf)
        self._title_label.setStyleSheet("color: rgba(255,255,255,200);")

        self._info_label = QLabel()
        inf = QFont()
        inf.setPointSize(8)
        self._info_label.setFont(inf)
        self._info_label.setStyleSheet("color: rgba(255,255,255,110);")

        header_text_col = QVBoxLayout()
        header_text_col.setContentsMargins(0, 10, 0, 4)
        header_text_col.setSpacing(1)
        header_text_col.addWidget(self._title_label)
        header_text_col.addWidget(self._info_label)

        hl.addLayout(header_text_col)
        hl.addStretch()

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
        self._title_close_btn.clicked.connect(self._minimize_to_tray)
        btn_size = 28
        margin = 8
        self._title_close_btn.setGeometry(self.width() - btn_size - margin, margin, btn_size, btn_size)
        self._title_close_btn.raise_()

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
        ef.setPointSize(10)
        self._empty_label.setFont(ef)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: rgba(255,255,255,80);")
        self._fl_layout.addWidget(self._empty_label)

        # -- Footer --
        self._footer = QWidget()
        self._footer.setFixedHeight(int(self.height() * _FOOTER_RATIO))
        fl2 = QHBoxLayout(self._footer)
        fl2.setContentsMargins(16, 4, 16, 10)

        btn_style = "QPushButton { color: rgba(255,255,255,140); font-size: 9pt; border: none; } QPushButton:hover { color: rgba(255,255,255,220); }"
        self._clear_btn = QPushButton(tr("basket.clear"))
        self._clear_btn.setFlat(True)
        self._clear_btn.setStyleSheet(btn_style)
        self._clear_btn.clicked.connect(self._on_clear)

        fl2.addStretch()
        fl2.addWidget(self._clear_btn)

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
        if sys.platform == "darwin" and not getattr(self, "_macos_level_set", False):
            if self._enforce_macos_topmost():
                self._macos_level_set = True

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))

        if paths:
            added = self._basket.add(paths)
            logger.info("Files dropped | added=%d total=%d size=%s", added, self._basket.count, self._format_size(self._basket.total_size))
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
        self._drag_start_pos = None  # prevent re-entry

        stale_files = self._basket.validate()
        for p in stale_files:
            self._basket.remove(p)

        if self._basket.is_empty:
            logger.warning("All files stale, drag-out cancelled")
            self._update_display()
            return

        valid_files = self._basket.files

        is_shift = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        is_move = (config_manager.get("default_transfer_mode", "copy") == "move") != is_shift
        expected_action = Qt.DropAction.MoveAction if is_move else Qt.DropAction.CopyAction

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in valid_files])
        drag.setMimeData(mime)
        result = drag.exec(expected_action)

        if stale_files:
            names = "\n".join(p.name for p in stale_files[:5])
            QMessageBox.warning(self, tr("app.name"), tr("basket.files_missing", names=names))

        # Basket state: determined solely by after_drop_action
        action = config_manager.get("after_drop_action", "close")
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
        self._clear_btn.setText(tr("basket.clear"))
        self._update_display()

    def _update_display(self) -> None:
        for lb in self._file_labels:
            lb.deleteLater()
        self._file_labels.clear()

        if self._basket.is_empty:
            self._empty_label.show()
            self._info_label.setText("")
            self._clear_btn.setVisible(False)
            return

        self._empty_label.hide()
        self._clear_btn.setVisible(True)

        cnt = self._basket.count
        self._info_label.setText(tr("info.items", count=cnt, size=self._format_size(self._basket.total_size)))

        remaining = self._basket.count - _MAX_VISIBLE_FILES

        for p, label in self._basket.display_labels(_MAX_VISIBLE_FILES):
            lb = QLabel(label)
            lb.setToolTip(str(p))
            lb.setStyleSheet("color: rgba(255,255,255,180); font-size: 9pt;")
            self._fl_layout.addWidget(lb)
            self._file_labels.append(lb)

        if remaining > 0:
            more = QLabel(tr("basket.more", count=remaining))
            more.setStyleSheet("color: rgba(255,255,255,100); font-size: 9pt;")
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
    # Actions
    # ------------------------------------------------------------------

    def _on_clear(self) -> None:
        count = self._basket.count
        self._basket.clear()
        logger.info("Basket cleared | removed=%d", count)
        self._update_display()

    def _minimize_to_tray(self) -> None:
        """Hide to system tray instead of closing."""
        self.hide()

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication) and app.property("_quitting"):
            logger.debug("Window closed during quit")
            event.accept()
        else:
            logger.debug("Window minimized to tray")
            event.ignore()
            self.hide()
