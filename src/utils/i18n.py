import json
import locale
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
            loc = path.stem
            with path.open(encoding="utf-8") as f:
                _STRINGS[loc] = json.load(f)


_load_strings()


class _I18nBus(QObject):
    """Global singleton that emits language-switch signals."""

    changed = Signal(str)


_bus = _I18nBus()
language_changed = _bus.changed

_current_locale: str = config_manager.get("language", "auto")


def _resolve_locale(raw: str) -> str:
    """If *raw* is ``"auto"``, detect from system; otherwise return as-is.

    Falls back to ``"en_US"`` when the detected system locale has no
    translation table.
    """
    if raw != "auto":
        return raw
    try:
        sys_lang, _ = locale.getdefaultlocale()
        if sys_lang:
            lang = sys_lang.split(".")[0].replace("-", "_")
            if lang in _STRINGS:
                return lang
    except Exception:
        pass
    return "en_US"


def set_language(locale: str) -> None:
    """Hot-switch the language, emitting language_changed to all subscribers."""
    global _current_locale
    if locale not in _STRINGS and locale != "auto":
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
    effective = _resolve_locale(_current_locale)
    table = _STRINGS.get(effective, _STRINGS.get("en_US", {}))
    text = table.get(key) or _STRINGS.get("en_US", {}).get(key, key)
    return text.format_map(kwargs) if kwargs else text


def available_languages() -> list[tuple[str, str]]:
    """Return [(locale_key, display_name), ...]; display_name is always from the current language table."""
    keys = ["zh_CN", "en_US", "ja_JP"]
    items = [(k, tr(f"lang.{k}")) for k in keys if k in _STRINGS]
    items.insert(0, ("auto", tr("lang.auto")))
    return items
