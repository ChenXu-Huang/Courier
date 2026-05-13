"""Package init — export public API."""

import sys
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError


def _resolve_root() -> Path:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        root_dir = Path(sys.executable).parent
        if root_dir.name.lower() == "bin":
            root_dir = root_dir.parent
        return root_dir
    return Path(__file__).resolve().parent.parent


def _get_version() -> str:
    try:
        return version("courier")
    except PackageNotFoundError:
        return "0.0.0"


ROOT_DIR = _resolve_root()
VERSION = _get_version()


from .app import launch_gui

__all__ = ["launch_gui"]

__author__ = ["ChenXu-Huang"]

__version__ = VERSION
