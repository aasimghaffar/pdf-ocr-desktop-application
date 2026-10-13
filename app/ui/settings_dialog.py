from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..config import DEFAULT_MODEL, SUGGESTED_MODELS, Settings, get_api_key, set_api_key
from ..gemini_ocr import list_models, test_api_key
from ..pdf_builder import MODE_OVERLAY, MODE_TEXT

OUTPUT_MODES = [
    ("Plain text (only the text of each page)", MODE_TEXT),
    ("Searchable scan (keep the original look)", MODE_OVERLAY),
]


class _Busy:
    def __enter__(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def __exit__(self, *exc):
        QApplication.restoreOverrideCursor()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self.settings = settings

        self.key_edit = QLineEdit(get_api_key())
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste your Gemini API key")
        show_btn = QPushButton("Show")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self._toggle_key)
        test_btn = QPushButton("Test key")
        test_btn.clicked.connect(self._test_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(show_btn)
        key_row.addWidget(test_btn)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.addItems(SUGGESTED_MODELS)
        self.model_combo.setCurrentText(settings.model)
        refresh_btn = QPushButton("Refresh list")
        refresh_btn.setToolTip("Load the models available to this API key")
        refresh_btn.clicked.connect(self._refresh_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self.model_combo, 1)
        model_row.addWidget(refresh_btn)

        self.mode_combo = QComboBox()
        for label, mode in OUTPUT_MODES:
            self.mode_combo.addItem(label, mode)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(settings.output_mode)))
        self.mode_combo.setToolTip(
            "Plain text: a new PDF with just the extracted text as plain lines, one page per scanned page.\n"
            "Searchable scan: keeps the scanned images and adds invisible, searchable text."
        )

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(100, 400)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(settings.dpi)
        self.dpi_spin.setToolTip("Resolution used when sending pages to Gemini. Higher = better on small text, slower.")

        self.overwrite_check = QCheckBox("Overwrite PDFs that already exist in the output folder")
        self.overwrite_check.setChecked(settings.overwrite)

        form = QFormLayout()
        form.addRow("Gemini API key:", key_row)
        form.addRow("Model:", model_row)
        form.addRow("Output PDF:", self.mode_combo)
        form.addRow("Page render DPI:", self.dpi_spin)
        form.addRow("", self.overwrite_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _toggle_key(self, show: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if show else QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(mode)

    def _require_key(self) -> str | None:
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "API key", "Enter an API key first.")
            return None
        return key

    def _test_key(self) -> None:
        key = self._require_key()
        if not key:
            return
        try:
            with _Busy():
                reply = test_api_key(key, self.model_combo.currentText().strip())
        except Exception as e:
            QMessageBox.critical(self, "API key", f"The key did not work:\n\n{e}")
            return
        QMessageBox.information(self, "API key", f"The key works. Gemini replied: {reply!r}")

    def _refresh_models(self) -> None:
        key = self._require_key()
        if not key:
            return
        try:
            with _Busy():
                models = list_models(key)
        except Exception as e:
            QMessageBox.critical(self, "Models", f"Could not load models:\n\n{e}")
            return
        current = self.model_combo.currentText()
        self.model_combo.clear()
        self.model_combo.addItems(models or SUGGESTED_MODELS)
        if models and current not in models:
            current = DEFAULT_MODEL if DEFAULT_MODEL in models else models[0]
        self.model_combo.setCurrentText(current)

    def accept(self) -> None:
        try:
            set_api_key(self.key_edit.text())
        except Exception as e:
            QMessageBox.critical(self, "API key", f"Could not save the API key:\n\n{e}")
            return
        self.settings.model = self.model_combo.currentText().strip() or DEFAULT_MODEL
        self.settings.output_mode = self.mode_combo.currentData()
        self.settings.dpi = self.dpi_spin.value()
        self.settings.overwrite = self.overwrite_check.isChecked()
        self.settings.save()
        super().accept()
