import json
from PySide6.QtCore import QObject, Signal

from .._meta import RESOURCES_DIR
from ..config import config_manager

_STRINGS: dict[str, dict[str, str]] = {}
_LANG_DIR = RESOURCES_DIR / "lang"


def _load_strings() -> None:
    """Dynamically load all language files from lang/ folder."""
    global _STRINGS
    _STRINGS = {}
    for path in _LANG_DIR.iterdir():
        if path.is_file() and path.suffix == ".json":
            locale = path.stem
            with path.open(encoding="utf-8") as f:
                _STRINGS[locale] = json.load(f)


_load_strings()


class _I18nBus(QObject):
    """Global singleton that emits language-switch signals."""

    changed = Signal(str)


_bus = _I18nBus()
language_changed = _bus.changed

_current_locale: str = config_manager.get("language", "zh_CN")


def set_language(locale: str) -> None:
    """Hot-switch the language, emitting language_changed to all subscribers."""
    global _current_locale
    if locale not in _STRINGS:
        raise ValueError(f"Unsupported locale: {locale!r}. Available: {list(_STRINGS)}")
    _current_locale = locale
    _bus.changed.emit(locale)
    config_manager.set("language", _current_locale)


def current_language() -> str:
    return _current_locale


def tr(key: str, **kwargs) -> str:
    """Translate a string key.

    Supports Python str.format_map-style placeholders:
        tr("tool.coming_soon", name="JSON Formatter")
    """
    table = _STRINGS.get(_current_locale, _STRINGS.get("zh_CN", {}))
    text = table.get(key) or _STRINGS.get("zh_CN", {}).get(key, key)
    return text.format_map(kwargs) if kwargs else text


def available_languages() -> list[tuple[str, str]]:
    """Return [(locale_key, display_name), ...]; display_name is always from the current language table."""
    keys = ["zh_CN", "en_US", "ja_JP"]
    return [(k, tr(f"lang.{k}")) for k in keys if k in _STRINGS]
