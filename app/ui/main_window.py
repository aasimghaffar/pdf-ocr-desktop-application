from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QCloseEvent, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings, get_api_key
from ..watcher import FolderWatcher, list_pdfs
from ..worker import JobConfig, Processor
from .settings_dialog import SettingsDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scanned PDF OCR (Gemini)")
        self.resize(760, 520)
        self.settings = Settings.load()

        self.processor = Processor()
        self.processor.log.connect(self.log)
        self.processor.page_progress.connect(self._on_page_progress)
        self.processor.overall.connect(self._on_overall)
        self.processor.busy_changed.connect(self._on_busy)

        self.watcher = FolderWatcher(self)
        self.watcher.file_ready.connect(self._on_file_ready)

        # Folder pickers
        self.input_edit = QLineEdit(self.settings.input_dir)
        self.output_edit = QLineEdit(self.settings.output_dir)
        folders = QGridLayout()
        for row, (label, edit) in enumerate((("Input folder:", self.input_edit), ("Output folder:", self.output_edit))):
            browse = QPushButton("Browse…")
            browse.clicked.connect(lambda _=False, e=edit: self._browse(e))
            open_btn = QPushButton("Open")
            open_btn.clicked.connect(lambda _=False, e=edit: self._open_folder(e))
            folders.addWidget(QLabel(label), row, 0)
            folders.addWidget(edit, row, 1)
            folders.addWidget(browse, row, 2)
            folders.addWidget(open_btn, row, 3)

        # Controls
        self.settings_btn = QPushButton("Settings…")
        self.settings_btn.clicked.connect(self._open_settings)
        self.watch_check = QCheckBox("Watch input folder")
        self.watch_check.setToolTip("Automatically process new PDFs that appear in the input folder")
        self.watch_check.toggled.connect(self._on_watch_toggled)
        self.process_btn = QPushButton("Process now")
        self.process_btn.setDefault(True)
        self.process_btn.clicked.connect(self._process_now)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        controls = QHBoxLayout()
        controls.addWidget(self.settings_btn)
        controls.addWidget(self.watch_check)
        controls.addStretch(1)
        controls.addWidget(self.process_btn)
        controls.addWidget(self.stop_btn)

        # Progress + log
        self.status_label = QLabel("Idle")
        self.files_label = QLabel("")
        self.progress = QProgressBar()
        self.progress.setValue(0)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_label, 1)
        status_row.addWidget(self.files_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))

        layout = QVBoxLayout()
        layout.addLayout(folders)
        layout.addLayout(controls)
        layout.addLayout(status_row)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_view, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        if not get_api_key():
            self.log("No Gemini API key set yet. Open Settings to add one.")
        if self.settings.watch:
            self.watch_check.setChecked(True)

    # ---- helpers -------------------------------------------------------------------------

    def log(self, message: str) -> None:
        self.log_view.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def _browse(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or str(Path.home()))
        if folder:
            edit.setText(os.path.normpath(folder))
            self._save_folders()
            if self.watch_check.isChecked() and edit is self.input_edit:
                self._start_watch()

    def _open_folder(self, edit: QLineEdit) -> None:
        if edit.text() and Path(edit.text()).is_dir():
            os.startfile(edit.text())

    def _save_folders(self) -> None:
        self.settings.input_dir = self.input_edit.text().strip()
        self.settings.output_dir = self.output_edit.text().strip()
        self.settings.save()

    def _prepare(self) -> bool:
        """Validate settings and hand the current config to the processor."""
        self._save_folders()
        src, dst = self.settings.input_dir, self.settings.output_dir
        if not src or not Path(src).is_dir():
            QMessageBox.warning(self, "Input folder", "Choose an existing input folder.")
            return False
        if not dst:
            QMessageBox.warning(self, "Output folder", "Choose an output folder.")
            return False
        if Path(src).resolve() == Path(dst).resolve():
            QMessageBox.warning(self, "Folders", "The input and output folders must be different.")
            return False
        try:
            Path(dst).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Output folder", f"Cannot create the output folder:\n{e}")
            return False
        api_key = get_api_key()
        if not api_key:
            QMessageBox.information(self, "API key", "Please enter your Gemini API key.")
            self._open_settings()
            api_key = get_api_key()
            if not api_key:
                return False
        self.processor.configure(
            JobConfig(
                api_key=api_key,
                model=self.settings.model,
                output_dir=dst,
                mode=self.settings.output_mode,
                dpi=self.settings.dpi,
                overwrite=self.settings.overwrite,
            )
        )
        return True

    # ---- actions -------------------------------------------------------------------------

    def _open_settings(self) -> None:
        SettingsDialog(self.settings, self).exec()

    def _process_now(self) -> None:
        if not self._prepare():
            return
        files = [str(p) for p in list_pdfs(self.settings.input_dir)]
        if not files:
            self.log("No PDF files found in the input folder.")
            return
        added = self.processor.enqueue(files)
        self.log(f"Queued {added} file(s).")

    def _stop(self) -> None:
        self.processor.stop()
        self.watch_check.setChecked(False)
        self.log("Stopping…")

    def _on_watch_toggled(self, checked: bool) -> None:
        if checked:
            if not self._start_watch():
                self.watch_check.setChecked(False)
                return
        else:
            self.watcher.stop()
            self.log("Stopped watching the input folder.")
        self.settings.watch = checked
        self.settings.save()
        self.stop_btn.setEnabled(checked or self.processor.is_busy())

    def _start_watch(self) -> bool:
        if not self._prepare():
            return False
        self.watcher.start(self.settings.input_dir)
        self.log(f"Watching {self.settings.input_dir} for new PDFs.")
        return True

    def _on_file_ready(self, path: str) -> None:
        # Settings may have changed since watching started; refresh the processor's config.
        if not self._prepare():
            self.watch_check.setChecked(False)
            return
        dst = Path(self.settings.output_dir) / Path(path).name
        if dst.exists() and not self.settings.overwrite:
            return  # already converted earlier; stay quiet in watch mode
        if self.processor.enqueue([path]):
            self.log(f"New file detected: {Path(path).name}")

    # ---- processor signals ---------------------------------------------------------------

    def _on_page_progress(self, name: str, done: int, total: int) -> None:
        self.status_label.setText(f"{name} — page {min(done + 1, total)} of {total}")
        self.progress.setMaximum(max(total, 1))
        self.progress.setValue(done)

    def _on_overall(self, done: int, total: int) -> None:
        self.files_label.setText(f"Files: {done} / {total}")

    def _on_busy(self, busy: bool) -> None:
        self.stop_btn.setEnabled(busy or self.watch_check.isChecked())
        if not busy:
            self.status_label.setText("Watching for new files…" if self.watch_check.isChecked() else "Idle")
            self.progress.setValue(0)
            self.files_label.setText("")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_folders()
        if self.processor.is_busy():
            answer = QMessageBox.question(self, "Quit", "Files are still being processed. Stop and quit?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.processor.stop()
            self.processor.wait(timeout=5)
        self.watcher.stop()
        event.accept()
