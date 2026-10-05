"""Background processing queue. Files can be added while a run is in progress (watch mode)."""
from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .gemini_ocr import GeminiOcr, OcrError
from .pdf_builder import Cancelled, convert


@dataclass(frozen=True)
class JobConfig:
    api_key: str
    model: str
    output_dir: str
    mode: str
    dpi: int
    overwrite: bool


log = logging.getLogger(__name__)


class Processor(QObject):
    log = Signal(str)
    page_progress = Signal(str, int, int)  # file name, pages done, total pages
    overall = Signal(int, int)             # files finished, files queued in this run
    busy_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._config: JobConfig | None = None
        self._done = 0
        self._total = 0
        self._stopped = False

    def configure(self, config: JobConfig) -> None:
        with self._lock:
            self._config = config

    def is_busy(self) -> bool:
        with self._lock:
            return self._thread is not None

    def enqueue(self, paths: list[str]) -> int:
        added = 0
        with self._lock:
            for p in paths:
                key = str(Path(p).resolve()).lower()
                if key in self._queued:
                    continue
                self._queued.add(key)
                self._queue.append(p)
                added += 1
            if not added:
                return 0
            self._total += added
            done, total = self._done, self._total
            start = self._thread is None
            if start:
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        if start:
            self.busy_changed.emit(True)
        self.overall.emit(done, total)
        return added

    def stop(self) -> None:
        """Cancel the current file and drop the queue. Files enqueued afterwards still run."""
        with self._lock:
            self._stop.set()
            self._stop = threading.Event()
            self._queue.clear()
            self._queued.clear()
            self._stopped = True

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _run(self) -> None:
        ocr: GeminiOcr | None = None
        ocr_key = None
        while True:
            with self._lock:
                if not self._queue:
                    self._thread = None
                    self._queued.clear()
                    self._done = self._total = 0
                    stopped, self._stopped = self._stopped, False
                    break
                path = self._queue.popleft()
                config = self._config
                stop = self._stop

            try:
                key = (config.api_key, config.model)
                if ocr is None or ocr_key != key:
                    ocr, ocr_key = GeminiOcr(config.api_key, config.model), key
                self._process(Path(path), config, ocr, stop)
            except Exception as e:  # never let the thread die: the app would stay "busy" forever
                log.exception("Unexpected error on %s", path)
                self.log.emit(f"FAILED {Path(path).name}: {e}")

            with self._lock:
                self._queued.discard(str(Path(path).resolve()).lower())
                self._done += 1
                done, total = self._done, self._total
            self.overall.emit(done, total)

        if stopped:
            self.log.emit("Stopped.")
        else:
            self.log.emit("All queued files processed.")
        self.busy_changed.emit(False)

    def _process(self, src: Path, config: JobConfig, ocr: GeminiOcr, stop: threading.Event) -> None:
        dst = Path(config.output_dir) / src.name
        if dst.exists() and not config.overwrite:
            self.log.emit(f"Skipped {src.name}: already exists in the output folder.")
            return
        if not src.exists():
            self.log.emit(f"Skipped {src.name}: file no longer exists.")
            return

        self.log.emit(f"Processing {src.name} ...")
        current_page = [0]

        def progress(done: int, total: int) -> None:
            current_page[0] = done + 1
            self.page_progress.emit(src.name, done, total)

        ocr.warn = lambda message: self.log.emit(f"  {src.name} page {current_page[0]}: {message}")
        ocr.cancelled = stop.is_set
        try:
            pages, read = convert(
                src,
                dst,
                ocr,
                mode=config.mode,
                dpi=config.dpi,
                should_stop=stop.is_set,
                progress=progress,
            )
            self.log.emit(f"Done {src.name}: {pages} page(s), {read} read by Gemini.")
        except Cancelled:
            self.log.emit(f"Cancelled {src.name}.")
        except OcrError as e:
            if stop.is_set():
                self.log.emit(f"Cancelled {src.name}.")
                return
            self.log.emit(f"FAILED {src.name} (page {current_page[0]}): {e}")
            if e.fatal:
                with self._lock:
                    dropped = len(self._queue)
                    self._queue.clear()
                    self._queued.clear()
                if dropped:
                    self.log.emit(f"Skipping the remaining {dropped} file(s): they would fail the same way.")
        except PermissionError as e:
            self.log.emit(f"FAILED {src.name}: cannot write {dst.name}. Is it open in another program? ({e})")
        except Exception as e:  # keep going with the next file
            log.exception("Failed to convert %s", src)
            self.log.emit(f"FAILED {src.name}: {e}")
