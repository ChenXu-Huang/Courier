"""Temporary zip file utilities for file drag-out compression."""

import os
import tempfile
import zipfile
from pathlib import Path

from ..logger import get_logger

logger = get_logger(__name__)


def create_temp_zip(files: list[Path]) -> Path | None:
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


def cleanup_temp_zip(zip_path: Path | None) -> None:
    """Remove a temporary zip file if it exists."""
    if zip_path is not None:
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to clean up temp zip: %s", zip_path)
