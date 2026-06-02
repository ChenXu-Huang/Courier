"""Thumbnail loading, caching, and on-painter drawing."""

import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QFileInfo, QSize, Qt, QPointF
from PySide6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFileIconProvider

from ..logger import get_logger

logger = get_logger(__name__)


class _LRUCache(OrderedDict):
    """A true LRU cache implemented based on OrderedDict."""

    def __init__(self, maxsize: int) -> None:
        super().__init__()
        self.maxsize = maxsize

    def get_item(self, key: Any) -> Any | None:
        if key in self:
            self.move_to_end(key)
            return self[key]
        return None

    def put_item(self, key: Any, value: Any) -> None:
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > self.maxsize:
            self.popitem(last=False)


class ThumbnailProvider:
    """Encapsulates thumbnail loading, caching, and on-painter drawing (High-DPI Aware)."""

    _IMAGE_EXTS = frozenset({
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
        ".svg", ".ico", ".tiff", ".tif", ".avif",
    })  # fmt: skip
    _VIDEO_EXTS = frozenset({
        ".mp4", ".mkv", ".webm", ".avi", ".mov",
        ".m4v", ".flv", ".wmv", ".mpg", ".mpeg",
    })  # fmt: skip
    _SHORTCUT_EXTS = frozenset({".lnk", ".url", ".exe"})  # fmt: skip

    def __init__(self, cache_max: int = 256, ffmpeg_path: str = "ffmpeg") -> None:
        self._ffmpeg_path = ffmpeg_path
        self._icon_provider = QFileIconProvider()
        self._type_cache = _LRUCache(maxsize=cache_max)
        self._cache = _LRUCache(maxsize=cache_max)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def draw(self, painter: QPainter, path: Path, x: float, y: float, size: float) -> None:
        """Draw file thumbnail: image content, video frame, or system icon fallback."""
        try:
            dpr = painter.device().devicePixelRatioF()
            icon_size = int(size * 0.8)
            suffix = path.suffix.lower()

            if suffix in self._IMAGE_EXTS:
                pix = self._load_image(path, icon_size, dpr)
            elif suffix in self._VIDEO_EXTS:
                pix = self._load_video(path, icon_size, dpr)
            elif suffix not in self._SHORTCUT_EXTS:
                pix = self._load_type_icon(path, icon_size, dpr)
            else:
                pix = None

            if pix is None or pix.isNull():
                icon = self._icon_provider.icon(QFileInfo(str(path)))
                pix = icon.pixmap(QSize(icon_size, icon_size))
                if not pix.isNull():
                    pix.setDevicePixelRatio(dpr)

            if pix is not None and not pix.isNull():
                # Ensure pixmap fits within icon_size at the correct DPR
                physical_target = int(icon_size * dpr)
                if pix.size() != QSize(physical_target, physical_target) or pix.devicePixelRatio() != dpr:
                    pix = pix.scaled(
                        physical_target, physical_target,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    pix.setDevicePixelRatio(dpr)

                pix_dpr = pix.devicePixelRatio()
                logical_w = pix.width() / pix_dpr
                logical_h = pix.height() / pix_dpr
                dx = int(x + (size - logical_w) / 2)
                dy = int(y + (size - logical_h) / 2)
                painter.drawPixmap(dx, dy, pix)
                if suffix in self._VIDEO_EXTS:
                    self._draw_play_overlay(painter, x, y, size)
        except Exception as e:
            logger.error("Error drawing thumbnail for %s: %s", path, e)

    def clear_cache(self) -> None:
        self._cache.clear()
        self._type_cache.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(path: Path, size: int, dpr: float) -> tuple[str, int, int, float]:
        return (str(path), path.stat().st_mtime_ns, size, dpr)

    def _load_image(self, path: Path, size: int, dpr: float) -> QPixmap | None:
        """Load actual image content scaled to fit *size*, with EXIF orientation."""
        cache_key = self._cache_key(path, size, dpr)
        cached = self._cache.get_item(cache_key)
        if cached is not None:
            return cached

        try:
            physical_size = int(size * dpr)
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)

            orig_size = reader.size()
            reader.setScaledSize(
                orig_size.scaled(physical_size, physical_size, Qt.AspectRatioMode.KeepAspectRatio)
                if orig_size.isValid()
                else QSize(physical_size, physical_size)
            )

            img = reader.read()
            if img.isNull():
                return None

            pix = QPixmap.fromImage(img)
            pix.setDevicePixelRatio(dpr)

            self._cache.put_item(cache_key, pix)
            return pix
        except Exception as e:
            logger.error("Failed to load image %s: %s", path, e)
            return None

    def _load_video(self, path: Path, size: int, dpr: float) -> QPixmap | None:
        """Extract a video frame via ffmpeg and return a scaled pixmap."""
        cache_key = self._cache_key(path, size, dpr)
        cached = self._cache.get_item(cache_key)
        if cached is not None:
            return cached

        try:
            proc = subprocess.run(
                [self._ffmpeg_path, "-ss", "1", "-i", str(path), "-vframes", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True,
                timeout=15,
            )
            if proc.returncode != 0 or not proc.stdout:
                return None

            pix = QPixmap()
            if not pix.loadFromData(proc.stdout):
                return None

            physical_size = int(size * dpr)
            scaled = pix.scaled(physical_size, physical_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)

            self._cache.put_item(cache_key, scaled)
            return scaled
        except Exception as e:
            logger.error("Failed to extract video frame for %s: %s", path, e)
            return None

    def _load_type_icon(self, path: Path, size: int, dpr: float) -> QPixmap | None:
        """Load system icon for non-image/non-video files..."""
        type_key = str(path) if path.is_dir() else (path.suffix.lower() or "__file__")
        cache_key = (type_key, size, dpr)

        cached = self._type_cache.get_item(cache_key)
        if cached is not None:
            return cached

        icon = self._icon_provider.icon(QFileInfo(str(path)))
        pix = icon.pixmap(QSize(size, size))
        if pix.isNull():
            return None

        pix.setDevicePixelRatio(dpr)
        self._type_cache.put_item(cache_key, pix)
        return pix

    @staticmethod
    def _draw_play_overlay(painter: QPainter, x: float, y: float, size: float) -> None:
        """Small semi-transparent play triangle for video thumbnails."""
        cx = x + size / 2
        cy = y + size / 2
        r = size * 0.1

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(QColor(255, 255, 255, 220))
        path = QPainterPath()
        s = r * 0.55
        path.moveTo(cx - s * 0.6, cy - s)
        path.lineTo(cx + s, cy)
        path.lineTo(cx - s * 0.6, cy + s)
        path.closeSubpath()
        painter.drawPath(path)
        painter.restore()
