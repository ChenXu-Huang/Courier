"""Global hotkey manager using ``pynput``.

Emits a Qt signal on hotkey press. The signal is delivered in the Qt
main thread via the event loop, making it safe to connect directly to
GUI slots.
"""

from pynput.keyboard import Key, KeyCode, Listener
from PySide6.QtCore import QObject, Signal

from ..config import config_manager
from ..logger import get_logger

logger = get_logger(__name__)


class Hotkey:
    """Parsed hotkey with validation and active-state checking."""

    _KEY_MAP: dict[str, Key | KeyCode] = {
        "shift": Key.shift, "shift_l": Key.shift, "shift_r": Key.shift,
        "ctrl": Key.ctrl, "control": Key.ctrl, "ctrl_l": Key.ctrl, "ctrl_r": Key.ctrl,
        "alt": Key.alt, "alt_l": Key.alt, "alt_r": Key.alt,
        "cmd": Key.cmd, "command": Key.cmd, "win": Key.cmd, "super": Key.cmd, "meta": Key.cmd,
        "caps lock": Key.caps_lock, "esc": Key.esc, "escape": Key.esc,
        "space": Key.space, "enter": Key.enter, "tab": Key.tab, "backspace": Key.backspace,
        "delete": Key.delete, "home": Key.home,
        "end": Key.end, "page up": Key.page_up, "page down": Key.page_down,
        "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    }  # fmt: skip

    _MODIFIERS: dict[Key, tuple[Key, ...]] = {
        Key.shift: (Key.shift_l, Key.shift_r),
        Key.ctrl: (Key.ctrl_l, Key.ctrl_r),
        Key.alt: (Key.alt_l, Key.alt_r),
        Key.cmd: (Key.cmd_l, Key.cmd_r),
    }

    def __init__(self, hotkey_str: str) -> None:
        self._str = hotkey_str
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        self._keys: set[Key | KeyCode] = set()

        for part in parts:
            key = self._resolve(part)
            if key is None:
                logger.warning("Unknown key in hotkey %r: %r", hotkey_str, part)
            else:
                self._keys.add(key)

        if not self._keys:
            logger.warning("Parsed empty key set from hotkey %r", hotkey_str)

    def __str__(self) -> str:
        return self._str

    @classmethod
    def validate(cls, hotkey_str: str) -> bool:
        """Return whether *hotkey_str* is fully recognised."""
        if not hotkey_str or not hotkey_str.strip():
            return False
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        return all(parts) and all(cls._resolve(p) is not None for p in parts)

    def is_active(self, pressed: set[Key | KeyCode]) -> bool:
        """Check whether every key in this hotkey is currently pressed."""
        for target in self._keys:
            if target in pressed:
                continue
            family = self._MODIFIERS.get(target)
            if family and any(m in pressed for m in family):
                continue
            if isinstance(target, KeyCode) and target.char and target.char.isalpha():
                if KeyCode.from_char(target.char.upper()) in pressed:
                    continue
                if KeyCode.from_char(target.char.lower()) in pressed:
                    continue
            return False
        return True

    @classmethod
    def _resolve(cls, part: str) -> Key | KeyCode | None:
        """Map a single lower-cased hotkey part to a pynput key."""
        if part in cls._KEY_MAP:
            return cls._KEY_MAP[part]
        if len(part) == 1:
            return KeyCode.from_char(part)
        if part.startswith("f") and part[1:].isdigit():
            n = int(part[1:])
            if 1 <= n <= 24:
                return getattr(Key, f"f{n}", None)
        return None


class CourierHotkeyManager(QObject):
    """Registers a system-wide hotkey via ``pynput`` and emits
    ``hotkey_triggered``.

    The hotkey string is read from *config_manager*; it defaults to
    ``"shift+caps lock"`` when the config key is absent.
    """

    hotkey_triggered = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hotkey = Hotkey(config_manager.get("global_hotkey", "shift+caps lock"))
        self._listener: Listener | None = None
        self._pressed: set[Key | KeyCode] = set()
        self._fired = False
        self._unwatch = config_manager.on_change("global_hotkey", self._on_hotkey_changed)

    @property
    def hotkey(self) -> str:
        return str(self._hotkey)

    def start(self) -> None:
        """Register the global hotkey."""
        if self._listener is not None and self._listener.running:
            return
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
            suppress=False,
        )
        self._listener.start()
        logger.info("Global hotkey listener started: %r", self._hotkey)

    def cleanup(self) -> None:
        """Unregister config callback and stop the listener."""
        self._unwatch()
        self.stop()

    def stop(self) -> None:
        """Unregister the global hotkey."""
        if self._listener is None:
            return
        try:
            self._listener.stop()
        except Exception:
            pass
        self._listener = None
        self._pressed.clear()

    def _on_hotkey_changed(self, path: str, old: str, new: str) -> None:
        """Update the hotkey object. Listener restart is managed externally
        (by the settings-close handler) since pynput's macOS Listener
        cannot be safely stopped and restarted."""
        self._hotkey = Hotkey(config_manager.get("global_hotkey", "shift+caps lock"))
        logger.info("Hotkey updated: %r", self._hotkey)

    def _on_press(self, key: Key | KeyCode | None) -> None:
        """Called from the pynput listener thread on each key press."""
        if key is None:
            return
        self._pressed.add(key)
        if not self._fired and self._hotkey.is_active(self._pressed):
            self._fired = True
            self.hotkey_triggered.emit()

    def _on_release(self, key: Key | KeyCode | None) -> None:
        """Called from the pynput listener thread on each key release."""
        if key is None:
            return
        self._pressed.discard(key)
        if self._fired and not self._hotkey.is_active(self._pressed):
            self._fired = False
