import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from app.config import LOG_FILE
from app.ui.main_window import MainWindow


def main() -> int:
    # The .exe has no console, so unexpected errors go to %APPDATA%/PdfOcr/app.log
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    sys.excepthook = lambda *exc: logging.getLogger("app").error("Uncaught exception", exc_info=exc)
    app = QApplication(sys.argv)
    app.setApplicationName("PdfOcr")
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
