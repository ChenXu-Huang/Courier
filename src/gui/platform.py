"""Platform-specific window operations — macOS, Windows, DPI."""

import ctypes
from ctypes import c_bool, c_char_p, c_int, c_long, c_void_p, c_ulong
from PySide6.QtWidgets import QApplication

from typing import TYPE_CHECKING

from .._meta import IS_MACOS, IS_WINDOWS
from ..logger import get_logger

logger = get_logger(__name__)


class PlatformCompatMixin:
    """Mixin providing platform-specific window enhancements and DPI utilities."""

    if TYPE_CHECKING:
        # Stub for mypy — at runtime winId() is inherited from QWidget
        def winId(self) -> int: ...

    def apply_platform_hacks(self) -> None:
        """Apply macOS topmost and Windows 11 DWM hacks. Call inside showEvent()."""
        if IS_MACOS and not getattr(self, "_macos_level_set", False):
            if self._enforce_macos_topmost():
                self._macos_level_set = True
        elif IS_WINDOWS and not getattr(self, "_dwm_rounding_suppressed", False):
            if self._suppress_dwm_rounding():
                self._dwm_rounding_suppressed = True

    def _enforce_macos_topmost(self) -> bool:
        """Float the window above all others via the Objective-C runtime."""
        try:
            objc = ctypes.CDLL("/usr/lib/libobjc.dylib")
            objc.sel_registerName.restype = c_void_p
            objc.sel_registerName.argtypes = [c_char_p]
            objc.objc_getClass.restype = c_void_p
            objc.objc_getClass.argtypes = [c_char_p]
            objc.class_getInstanceMethod.restype = c_void_p
            objc.class_getInstanceMethod.argtypes = [c_void_p, c_void_p]
            objc.method_getImplementation.restype = c_void_p
            objc.method_getImplementation.argtypes = [c_void_p]

            # self MUST have a winId() method (e.g., inheriting from QWidget)
            view = c_void_p(int(self.winId()))
            ns_view_cls = objc.objc_getClass(b"NSView")
            ns_window_cls = objc.objc_getClass(b"NSWindow")

            sel_window = objc.sel_registerName(b"window")
            imp_window = objc.method_getImplementation(objc.class_getInstanceMethod(ns_view_cls, sel_window))
            get_window = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_void_p)(imp_window)
            ns_window = get_window(view, sel_window)
            if not ns_window:
                logger.warning("Failed to obtain NSWindow via ctypes")
                return False

            sel_level = objc.sel_registerName(b"setLevel:")
            imp_level = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_level))
            set_level = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_long)(imp_level)
            set_level(ns_window, sel_level, 3)

            sel_hides = objc.sel_registerName(b"setHidesOnDeactivate:")
            imp_hides = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_hides))
            set_hides = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_bool)(imp_hides)
            set_hides(ns_window, sel_hides, False)

            sel_behavior = objc.sel_registerName(b"setCollectionBehavior:")
            imp_behavior = objc.method_getImplementation(objc.class_getInstanceMethod(ns_window_cls, sel_behavior))
            set_behavior = ctypes.CFUNCTYPE(None, c_void_p, c_void_p, c_ulong)(imp_behavior)
            set_behavior(ns_window, sel_behavior, 1 | 256 | 1024)

            logger.debug("macOS topmost and multi-space behavior enforced via IMP (safe path)")
            return True
        except Exception as exc:
            logger.warning("macOS topmost ctypes failed: %s", exc)
            return False

    def _suppress_dwm_rounding(self) -> bool:
        """Disable Windows 11 DWM automatic corner rounding for this window."""
        _DWMWA_WINDOW_CORNER_PREFERENCE = 33
        _DWMWCP_DONOTROUND = 1

        try:
            hwnd = c_void_p(int(self.winId()))
            preference = c_int(_DWMWCP_DONOTROUND)
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                hwnd,
                _DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
            if result != 0:
                logger.debug(
                    "DWM corner suppression returned HRESULT=0x%08X",
                    result & 0xFFFFFFFF,
                )
                return False
            logger.debug("DWM automatic corner rounding suppressed")
            return True
        except Exception as exc:
            logger.warning("DwmSetWindowAttribute failed: %s", exc)
            return False

    @property
    def font_scale(self) -> float:
        """DPI-aware font scale factor, platform-adjusted."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return 1.0

        dpi = screen.logicalDotsPerInch()
        # Note: IS_MACOS and IS_WINDOWS check is still safe here
        if IS_MACOS:
            return max(1.0, min(3.0, (dpi / 72.0) * 1.2))
        return max(0.8, min(3.0, dpi / 96.0))
