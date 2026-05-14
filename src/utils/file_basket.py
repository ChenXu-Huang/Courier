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
            if resolved not in self._paths:
                self._files.append(resolved)
                self._paths.add(resolved)
                added += 1
        if added != len(paths):
            logger.debug("Basket add | requested=%d added=%d duplicates=%d", len(paths), added, len(paths) - added)
        return added

    def remove(self, path: Path) -> bool:
        resolved = path.resolve()
        if resolved not in self._paths:
            return False
        self._files = [p for p in self._files if p != resolved]
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
        return len(self._files)

    @property
    def is_empty(self) -> bool:
        return len(self._files) == 0

    @property
    def total_size(self) -> int:
        total = 0
        for p in self._files:
            try:
                if p.is_file():
                    total += p.stat().st_size
                elif p.is_dir():
                    for f in p.rglob("*"):
                        if f.is_file():
                            total += f.stat().st_size
            except OSError:
                pass
        return total

    def validate(self) -> list[Path]:
        """Return paths that no longer exist on disk."""
        stale = [p for p in self._files if not p.exists()]
        if stale:
            logger.warning("Stale files detected | count=%d", len(stale))
        return stale

    @property
    def duplicate_names(self) -> set[str]:
        """Return set of filenames that appear more than once."""
        names: dict[str, int] = {}
        for p in self._files:
            names[p.name] = names.get(p.name, 0) + 1
        return {n for n, c in names.items() if c > 1}

    def display_labels(self, max_count: int = 0) -> list[tuple[Path, str]]:
        """Return ``(path, label)`` pairs.

        Labels include a parent-directory prefix when the filename
        collides with another staged file.
        """
        dups = self.duplicate_names
        pairs: list[tuple[Path, str]] = []
        for p in self._files:
            if p.name in dups:
                label = f"{p.parent.name}/{p.name}"
            else:
                label = p.name
            if len(label) > 44:
                label = label[:41] + "..."
            pairs.append((p, label))
        if max_count > 0:
            pairs = pairs[:max_count]
        return pairs

    def __len__(self) -> int:
        return len(self._files)

    def __bool__(self) -> bool:
        return not self.is_empty

    def __iter__(self):
        return iter(self._files)
