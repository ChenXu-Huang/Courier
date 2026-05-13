import sys
from PySide6.QtWidgets import QApplication

from . import ROOT_DIR, VERSION


_CONFIG_PATH = ROOT_DIR / "config" / "settings.json"
_DEFAULT_CONFIG = {
    "window_size": 320,
    "window_opacity": 0.92,
    "window_radius": 20,
    "theme_color": "#3B82F6",
    "after_drop_action": "close",
    "default_transfer_mode": "copy",
}

_LOG_CONFIG = {
    "name": "courier",
    "level": "INFO",
    "log_dir": ROOT_DIR / "logs",
    "console": False,
    "console_color": False,
    "json_file": False,
    "text_file": True,
    "error_file": True,
    "max_bytes": 1024 * 1024,
    "backup_count": 5,
    "default_extra": {"app_version": VERSION, "env": "app"},
}


def launch_gui() -> int:
    # --- Logging ---
    from .logger import LoggerManager

    LoggerManager.configure(**_LOG_CONFIG)
    logger = LoggerManager.get(__name__)
    logger.info("Courier starting | version=%s | root=%s", VERSION, ROOT_DIR)

    # --- Qt application ---
    app = QApplication(sys.argv)
    app.setApplicationName("Courier")
    app.setOrganizationName("Courier")
    app.setQuitOnLastWindowClosed(False)

    # --- Config ---
    from .config import JsonConfig

    config = JsonConfig(_CONFIG_PATH, default=_DEFAULT_CONFIG)
    config.reload()

    # --- Tray (starts first window) ---
    from .gui import CourierTrayManager

    tray = CourierTrayManager(config)
    tray.create_new_window()

    logger.info("Courier started successfully")

    # --- Event loop ---
    exit_code = app.exec()

    # --- Cleanup ---
    logger.info("Courier shutting down (code=%s)", exit_code)
    LoggerManager.shutdown()
    return exit_code
