"""Global hotkey manager using the ``keyboard`` library.

Emits a Qt signal on hotkey press. The signal is delivered in the Qt
main thread via the event loop, making it safe to connect directly to
GUI slots.
"""

import keyboard
from PySide6.QtCore import QObject, Signal

from ..config import config_manager
from ..logger import get_logger

logger = get_logger(__name__)


class CourierHotkeyManager(QObject):
    """Registers a system-wide hotkey and emits ``hotkey_triggered``.

    The hotkey string is read from *config_manager*; it defaults to
    ``"shift+caps lock"`` when the config key is absent.
    """

    hotkey_triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = config_manager.get("global_hotkey", "shift+caps lock")
        self._registered = False

    @property
    def hotkey(self) -> str:
        return self._hotkey

    def start(self) -> None:
        """Register the global hotkey."""
        if self._registered:
            return
        try:
            keyboard.add_hotkey(self._hotkey, self._on_hotkey, suppress=True)
            self._registered = True
        except Exception:
            logger.error("Failed to register hotkey %r", self._hotkey)

    def stop(self) -> None:
        """Unregister the global hotkey."""
        if not self._registered:
            return
        try:
            keyboard.remove_hotkey(self._hotkey)
        except Exception:
            pass
        self._registered = False

    def _on_hotkey(self) -> None:
        """Called from the keyboard listener thread — emit signal to main thread."""
        self.hotkey_triggered.emit()
