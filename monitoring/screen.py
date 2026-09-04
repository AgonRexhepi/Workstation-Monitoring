"""
Screen recorder – captures the primary display and saves MP4 segments.
Also takes periodic screenshots (PNG).
"""

import os
import time
import logging
import threading
from datetime import datetime

import cv2
import numpy as np
import mss

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)


class ScreenRecorder:
    """Records the primary screen at a configurable FPS and takes periodic screenshots."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._screenshot_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if self._record_thread and self._record_thread.is_alive():
            logger.warning("ScreenRecorder already running")
            return
        self._stop_event.clear()
        self._record_thread = threading.Thread(
            target=self._record_loop, daemon=True, name="screen-record"
        )
        self._screenshot_thread = threading.Thread(
            target=self._screenshot_loop, daemon=True, name="screen-screenshot"
        )
        self._record_thread.start()
        self._screenshot_thread.start()
        logger.info("ScreenRecorder started")

    def stop(self):
        self._stop_event.set()
        if self._record_thread:
            self._record_thread.join(timeout=10)
        if self._screenshot_thread:
            self._screenshot_thread.join(timeout=5)
        logger.info("ScreenRecorder stopped")

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    def _record_loop(self):
        os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            width = monitor["width"]
            height = monitor["height"]
            while not self._stop_event.is_set():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(
                    config.RECORDINGS_DIR, f"screen_{timestamp}.mp4"
                )
                fourcc = cv2.VideoWriter_fourcc(*config.SCREEN_CODEC)
                writer = cv2.VideoWriter(
                    filename, fourcc, config.SCREEN_FPS, (width, height)
                )
                # Record in 10-minute segments
                segment_end = time.time() + config.SEGMENT_DURATION_SECONDS
                try:
                    while not self._stop_event.is_set() and time.time() < segment_end:
                        frame_start = time.time()
                        img = np.array(sct.grab(monitor))
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        writer.write(frame)
                        elapsed = time.time() - frame_start
                        sleep_time = (1.0 / config.SCREEN_FPS) - elapsed
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                except Exception:
                    logger.exception("Error in screen record loop")
                finally:
                    writer.release()
                logger.info("Saved screen segment: %s", filename)

    def _screenshot_loop(self):
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            while not self._stop_event.wait(config.SCREENSHOT_INTERVAL):
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SCREENSHOTS_DIR, f"screenshot_{timestamp}.png"
                    )
                    img = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=filename)
                    logger.debug("Screenshot saved: %s", filename)
                except Exception:
                    logger.exception("Error taking screenshot")
