"""File logs reopen after external rotation; operational stdout stays in journald."""

from logging.handlers import WatchedFileHandler
from pathlib import Path


def file_handler(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return WatchedFileHandler(path, encoding="utf-8", delay=True)
