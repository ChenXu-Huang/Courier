"""Settings dialog — configure all Courier preferences."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Generic, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QMessageBox, QSpinBox,
    QVBoxLayout, QWidget,
)  # fmt: skip

from ..config import config_manager
from ..logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Field descriptor
# ---------------------------------------------------------------------------

W = TypeVar("W", bound=QWidget)


@dataclass(frozen=True)
class FieldSpec(Generic[W]):
    """Describes one settings field: label, widget factory, getter/setter,
    and optional validator.
    """

    key: str
    label: str
    make: Callable[[], W]
    get: Callable[[W], Any]
    set: Callable[[W, Any], None]
    validate: Callable[[W], str | None] = lambda _: None

    def with_validate(self, validator: Callable[[W], str | None]) -> FieldSpec[W]:
        """Return a new ``FieldSpec`` with a different validator."""
        return replace(self, validate=validator)

    @staticmethod
    def int_spin(key: str, label: str, lo: int, hi: int, step: int = 1) -> FieldSpec[QSpinBox]:
        def make() -> QSpinBox:
            w = QSpinBox()
            w.setRange(lo, hi)
            w.setSingleStep(step)
            return w
        return FieldSpec(
            key=key, label=label, make=make,
            get=lambda w: w.value(),
            set=lambda w, v: w.setValue(int(v) if v is not None else w.minimum()),
        )

    @staticmethod
    def float_spin(key: str, label: str, lo: float, hi: float, step: float, decimals: int) -> FieldSpec[QDoubleSpinBox]:
        def make() -> QDoubleSpinBox:
            w = QDoubleSpinBox()
            w.setRange(lo, hi)
            w.setSingleStep(step)
            w.setDecimals(decimals)
            return w
        return FieldSpec(
            key=key, label=label, make=make,
            get=lambda w: w.value(),
            set=lambda w, v: w.setValue(float(v) if v is not None else w.minimum()),
        )

    @staticmethod
    def combo(key: str, label: str, *items: tuple[str, str]) -> FieldSpec[QComboBox]:
        def make() -> QComboBox:
            w = QComboBox()
            for text, data in items:
                w.addItem(text, data)
            return w
        return FieldSpec(
            key=key, label=label, make=make,
            get=lambda w: w.currentData(),
            set=lambda w, v: w.setCurrentIndex(i if (i := w.findData(v)) >= 0 else 0),
        )

    @staticmethod
    def text(key: str, label: str, placeholder: str = "") -> FieldSpec[QLineEdit]:
        def make() -> QLineEdit:
            w = QLineEdit()
            if placeholder:
                w.setPlaceholderText(placeholder)
            return w
        return FieldSpec(
            key=key, label=label, make=make,
            get=lambda w: w.text().strip(),
            set=lambda w, v: w.setText(str(v) if v is not None else ""),
        )


_FIELDS: list[FieldSpec[Any]] = [
    FieldSpec.int_spin("window_size", "Window Size (px)", 200, 600, 10),
    FieldSpec.float_spin("window_opacity", "Window Opacity", 0.1, 1.0, 0.05, 2),
    FieldSpec.int_spin("window_radius", "Corner Radius (px)", 0, 50),
    FieldSpec.combo(
        "after_drop_action", "After Drop",
        ("Close window", "close"),
        ("Clear basket", "clear"),
        ("Keep items", "keep"),
    ),
    FieldSpec.combo(
        "default_transfer_mode", "Transfer Mode",
        ("Copy", "copy"),
        ("Move", "move"),
    ),
    FieldSpec.text("global_hotkey", "Global Hotkey",
        placeholder="e.g. ctrl+shift+caps lock",
    ).with_validate(lambda w: "The hotkey cannot be empty" if not w.text().strip() else None),
]


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class CourierSettingsDialog(QDialog):
    """Modal settings dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Courier Settings")
        self.setMinimumWidth(360)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 0, 0)

        self._widgets = {spec.key: (spec, spec.make()) for spec in _FIELDS}
        for spec, widget in self._widgets.values():
            form.addRow(f"{spec.label}:", widget)

        layout.addLayout(form)
        layout.addSpacing(12)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _load_values(self) -> None:
        for spec, widget in self._widgets.values():
            spec.set(widget, config_manager.get(spec.key))

    def _on_accept(self) -> None:
        errors = [
            f"{spec.label}: {msg}"
            for spec, widget in self._widgets.values()
            if (msg := spec.validate(widget)) is not None
        ]
        if errors:
            QMessageBox.warning(self, "Invalid Settings", "\n".join(errors))
            return

        for spec, widget in self._widgets.values():
            config_manager.set(spec.key, spec.get(widget))
        logger.info("Settings saved")
        self.accept()
