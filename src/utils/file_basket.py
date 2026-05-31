import math
from collections import Counter
from pathlib import Path

from ..logger import get_logger

logger = get_logger(__name__)


class FileBasket:
    """Staged file path list — dedup, stats, validation."""

    def __init__(self) -> None:
        self._files: list[Path] = []
        self._paths: set[Path] = set()

    def add(self, paths: list[Path]) -> int:
        """Deduplicate and add *paths*. Returns number of new items."""
        added = 0
        for p in paths:
            resolved = p.resolve()
            if resolved in self._paths:
                continue
            self._files.append(resolved)
            self._paths.add(resolved)
            added += 1

        if added < len(paths):
            logger.debug(
                "Basket add | requested=%d added=%d duplicates=%d",
                len(paths), added, len(paths) - added,
            )
        return added

    def remove(self, path: Path) -> bool:
        resolved = path.resolve()
        if resolved not in self._paths:
            return False
        self._files.remove(resolved)
        self._paths.discard(resolved)
        logger.debug("Basket remove | path=%s", resolved)
        return True

    def clear(self) -> None:
        self._files.clear()
        self._paths.clear()
        logger.debug("Basket cleared")

    @property
    def files(self) -> list[Path]:
        return list(self._files)

    @property
    def count(self) -> int:
        return len(self)

    @property
    def is_empty(self) -> bool:
        return not self

    @property
    def total_size(self) -> int:
        def _size(p: Path) -> int:
            try:
                if p.is_file():
                    return p.stat().st_size
                if p.is_dir():
                    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            except OSError:
                pass
            return 0

        return sum(_size(p) for p in self._files)

    @staticmethod
    def _format_size(n: int) -> str:
        if n <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        idx = min(int(math.log(n, 1024)), len(units) - 1)
        return f"{n / (1024**idx):.2f} {units[idx]}"

    def validate(self) -> list[Path]:
        """Return paths that no longer exist on disk."""
        stale = [p for p in self._files if not p.exists()]
        if stale:
            logger.warning("Stale files detected | count=%d", len(stale))
        return stale

    @property
    def duplicate_names(self) -> set[str]:
        """Return set of filenames that appear more than once."""
        counts = Counter(p.name for p in self._files)
        return {name for name, c in counts.items() if c > 1}

    def display_labels(self, max_count: int = 0) -> list[tuple[Path, str]]:
        """Return ``(path, label)`` pairs.

        Labels include a parent-directory prefix when the filename
        collides with another staged file.
        """
        dups = self.duplicate_names

        def _label(p: Path) -> str:
            label = f"{p.parent.name}/{p.name}" if p.name in dups else p.name
            return label if len(label) <= 44 else label[:41] + "..."

        pairs = [(p, _label(p)) for p in self._files]
        return pairs[:max_count] if max_count > 0 else pairs

    def __len__(self) -> int:
        return len(self._files)

    def __bool__(self) -> bool:
        return bool(self._files)

    def __iter__(self):
        return iter(self._files)
