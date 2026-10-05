"""Watches the input folder and reports PDFs once they have finished copying."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

POLL_MS = 1000
STABLE_CHECKS = 2  # size must be unchanged for this many polls


def list_pdfs(folder: str | Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() == ".pdf")


def _signature(path: Path) -> tuple[int, float] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime


def _readable(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            f.read(1)
        return True
    except OSError:
        return False


class FolderWatcher(QObject):
    file_ready = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._folder: Path | None = None
        self._fs = QFileSystemWatcher(self)
        self._fs.directoryChanged.connect(self._schedule_scan)
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._scan)
        # path -> (signature, times seen unchanged)
        self._pending: dict[Path, tuple[tuple[int, float], int]] = {}
        # path -> signature that was already reported
        self._reported: dict[Path, tuple[int, float]] = {}

    def start(self, folder: str) -> None:
        self.stop()
        self._folder = Path(folder)
        self._fs.addPath(str(self._folder))
        self._scan()
        self._timer.start()

    def stop(self) -> None:
        if self._fs.directories():
            self._fs.removePaths(self._fs.directories())
        self._timer.stop()
        self._pending.clear()
        self._reported.clear()
        self._folder = None

    def _schedule_scan(self, _path: str) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def _scan(self) -> None:
        if self._folder is None:
            return
        try:
            files = list_pdfs(self._folder)
        except OSError:
            return
        current = set(files)
        for gone in [p for p in self._pending if p not in current]:
            del self._pending[gone]

        for path in files:
            sig = _signature(path)
            if sig is None or self._reported.get(path) == sig:
                continue
            prev = self._pending.get(path)
            count = prev[1] + 1 if prev and prev[0] == sig else 0
            if count >= STABLE_CHECKS and sig[0] > 0 and _readable(path):
                self._pending.pop(path, None)
                self._reported[path] = sig
                self.file_ready.emit(str(path))
            else:
                self._pending[path] = (sig, count)

        # Keep polling only while something is still being copied.
        if not self._pending:
            self._timer.stop()
