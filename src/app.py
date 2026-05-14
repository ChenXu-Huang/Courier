"""Application lifecycle manager — entry point for the GUI."""

import sys
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from ._meta import ROOT_DIR, VERSION
from .logger import LoggerManager, LoggerConfig

_LOG_CONFIG = LoggerConfig(
    name="courier",
    level="INFO",
    log_dir=ROOT_DIR / "logs",
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

from .config import config_manager
from .gui import CourierTrayManager
from .utils import CourierHotkeyManager


def launch_gui() -> int:
    logger.info("Courier starting | version=%s | root=%s", VERSION, ROOT_DIR)

    # --- Qt application ---
    app = QApplication(sys.argv)
    app.setApplicationName("Courier")
    app.setOrganizationName("Courier")
    app.setQuitOnLastWindowClosed(False)

    # --- Config ---
    config_manager.reload()

    # --- Tray (starts first window) ---
    tray = CourierTrayManager()
    tray.create_new_window()

    # --- Global hotkey ---
    hotkey = CourierHotkeyManager()
    hotkey.hotkey_triggered.connect(
        lambda: tray.create_new_window_at(
            QCursor.pos().x() - config_manager.get("window_size", 320) // 2,
            QCursor.pos().y() - config_manager.get("window_size", 320) // 2,
        )
    )
    hotkey.start()
    logger.info("Global hotkey registered | hotkey=%s", hotkey.hotkey)

    logger.info("Courier started successfully")

    # --- Event loop ---
    exit_code = app.exec()

    # --- Cleanup ---
    logger.info("Courier shutting down (code=%s)", exit_code)
    hotkey.stop()
    LoggerManager.shutdown()
    return exit_code
