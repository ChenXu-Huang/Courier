"""System tray icon and menu."""

from PySide6.QtCore import QObject, QRect, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import config_manager
from ..logger import get_logger
from .basket_window import CourierBasketWindow
from .settings_dialog import CourierSettingsDialog

logger = get_logger(__name__)


class CourierTrayManager(QObject):
    """Owns the system tray icon and manages window instances."""

    def __init__(self) -> None:
        super().__init__()
        self._windows: list[CourierBasketWindow] = []
        self._setup_tray()

    # ------------------------------------------------------------------
    # Tray setup
    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._make_icon())
        self._tray.setToolTip("Courier")

        # Context menu
        menu = QMenu()

        new_act = QAction("New Window", self)
        new_act.triggered.connect(self.create_new_window)

        settings_act = QAction("Settings", self)
        settings_act.triggered.connect(self._open_settings)

        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.quit)

        menu.addAction(new_act)
        menu.addSeparator()
        menu.addAction(settings_act)
        menu.addSeparator()
        menu.addAction(quit_act)

        self._tray.setContextMenu(menu)

        # Left-click → new window
        self._tray.activated.connect(self._on_activated)

        self._tray.show()
        logger.info("System tray initialized")

    def _make_icon(self) -> QIcon:
        """Generate a simple coloured-circle tray icon."""
        size = 64
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        color = QColor(config_manager.get("theme_color", "#3B82F6"))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(4, 4, 56, 56)

        p.setPen(QPen(Qt.GlobalColor.white, 3))
        f = QFont("Segoe UI", 28, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "C")
        p.end()

        return QIcon(pix)

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def create_new_window(self) -> CourierBasketWindow:
        """Create and show a new basket window centred on screen."""
        w = self._make_window()
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - w.width()) // 2 + geo.x()
            y = (geo.height() - w.height()) // 2 + geo.y()
            w.move(x, y)
        w.show()
        logger.info("New window created | windows=%d", len(self._windows))
        return w

    def create_new_window_at(self, x: int, y: int) -> CourierBasketWindow:
        """Create and show a new basket window at the given screen position."""
        w = self._make_window()
        w.move(x, y)
        w.show()
        logger.info("New window created at (%d, %d) | windows=%d", x, y, len(self._windows))
        return w

    def _make_window(self) -> CourierBasketWindow:
        """Build a window, register it, and return it (don't show yet)."""
        w = CourierBasketWindow()
        w.destroyed.connect(lambda: self._windows.remove(w) if w in self._windows else None)
        self._windows.append(w)
        return w

    def close_all_windows(self) -> None:
        for w in list(self._windows):
            w.close()
            w.deleteLater()
        self._windows.clear()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        logger.info("Settings dialog opened")
        dialog = CourierSettingsDialog(None)
        dialog.exec()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            logger.debug("Tray icon left-clicked")
            self.create_new_window()

    def quit(self) -> None:
        logger.info("Quit requested, shutting down")
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setProperty("_quitting", True)
            self.close_all_windows()
            app.quit()
