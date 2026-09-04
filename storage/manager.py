"""
Storage manager – handles directory creation, retention policy (age + size),
and provides metadata queries used by the dashboard.
"""

import os
import time
import logging
import threading
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)

def _all_dirs():
    return [
        config.RECORDINGS_DIR,
        config.SCREENSHOTS_DIR,
        config.LOGS_DIR,
        config.WEBCAM_DIR,
    ]


def ensure_directories():
    """Create all required storage directories if they do not exist."""
    for directory in _all_dirs():
        os.makedirs(directory, exist_ok=True)
    logger.info("Storage directories verified")


# ------------------------------------------------------------------
# Retention / cleanup
# ------------------------------------------------------------------

class StorageManager:
    """Periodically enforces the storage retention policy."""

    def __init__(self, check_interval: int = 3600):
        self._interval = check_interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        ensure_directories()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="storage-cleanup"
        )
        self._thread.start()
        logger.info("StorageManager started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("StorageManager stopped")

    def _cleanup_loop(self):
        while not self._stop_event.wait(self._interval):
            try:
                self._enforce_age_policy()
                self._enforce_size_policy()
            except Exception:
                logger.exception("Error during storage cleanup")

    def _enforce_age_policy(self):
        cutoff = time.time() - config.MAX_RECORDING_AGE_DAYS * 86400
        for directory in _all_dirs():
            for path in Path(directory).rglob("*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    logger.info("Removed aged file: %s", path)

    def _enforce_size_policy(self):
        max_bytes = config.MAX_STORAGE_MB * 1024 * 1024
        # Collect (path, stat) pairs once to avoid repeated syscalls and
        # race conditions between the total calculation and the sort/deletion.
        file_stats = []
        for directory in _all_dirs():
            for path in Path(directory).rglob("*"):
                if path.is_file():
                    try:
                        file_stats.append((path, path.stat()))
                    except OSError:
                        pass  # file removed between rglob and stat
        total = sum(s.st_size for _, s in file_stats)
        if total <= max_bytes:
            return
        # Sort oldest-first
        file_stats.sort(key=lambda ps: ps[1].st_mtime)
        for path, stat in file_stats:
            if total <= max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= stat.st_size
            logger.info("Removed file due to size limit: %s", path)


# ------------------------------------------------------------------
# Metadata helpers used by the dashboard
# ------------------------------------------------------------------

def _file_info(path: Path) -> dict:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def list_screen_recordings() -> list[dict]:
    return _list_files(config.RECORDINGS_DIR, "*.mp4")


def list_webcam_recordings() -> list[dict]:
    return _list_files(config.WEBCAM_DIR, "*.mp4")


def list_screenshots() -> list[dict]:
    return _list_files(config.SCREENSHOTS_DIR, "*.png")


def get_keyboard_log_lines(max_lines: int = 500) -> list[str]:
    log_path = Path(config.KEYBOARD_LOG_FILE)
    if not log_path.exists():
        return []
    with log_path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    return lines[-max_lines:]


def _list_files(directory: str, pattern: str) -> list[dict]:
    results = []
    base = Path(directory)
    if not base.exists():
        return results
    for path in sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        results.append(_file_info(path))
    return results


def storage_summary() -> dict:
    total = 0
    for directory in _all_dirs():
        for path in Path(directory).rglob("*"):
            if path.is_file():
                total += path.stat().st_size
    return {
        "total_mb": round(total / (1024 * 1024), 2),
        "max_mb": config.MAX_STORAGE_MB,
        "recordings": len(list_screen_recordings()),
        "webcam": len(list_webcam_recordings()),
        "screenshots": len(list_screenshots()),
    }
