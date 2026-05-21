"""System tray icon and menu."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .._meta import RESOURCES_DIR
from ..config import config_manager
from ..logger import get_logger
from ..utils import tr, language_changed
from .basket_window import CourierBasketWindow
from .settings_dialog import CourierSettingsDialog

_ICON_PATH = RESOURCES_DIR / "icons" / "courier.svg"

logger = get_logger(__name__)


class CourierTrayManager(QObject):
    """Owns the system tray icon and manages window instances."""

    settings_about_to_open = Signal()
    settings_closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._windows: list[CourierBasketWindow] = []
        self._setup_tray()
        language_changed.connect(self._retranslate_tray)

    # ------------------------------------------------------------------
    # Tray setup
    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self._make_icon())
        self._tray.setToolTip("Courier")

        # Context menu
        menu = QMenu()

        self._new_act = QAction(tr("tray.new_window"), self)
        self._new_act.triggered.connect(self.create_new_window)

        self._settings_act = QAction(tr("tray.settings"), self)
        self._settings_act.triggered.connect(self._open_settings)

        self._quit_act = QAction(tr("tray.quit"), self)
        self._quit_act.triggered.connect(self.quit)

        menu.addAction(self._new_act)
        menu.addSeparator()
        menu.addAction(self._settings_act)
        menu.addSeparator()
        menu.addAction(self._quit_act)

        self._tray.setContextMenu(menu)

        # Left-click → new window
        self._tray.activated.connect(self._on_activated)

        self._tray.show()
        logger.info("System tray initialized")

    def _make_icon(self) -> QIcon:
        return QIcon(str(_ICON_PATH))

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
        """Create and show a new basket window centered at the given screen position."""
        size = config_manager.get("window_size")
        w = self._make_window()
        w.move(x - size // 2, y - size // 2)
        w.show()
        logger.info("New window created at (%d, %d) | windows=%d", x, y, len(self._windows))
        return w

    def _make_window(self) -> CourierBasketWindow:
        """Build a window, register it, and return it (don't show yet)."""
        w = CourierBasketWindow()
        w.destroyed.connect(lambda: self._windows.remove(w) if w in self._windows else None)
        self._windows.append(w)
        return w

    def _retranslate_tray(self) -> None:
        self._new_act.setText(tr("tray.new_window"))
        self._settings_act.setText(tr("tray.settings"))
        self._quit_act.setText(tr("tray.quit"))
        self._tray.setToolTip(tr("app.name"))

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
        self.settings_about_to_open.emit()
        dialog = CourierSettingsDialog(None)
        dialog.exec()
        self.settings_closed.emit()

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
