import json
import os
import plistlib
from PySide6.QtCore import QObject, Signal, QLocale

from .._meta import IS_MACOS, RESOURCES_DIR
from ..config import config_manager

_LANG_DIR = RESOURCES_DIR / "lang"
_MAC_PLIST_PATH = "~/Library/Preferences/.GlobalPreferences.plist"


class _SignalBus(QObject):
    changed = Signal(str)


class I18n:
    """Global i18n state & signal bus."""

    def __init__(self) -> None:
        self._bus = _SignalBus()
        self.changed = self._bus.changed
        self._strings = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LANG_DIR.iterdir() if p.is_file() and p.suffix == ".json"}
        self._system = self._detect()
        self._current = config_manager.get("language")

    def _detect(self) -> str:
        """Detect system locale. macOS plist first, then QLocale."""
        if IS_MACOS:
            path = os.path.expanduser(_MAC_PLIST_PATH)
            with open(path, "rb") as f:
                plist = plistlib.load(f)
            loc = plist.get("AppleLocale", "").replace("-", "_")
            if loc in self._strings:
                return loc

        loc = QLocale.system().name().replace("-", "_")
        return loc if loc in self._strings else "en_US"

    def _effective(self, raw: str) -> str:
        return self._system if raw == "auto" else raw

    def set(self, locale: str) -> None:
        if locale not in self._strings and locale != "auto":
            raise ValueError(f"Unsupported locale: {locale!r}. Available: {list(self._strings)}")
        self._current = locale
        self.changed.emit(locale)
        config_manager.set("language", locale)

    @property
    def current(self) -> str:
        return self._current

    def tr(self, key: str, **kwargs) -> str:
        loc = self._effective(self._current)
        text = self._strings.get(loc, {}).get(key)
        if text is None:
            text = self._strings.get("en_US", {}).get(key, key)
        return text.format_map(kwargs) if kwargs else text

    def available(self) -> list[tuple[str, str]]:
        keys = ["auto"] + sorted(self._strings)
        return [(k, self.tr(f"lang.{k}")) for k in keys]


_i18n = I18n()
language_changed = _i18n.changed


def set_language(locale: str) -> None:
    _i18n.set(locale)


def current_language() -> str:
    return _i18n.current


def tr(key: str, **kwargs) -> str:
    return _i18n.tr(key, **kwargs)


def available_languages() -> list[tuple[str, str]]:
    return _i18n.available()
