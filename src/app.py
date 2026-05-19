"""Application lifecycle manager — entry point for the GUI."""

import sys

from ._meta import APP_NAME, VERSION, ROOT_DIR, LOG_DIR, RESOURCES_DIR
from .logger import LoggerManager, LoggerConfig

_LOG_CONFIG = LoggerConfig(
    name=APP_NAME.lower(),
    level="INFO",
    log_dir=LOG_DIR,
    console=False,
    console_color=False,
    json_file=False,
    text_file=True,
    error_file=True,
    max_bytes=1024 * 1024,
    backup_count=5,
    default_extra={"app_version": VERSION, "env": "app"},
)

LoggerManager.configure(_LOG_CONFIG)
logger = LoggerManager.get(__name__)


def launch_gui() -> int:
    from PySide6.QtGui import QCursor, QIcon
    from PySide6.QtWidgets import QApplication

    from .config import config_manager
    from .gui import CourierTrayManager
    from .utils import CourierHotkeyManager

    logger.info("Courier starting | version=%s | root=%s", VERSION, ROOT_DIR)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(QIcon(str(RESOURCES_DIR / "icons" / "courier.svg")))
    app.setQuitOnLastWindowClosed(False)

    # --- Config ---
    config_manager.reload()

    # --- Tray (optionally shows first window) ---
    tray = CourierTrayManager()
    if config_manager.get("show_on_startup"):
        tray.create_new_window()

    # --- Global hotkey ---
    hotkey = CourierHotkeyManager()
    hotkey.hotkey_triggered.connect(
        lambda: tray.create_new_window_at(
            QCursor.pos().x() - config_manager.get("window_size") // 2,
            QCursor.pos().y() - config_manager.get("window_size") // 2,
        )
    )
    hotkey.start()
    logger.info("Global hotkey registered | hotkey=%s", hotkey.hotkey)

    tray.settings_about_to_open.connect(hotkey.stop)
    tray.settings_closed.connect(hotkey.start)

    logger.info("Courier started successfully")

    # --- Event loop ---
    exit_code = app.exec()

    # --- Cleanup ---
    logger.info("Courier shutting down (code=%s)", exit_code)
    hotkey.cleanup()
    LoggerManager.shutdown()
    return exit_code
