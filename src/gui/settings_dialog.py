"""Settings dialog — configure all Courier preferences."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Generic, TypeVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLineEdit, QMessageBox, QSpinBox,
    QVBoxLayout, QWidget, QCheckBox, 
)  # fmt: skip

from ..config import config_manager
from ..logger import get_logger
from ..utils import Hotkey, tr, available_languages, current_language, set_language

logger = get_logger(__name__)
W = TypeVar("W", bound=QWidget)


@dataclass(frozen=True)
class FieldSpec(Generic[W]):
    """Describes one settings field: label, widget factory, getter/setter,
    and optional validator, and (for combo fields) i18n keys for each item.
    """

    key: str
    label: str
    make: Callable[[], W]
    get: Callable[[W], Any]
    set: Callable[[W, Any], None]
    validate: Callable[[W], str | None] = lambda _: None
    item_keys: tuple[str, ...] = field(default_factory=tuple)

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
        i18n_keys = tuple(i18n_key for i18n_key, _ in items)
        data_values = [(i18n_key, data) for i18n_key, data in items]
        def make() -> QComboBox:
            w = QComboBox()
            for i18n_key, data in data_values:
                w.addItem("", data)
            return w
        return FieldSpec(
            key=key, label=label, make=make,
            get=lambda w: w.currentData(),
            set=lambda w, v: w.setCurrentIndex(i if (i := w.findData(v)) >= 0 else 0),
            item_keys=i18n_keys,
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

    @staticmethod
    def checkbox(key: str, label: str) -> FieldSpec[QCheckBox]:
        return FieldSpec(
            key=key, label=label, make=QCheckBox,
            get=lambda w: w.isChecked(),
            set=lambda w, v: w.setChecked(bool(v) if v is not None else False),
        )


def _validate_hotkey(w: QLineEdit) -> str | None:
    raw = w.text().strip()
    if not raw:
        return tr("settings.validate_hotkey_empty")
    if not Hotkey.validate(raw):
        return tr("settings.validate_hotkey_invalid")
    return None


_FIELDS: list[FieldSpec[Any]] = [
    FieldSpec.checkbox("show_on_startup", "settings.show_on_startup"),
    FieldSpec.combo(
        "theme_mode", "settings.theme_mode",
        ("settings.theme_mode.auto", "auto"),
        ("settings.theme_mode.dark", "dark"),
        ("settings.theme_mode.light", "light"),
    ),
    FieldSpec.int_spin("window_size", "settings.window_size", 200, 600, 10),
    FieldSpec.float_spin("window_opacity", "settings.window_opacity", 0.1, 1.0, 0.05, 2),
    FieldSpec.int_spin("window_radius", "settings.corner_radius", 0, 50),
    FieldSpec.combo(
        "after_drop_action", "settings.after_drop",
        ("settings.after_drop.close", "close"),
        ("settings.after_drop.clear", "clear"),
        ("settings.after_drop.keep",  "keep"),
    ),
    FieldSpec.combo(
        "default_transfer_mode", "settings.transfer_mode",
        ("settings.transfer_mode.copy", "copy"),
        ("settings.transfer_mode.move", "move"),
    ),
    FieldSpec.text(
        "global_hotkey", "settings.global_hotkey",
        placeholder="",
    ).with_validate(_validate_hotkey),
]


class CourierSettingsDialog(QDialog):
    """Modal settings dialog."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title"))
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

        self._widgets: dict[str, tuple[FieldSpec[Any], QWidget]] = {
            spec.key: (spec, spec.make()) for spec in _FIELDS
        }
        for spec, widget in self._widgets.values():
            form.addRow(f"{tr(spec.label)}:", widget)
            self._apply_combo_translations(spec, widget)
            if isinstance(widget, QLineEdit) and spec.key == "global_hotkey":
                widget.setPlaceholderText(tr("settings.hotkey_placeholder"))

        layout.addLayout(form)

        # Language selection
        self._lang_combo = QComboBox()
        for locale, name in available_languages():
            self._lang_combo.addItem(name, locale)
        self._lang_combo.setCurrentIndex(self._lang_combo.findData(current_language()))
        form.addRow(f"{tr('settings.language')}:", self._lang_combo)

        layout.addSpacing(12)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    @staticmethod
    def _apply_combo_translations(spec: FieldSpec[Any], widget: QWidget) -> None:
        if not isinstance(widget, QComboBox) or not spec.item_keys:
            return
        for i, key in enumerate(spec.item_keys):
            widget.setItemText(i, tr(key))

    def _load_values(self) -> None:
        for spec, widget in self._widgets.values():
            spec.set(widget, config_manager.get(spec.key))

    def _on_accept(self) -> None:
        errors = [
            f"{tr(spec.label)}: {msg}"
            for spec, widget in self._widgets.values()
            if (msg := spec.validate(widget)) is not None
        ]
        if errors:
            QMessageBox.warning(self, tr("settings.invalid_title"), "\n".join(errors))
            return

        try:
            for spec, widget in self._widgets.values():
                config_manager.set(spec.key, spec.get(widget))
            logger.info("Settings saved")

            new_lang = self._lang_combo.currentData()
            if new_lang != current_language():
                set_language(new_lang)

            self.accept()
        except BaseException:
            logger.exception("Failed to save settings")
            QMessageBox.critical(self, "Error", "Failed to save settings")
