import json
import os
from PySide6.QtCore import QObject, Signal

from .._meta import RESOURCES_DIR
from ..config import config_manager

_LANG_DIR = RESOURCES_DIR / "lang"


class I18n(QObject):
    """Global i18n state & signal bus."""

    changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._strings = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LANG_DIR.iterdir() if p.is_file() and p.suffix == ".json"}
        self._system = self._detect()
        self._current = config_manager.get("language", "auto")

    def _detect(self) -> str:
        """Detect system locale from env; skip C/POSIX."""
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            val = os.environ.get(var, "")
            if not val:
                continue
            base = val.split(".")[0]
            if base == "C":  # 同时拦住 C、C.UTF-8 等
                continue
            loc = base.replace("-", "_")
            if loc in self._strings:
                return loc
        return "en_US"

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
        # 用 None 判断替代 or，避免空字符串误 fallback
        text = self._strings.get(loc, {}).get(key)
        if text is None:
            text = self._strings.get("en_US", {}).get(key, key)
        return text.format_map(kwargs) if kwargs else text

    def available(self) -> list[tuple[str, str]]:
        # 保留你想要的顺序，但自动包含 lang/ 目录里新增的其他语言
        preferred = [k for k in ("zh_CN", "en_US", "ja_JP") if k in self._strings]
        other = sorted(k for k in self._strings if k not in preferred)
        keys = ["auto"] + preferred + other
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
