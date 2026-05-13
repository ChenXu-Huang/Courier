import shutil
from pathlib import Path
from typing import Callable, Optional

from ..logger import get_logger

logger = get_logger(__name__)

ProgressCb = Callable[[int, int], None]


def copy_files(
    sources: list[Path],
    dest_dir: Path,
    *,
    progress: Optional[ProgressCb] = None,
) -> list[Path]:
    """Copy *sources* into *dest_dir* preserving metadata.

    Returns list of successfully copied target paths.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ok: list[Path] = []
    total = len(sources)
    for i, src in enumerate(sources):
        try:
            dst = dest_dir / src.name
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
            ok.append(dst)
        except OSError:
            logger.exception("Failed to copy %s to %s", src, dest_dir)
        if progress:
            progress(i + 1, total)
    return ok


def move_files(
    sources: list[Path],
    dest_dir: Path,
    *,
    progress: Optional[ProgressCb] = None,
) -> list[Path]:
    """Move *sources* into *dest_dir* (cross-device safe).

    Returns list of successfully moved target paths.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ok: list[Path] = []
    total = len(sources)
    for i, src in enumerate(sources):
        try:
            dst = dest_dir / src.name
            shutil.move(str(src), str(dst))
            ok.append(dst)
        except OSError:
            logger.exception("Failed to move %s to %s", src, dest_dir)
        if progress:
            progress(i + 1, total)
    return ok


def delete_sources(sources: list[Path]) -> list[Path]:
    """Delete source files/dirs after a successful move drag-out."""
    removed: list[Path] = []
    for src in sources:
        try:
            if src.is_dir():
                shutil.rmtree(src)
            else:
                src.unlink()
            removed.append(src)
        except OSError:
            logger.exception("Failed to delete %s", src)
    return removed
