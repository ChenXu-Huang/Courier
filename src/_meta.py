"""Package metadata — root directory, version, platform paths."""

import os
import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError

APP_NAME = "Courier"


def _get_version() -> str:
    try:
        return version(APP_NAME.lower())
    except PackageNotFoundError:
        return "0.0.1"


VERSION = _get_version()


IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform == "linux"


def _is_bundled() -> bool:
    """True when running as a compiled/frozen executable (Nuitka, PyInstaller)."""
    return bool(getattr(sys, "frozen", False) or "__compiled__" in globals())


def _resolve_root() -> Path:
    if _is_bundled():
        root_dir = Path(sys.executable).parent
        if root_dir.name.lower() in ("bin", "macos"):
            root_dir = root_dir.parent
        return root_dir
    return Path(__file__).resolve().parent.parent


ROOT_DIR = _resolve_root()


def _is_portable() -> bool:
    """True when a ``.portable`` file exists next to the bundled executable.

    In portable mode all runtime data (config, logs) is stored directly
    under ``ROOT_DIR`` instead of OS-specific standard locations.
    """
    return _is_bundled() and (ROOT_DIR / ".portable").is_file()


def _get_resources_dir() -> Path:
    if IS_MACOS and _is_bundled():
        return ROOT_DIR / "Resources"
    return ROOT_DIR / "resources"


def _get_config_dir() -> Path:
    if not _is_bundled() or _is_portable():
        return ROOT_DIR / "config"
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    return Path(xdg_config) / APP_NAME if xdg_config else Path.home() / ".config" / APP_NAME


def _get_log_dir() -> Path:
    if not _is_bundled() or _is_portable():
        return ROOT_DIR / "logs"
    if IS_MACOS:
        return Path.home() / "Library" / "Logs" / APP_NAME
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME / "logs"
    xdg_data = os.environ.get("XDG_DATA_HOME")
    return Path(xdg_data) / APP_NAME / "logs" if xdg_data else Path.home() / ".local" / "share" / APP_NAME / "logs"


RESOURCES_DIR = _get_resources_dir()
CONFIG_DIR = _get_config_dir()
LOG_DIR = _get_log_dir()
