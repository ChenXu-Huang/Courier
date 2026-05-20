__all__ = ["config_manager"]

import json
from pathlib import Path
from typing import Any, Callable

from ._meta import CONFIG_DIR, IS_MACOS
from .logger import get_logger, log_exceptions

logger = get_logger(__name__)

_DEFAULT_CONFIG: dict[str, Any] = {
    "language": "auto",
    "theme_mode": "auto",
    "window_size": 240,
    "window_opacity": 0.90,
    "window_radius": 20,
    "after_drop_action": "close",
    "default_transfer_mode": "copy",
    "global_hotkey": "shift+enter" if IS_MACOS else "shift+caps lock",
    "show_on_startup": True,
    "compress_on_drag": False,
}


class _MISSING:
    """Sentinel for absent values (avoids ambiguity with ``None``)."""


class JsonConfigManager:
    """Generic JSON-backed config store with nested key-path access.

    Features in-memory caching, lazy loading, auto-save, change callbacks,
    and context-manager batching.

    Examples:
    >>> config_manager = JsonConfigManager("config.json")
        config_manager.get("database.host", "localhost")
        config_manager.set("database.port", 5432)
        config_manager["database"] = {"host": "pg.example.com"}
        with config_manager:
            config_manager.set("a", 1)
            config_manager.set("b", 2)   # single disk write on exit
    """

    def __init__(
        self,
        config_path: str | Path = "config.json",
        *,
        auto_save: bool = True,
        default: dict[str, Any] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self._data: dict[str, Any] = {}
        self._loaded = False
        self._original: dict[str, Any] = {}  # snapshot for change detection
        self._dirty = False
        self._auto_save = auto_save
        self._batch = 0  # >0 means inside ``with store``
        self._default = default
        self._callbacks: dict[str, list[Callable[[str, Any, Any], None]]] = {}

    @log_exceptions()
    def _load_json(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                logger.error("Failed to parse %s: %s", self.config_path.name, e)
        if self._default is not None:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config_path.open("w", encoding="utf-8", newline="") as f:
                json.dump(self._default, f, indent=4, ensure_ascii=False)
            return dict(self._default)
        return {}

    @log_exceptions()
    def _save_json(self, data: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8", newline="") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self._data = self._load_json()
            self._loaded = True
            self._original = json.loads(json.dumps(self._data))

    def _flush(self) -> None:
        """Write to disk if the store is dirty and not in batch mode."""
        if self._dirty and self._auto_save and self._batch == 0:
            self._save_json(self._data)
            self._dirty = False
            self._original = json.loads(json.dumps(self._data))

    @staticmethod
    def _get_nested(data: dict, path: str, default: Any = None) -> Any:
        keys = path.split(".")
        val = data
        for key in keys:
            if isinstance(val, dict) and key in val:
                val = val[key]
            else:
                return default
        return val

    @staticmethod
    def _set_nested(data: dict, path: str, value: Any) -> None:
        keys = path.split(".")
        for key in keys[:-1]:
            data = data.setdefault(key, {})
        data[keys[-1]] = value

    @staticmethod
    def _del_nested(data: dict, path: str) -> bool:
        keys = path.split(".")
        for key in keys[:-1]:
            if not isinstance(data, dict) or key not in data:
                return False
            data = data[key]
        if keys[-1] in data:
            data.pop(keys[-1])
            return True
        return False

    def _fire_callbacks(self, path: str, old: Any, new: Any) -> None:
        for cb_path, cbs in self._callbacks.items():
            if path == cb_path or path.startswith(cb_path + "."):
                for cb in cbs:
                    try:
                        cb(path, old, new)
                    except Exception:
                        logger.exception("Callback failed for %s", path)

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Retrieve value at *path* (dot-separated).

        Falls back to ``self._default`` (if set) when *path* is not fount
        in loaded config. Pass an explicit *default* to override.
        """
        self._ensure_loaded()
        val = self._get_nested(self._data, path, _MISSING)
        if val is not _MISSING:
            return val
        if self._default is not None:
            val = self._get_nested(self._default, path, _MISSING)
            if val is not _MISSING:
                return val
        return default

    def set(self, path: str, value: Any) -> None:
        """Set *value* at *path*, marking store dirty and auto-saving."""
        self._ensure_loaded()
        old = self._get_nested(self._data, path, _MISSING)
        self._set_nested(self._data, path, value)
        self._dirty = True
        self._fire_callbacks(path, old, value)
        self._flush()
        logger.debug("Config set | %s = %r", path, value)

    def delete(self, path: str) -> bool:
        """Delete the key at *path*. Returns True if the key existed."""
        self._ensure_loaded()
        old = self._get_nested(self._data, path, _MISSING)
        deleted = self._del_nested(self._data, path)
        if deleted:
            self._dirty = True
            self._fire_callbacks(path, old, _MISSING)
            self._flush()
            logger.debug("Config deleted | %s", path)
        return deleted

    def reload(self) -> None:
        """Discard in-memory changes and re-read from disk."""
        self._data = self._load_json()
        self._original = json.loads(json.dumps(self._data))
        self._dirty = False
        logger.info("Config reloaded from %s", self.config_path)

    def save(self) -> None:
        """Force an immediate write to disk."""
        self._ensure_loaded()
        self._save_json(self._data)
        self._dirty = False
        self._original = json.loads(json.dumps(self._data))

    def clear(self) -> None:
        """Clear all data in memory (does **not** delete the file)."""
        self._ensure_loaded()
        self._data.clear()
        self._dirty = True
        self._flush()

    def keys(self) -> list[str]:
        """Return top-level keys."""
        self._ensure_loaded()
        return list(self._data.keys())

    def items(self):
        """Iterate over ``(key, value)`` pairs (shallow)."""
        self._ensure_loaded()
        return self._data.items()

    def on_change(self, path: str, callback: Callable[[str, Any, Any], None]) -> Callable[[], None]:
        """Register *callback* for changes under *path*.

        The callback receives ``(changed_path, old_value, new_value)``.
        Returns a zero-arg function that removes the registration.
        """
        self._callbacks.setdefault(path, []).append(callback)

        def _unregister() -> None:
            try:
                self._callbacks[path].remove(callback)
            except ValueError:
                pass

        return _unregister

    def is_dirty(self) -> bool:
        """Whether there are unsaved changes."""
        return self._dirty

    def __enter__(self):
        self._ensure_loaded()
        self._batch += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._batch -= 1
        if exc_type is None:
            self._flush()

    def __getitem__(self, path: str) -> Any:
        val = self.get(path, _MISSING)
        if val is _MISSING:
            raise KeyError(f"Config key {path!r} not found")
        return val

    def __setitem__(self, path: str, value: Any) -> None:
        self.set(path, value)

    def __delitem__(self, path: str) -> None:
        if not self.delete(path):
            raise KeyError(f"Config key {path!r} not found")

    def __contains__(self, path: str) -> bool:
        return self.get(path, _MISSING) is not _MISSING

    def __len__(self) -> int:
        self._ensure_loaded()
        return len(self._data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self.config_path)!r})"


config_manager = JsonConfigManager(CONFIG_DIR / "settings.json", default=_DEFAULT_CONFIG)
