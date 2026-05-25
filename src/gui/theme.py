"""Unified theme manager — centralized QSS and color palette for all GUI widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from .._meta import RESOURCES_DIR
from ..config import config_manager

_RGBA = Tuple[int, int, int, int]

# -- SVG icon templates (stroke=currentColor gets replaced per theme) -----------

_ICONS_DIR = RESOURCES_DIR / "icons"


def _read_svg(name: str) -> str:
    return (_ICONS_DIR / name).read_text(encoding="utf-8")


_SVG_CLOSE = _read_svg("close.svg")
_SVG_MENU = _read_svg("menu.svg")
_SVG_CHEVRON_DOWN = _read_svg("chevron-down.svg")
_SVG_CHEVRON_UP = _read_svg("chevron-up.svg")


@dataclass(frozen=True)
class ThemePalette:
    """Immutable color palette for one theme (dark or light).

    All color values are RGBA tuples.  Use :meth:`window_stylesheet` and
    :meth:`menu_stylesheet` to generate QSS strings.
    """

    # Window (QPainter)
    window_bg: _RGBA
    window_border: _RGBA

    # Labels
    title_color: _RGBA
    empty_label_color: _RGBA
    file_label_color: _RGBA
    more_label_color: _RGBA

    # Overlay buttons (close, menu)
    overlay_btn_bg: _RGBA
    overlay_btn_color: _RGBA
    overlay_btn_hover_bg: _RGBA
    overlay_btn_hover_color: _RGBA

    # Footer pill button
    pill_btn_bg: _RGBA
    pill_btn_border: _RGBA
    pill_btn_color: _RGBA
    pill_btn_hover_bg: _RGBA
    pill_btn_hover_color: _RGBA

    # Context menu (QMenu)
    menu_bg: _RGBA
    menu_border: _RGBA
    menu_item_color: _RGBA
    menu_item_selected_bg: _RGBA
    menu_item_selected_color: _RGBA

    # Icon stroke (applied to theme-aware SVG icons)
    icon_stroke: _RGBA

    # -- helpers ----------------------------------------------------------------

    def _rgba(self, c: _RGBA) -> str:
        return f"rgba({c[0]},{c[1]},{c[2]},{c[3]})"

    def window_stylesheet(self) -> str:
        """Full QSS string for CourierBasketWindow and all its named children."""
        return f"""
            #courier-title {{
                color: {self._rgba(self.title_color)};
            }}
            #courier-empty-label {{
                color: {self._rgba(self.empty_label_color)};
            }}
            #courier-file-label {{
                color: {self._rgba(self.file_label_color)};
            }}
            #courier-more-label {{
                color: {self._rgba(self.more_label_color)};
            }}
            #courier-close-btn, #courier-menu-btn {{
                background: {self._rgba(self.overlay_btn_bg)};
                border: none;
                border-radius: 14px;
                color: {self._rgba(self.overlay_btn_color)};
            }}
            #courier-close-btn:hover, #courier-menu-btn:hover {{
                background: {self._rgba(self.overlay_btn_hover_bg)};
                color: {self._rgba(self.overlay_btn_hover_color)};
            }}
        """.strip()

    def menu_stylesheet(self, font_size: int) -> str:
        """QSS for the QMenu popup — font_size is dynamic (pt)."""
        return f"""
            QMenu {{
                background: {self._rgba(self.menu_bg)};
                border: 1px solid {self._rgba(self.menu_border)};
                border-radius: 8px;
                padding: 4px;
            }}
            QMenu::item {{
                color: {self._rgba(self.menu_item_color)};
                padding: 6px 20px;
                border-radius: 4px;
                font-size: {font_size}pt;
            }}
            QMenu::item:selected {{
                background: {self._rgba(self.menu_item_selected_bg)};
                color: {self._rgba(self.menu_item_selected_color)};
            }}
        """.strip()

    # -- factories --------------------------------------------------------------

    @staticmethod
    def dark() -> ThemePalette:
        return ThemePalette(
            window_bg=(30, 30, 40, 235),
            window_border=(255, 255, 255, 25),
            title_color=(255, 255, 255, 200),
            empty_label_color=(255, 255, 255, 80),
            file_label_color=(255, 255, 255, 180),
            more_label_color=(255, 255, 255, 100),
            overlay_btn_bg=(255, 255, 255, 30),
            overlay_btn_color=(255, 255, 255, 200),
            overlay_btn_hover_bg=(255, 255, 255, 60),
            overlay_btn_hover_color=(255, 255, 255, 255),
            pill_btn_bg=(255, 255, 255, 20),
            pill_btn_border=(255, 255, 255, 25),
            pill_btn_color=(255, 255, 255, 180),
            pill_btn_hover_bg=(255, 255, 255, 40),
            pill_btn_hover_color=(255, 255, 255, 255),
            menu_bg=(30, 30, 40, 235),
            menu_border=(255, 255, 255, 25),
            menu_item_color=(255, 255, 255, 180),
            menu_item_selected_bg=(255, 255, 255, 30),
            menu_item_selected_color=(255, 255, 255, 255),
            icon_stroke=(255, 255, 255, 255),
        )

    @staticmethod
    def light() -> ThemePalette:
        return ThemePalette(
            window_bg=(245, 245, 250, 240),
            window_border=(0, 0, 0, 25),
            title_color=(0, 0, 0, 200),
            empty_label_color=(0, 0, 0, 80),
            file_label_color=(0, 0, 0, 180),
            more_label_color=(0, 0, 0, 100),
            overlay_btn_bg=(0, 0, 0, 10),
            overlay_btn_color=(0, 0, 0, 180),
            overlay_btn_hover_bg=(0, 0, 0, 25),
            overlay_btn_hover_color=(0, 0, 0, 255),
            pill_btn_bg=(0, 0, 0, 8),
            pill_btn_border=(0, 0, 0, 15),
            pill_btn_color=(0, 0, 0, 180),
            pill_btn_hover_bg=(0, 0, 0, 20),
            pill_btn_hover_color=(0, 0, 0, 255),
            menu_bg=(245, 245, 250, 240),
            menu_border=(0, 0, 0, 25),
            menu_item_color=(0, 0, 0, 180),
            menu_item_selected_bg=(0, 0, 0, 15),
            menu_item_selected_color=(0, 0, 0, 255),
            icon_stroke=(0, 0, 0, 255),
        )


class ThemeManager(QObject):
    """Singleton theme controller driven by the ``theme_mode`` config key.

    Emits :attr:`theme_changed` whenever the effective theme (dark/light)
    actually changes, so connected widgets can re-apply stylesheets.
    """

    theme_changed = Signal(str)  # emits "dark" or "light"

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mode: str = config_manager.get("theme_mode")  # "auto" | "dark" | "light"
        self._effective: str = self._resolve_effective()
        self._palette: ThemePalette = self._build_palette()
        config_manager.on_change("theme_mode", self._on_config_changed)

    # -- public API ------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Raw config value: ``"auto"``, ``"dark"``, or ``"light"``."""
        return self._mode

    @property
    def effective(self) -> str:
        """Resolved theme — always ``"dark"`` or ``"light"``."""
        return self._effective

    @property
    def is_dark(self) -> bool:
        return self._effective == "dark"

    def bg_color(self) -> QColor:
        return QColor(*self._palette.window_bg)

    def border_color(self) -> QColor:
        return QColor(*self._palette.window_border)

    def window_stylesheet(self) -> str:
        return self._palette.window_stylesheet()

    def menu_stylesheet(self, font_size: int) -> str:
        return self._palette.menu_stylesheet(font_size)

    # -- Themed SVG icons (stroke colour from palette) ---------------------------

    @staticmethod
    def _make_icon(svg_template: str, stroke: _RGBA) -> QIcon:
        hex_color = f"#{stroke[0]:02X}{stroke[1]:02X}{stroke[2]:02X}"
        colored = svg_template.replace("currentColor", hex_color)
        data = QByteArray(colored.encode("utf-8"))
        renderer = QSvgRenderer(data)
        pixmap = QPixmap(24, 24)  # SVG viewBox="0 0 24 24"
        pixmap.fill(Qt.GlobalColor.transparent)
        with QPainter(pixmap) as p:
            renderer.render(p)
        return QIcon(pixmap)

    @property
    def close_icon(self) -> QIcon:
        return self._make_icon(_SVG_CLOSE, self._palette.icon_stroke)

    @property
    def menu_icon(self) -> QIcon:
        return self._make_icon(_SVG_MENU, self._palette.icon_stroke)

    @property
    def chevron_down_icon(self) -> QIcon:
        return self._make_icon(_SVG_CHEVRON_DOWN, self._palette.icon_stroke)

    @property
    def chevron_up_icon(self) -> QIcon:
        return self._make_icon(_SVG_CHEVRON_UP, self._palette.icon_stroke)

    def set_theme_mode(self, mode: str) -> None:
        """Persist ``theme_mode`` to config (fires change callback → refresh)."""
        if mode not in ("auto", "dark", "light"):
            raise ValueError(f"Invalid theme_mode: {mode!r}")
        config_manager.set("theme_mode", mode)

    def refresh(self) -> None:
        """Re-evaluate effective theme and rebuild palette if different."""
        new_effective = self._resolve_effective()
        if new_effective == self._effective:
            return
        self._effective = new_effective
        self._palette = self._build_palette()
        self.theme_changed.emit(self._effective)

    # -- internals -------------------------------------------------------------

    def _resolve_effective(self) -> str:
        mode = config_manager.get("theme_mode")
        if mode != "auto":
            return mode
        return self._detect_system_theme()

    @staticmethod
    def _detect_system_theme() -> str:
        """Detect system dark/light via QPalette."""
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return "dark"
        lightness = app.palette().color(QPalette.ColorRole.Window).lightness()
        return "dark" if lightness < 128 else "light"

    def _build_palette(self) -> ThemePalette:
        return ThemePalette.dark() if self._effective == "dark" else ThemePalette.light()

    def _on_config_changed(self, path: str, old: str, new: str) -> None:
        self._mode = new
        self.refresh()


# -- module-level singleton ----------------------------------------------------

_manager: ThemeManager | None = None


def get_theme_manager() -> ThemeManager:
    """Return the global ThemeManager singleton (lazy-initialised)."""
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


theme_manager = get_theme_manager()
