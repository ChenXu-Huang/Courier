"""Square floating window — drag-drop file staging surface."""

import math
from pathlib import Path
from PySide6.QtCore import Qt, QMimeData, QRectF, QUrl
from PySide6.QtGui import QColor, QDrag, QFont, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..utils import FileBasket

_HEADER_RATIO = 0.15
_FOOTER_RATIO = 0.15
_MAX_VISIBLE_FILES = 8


class CourierBasketWindow(QWidget):
    """A square, always-on-top, frameless window for staging file transfers."""

    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config
        self._basket = FileBasket()
        self._drag_start_pos = None
        self._drag_out_started = False
        self._file_labels: list[QLabel] = []

        self._setup_window()
        self._create_ui()
        self._apply_theme()
        self._update_display()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        size = int(self._config.get("window_size", 320))
        size = max(200, min(600, size))

        self.setFixedSize(size, size)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAcceptDrops(True)

    def _apply_theme(self) -> None:
        self._bg_color = QColor(30, 30, 40, 235)
        self._radius = int(self._config.get("window_radius", 20))
        self._border_color = QColor(255, 255, 255, 25)

        opacity = float(self._config.get("window_opacity", 0.92))
        self.setWindowOpacity(opacity)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _create_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # -- Header --
        self._header = QWidget()
        self._header.setFixedHeight(int(self.height() * _HEADER_RATIO))
        self._header.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hl = QVBoxLayout(self._header)
        hl.setContentsMargins(20, 10, 20, 4)
        hl.setSpacing(1)

        self._title_label = QLabel("Courier")
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

        hl.addWidget(self._title_label)
        hl.addWidget(self._info_label)

        # -- File list --
        self._file_list = QWidget()
        self._file_list.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._file_list.setStyleSheet("background: transparent;")
        self._fl_layout = QVBoxLayout(self._file_list)
        self._fl_layout.setContentsMargins(20, 4, 20, 4)
        self._fl_layout.setSpacing(3)
        self._fl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._empty_label = QLabel("Drop files here")
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

        btn_style = "QPushButton { color: rgba(255,255,255,140); font-size: 9pt; border: none; }QPushButton:hover { color: rgba(255,255,255,220); }"
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFlat(True)
        self._clear_btn.setStyleSheet(btn_style)
        self._clear_btn.clicked.connect(self._on_clear)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFlat(True)
        self._close_btn.setStyleSheet(btn_style)
        self._close_btn.clicked.connect(self._minimize_to_tray)

        fl2.addWidget(self._clear_btn)
        fl2.addStretch()
        fl2.addWidget(self._close_btn)

        # -- Assemble --
        layout.addWidget(self._header)
        layout.addWidget(self._file_list, 1)
        layout.addWidget(self._footer)

    # ------------------------------------------------------------------
    # Painting (rounded-rect background)
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
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

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths: list[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                paths.append(Path(local))

        if paths:
            self._basket.add(paths)
            self._update_display()

        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Drag-out (drag files to external target) & window move
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self._drag_out_started = False

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_start_pos = None
        self._drag_out_started = False

    def _start_drag_out(self) -> None:
        """Initiate QDrag with all staged file URLs."""
        self._drag_start_pos = None  # prevent re-entry

        drag = QDrag(self)
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(p)) for p in self._basket.files])
        drag.setMimeData(mime)

        drag.exec(Qt.DropAction.CopyAction)

        # Post-drop behaviour
        action = self._config.get("after_drop_action", "close")
        if action == "close":
            self.close()
        elif action == "clear":
            self._basket.clear()
            self._update_display()

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

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
        self._info_label.setText(f"{cnt} items · {self._format_size(self._basket.total_size)}")

        remaining = self._basket.count - _MAX_VISIBLE_FILES

        for p, label in self._basket.display_labels(_MAX_VISIBLE_FILES):
            lb = QLabel(label)
            lb.setToolTip(str(p))
            lb.setStyleSheet("color: rgba(255,255,255,180); font-size: 9pt;")
            self._fl_layout.addWidget(lb)
            self._file_labels.append(lb)

        if remaining > 0:
            more = QLabel(f"+{remaining} more...")
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
        self._basket.clear()
        self._update_display()

    def _minimize_to_tray(self) -> None:
        """Hide to system tray instead of closing."""
        self.hide()

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication) and app.property("_quitting"):
            event.accept()
        else:
            event.ignore()
            self.hide()
