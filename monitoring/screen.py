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
import mss.tools

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

    # Codecs tried in order until one opens successfully.
    _CODEC_FALLBACKS = ["H264", "XVID", "mp4v"]

    def _open_writer(self, filename: str, width: int, height: int):
        """Try codecs in fallback order; return (VideoWriter, codec_str) or (None, None)."""
        seen: set = set()
        codecs_to_try = [config.SCREEN_CODEC] + self._CODEC_FALLBACKS
        tried: list = []
        for codec in codecs_to_try:
            if codec in seen:
                continue
            seen.add(codec)
            tried.append(codec)
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(filename, fourcc, config.SCREEN_FPS, (width, height))
            if writer.isOpened():
                if codec != config.SCREEN_CODEC:
                    logger.warning(
                        "Codec %s unavailable; using %s instead",
                        config.SCREEN_CODEC, codec,
                    )
                return writer, codec
            writer.release()
        logger.error(
            "Failed to initialize VideoWriter for screen recording. "
            "Tried codecs %s, Resolution: %dx%d. Retrying in 30s.",
            tried, width, height
        )
        return None, None

    def _record_loop(self):
        os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                logger.error("No primary monitor available for screen recording")
                return
            monitor = sct.monitors[1]  # primary monitor
            width = monitor["width"]
            height = monitor["height"]
            while not self._stop_event.is_set():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = os.path.join(
                    config.RECORDINGS_DIR, f"screen_{timestamp}.mp4"
                )
                writer, used_codec = self._open_writer(filename, width, height)
                # Check if VideoWriter was successfully initialized
                if writer is None:
                    self._stop_event.wait(30)
                    continue
                # Record in segments
                segment_end = time.time() + config.SEGMENT_DURATION_SECONDS
                frames_written = 0
                segment_failed = False
                try:
                    while not self._stop_event.is_set() and time.time() < segment_end:
                        frame_start = time.time()
                        try:
                            img = np.array(sct.grab(monitor))
                        except Exception as exc:
                            # Session 0 services can intermittently lose access to
                            # the interactive desktop; back off instead of hot-looping.
                            logger.error("Screen capture failed: %s", exc)
                            segment_failed = True
                            break
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        writer.write(frame)
                        frames_written += 1
                        elapsed = time.time() - frame_start
                        sleep_time = (1.0 / config.SCREEN_FPS) - elapsed
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                except Exception:
                    logger.exception("Error in screen record loop")
                finally:
                    writer.release()
                if frames_written > 0:
                    logger.info("Saved screen segment: %s", filename)
                else:
                    try:
                        if os.path.exists(filename):
                            os.remove(filename)
                    except OSError:
                        logger.debug("Could not remove empty screen segment: %s", filename)
                    logger.warning("Dropped empty screen segment: %s", filename)

                if segment_failed:
                    self._stop_event.wait(10)

    def _screenshot_loop(self):
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            counter = 0
            while not self._stop_event.wait(config.SCREENSHOT_INTERVAL):
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join(
                        config.SCREENSHOTS_DIR, f"screenshot_{timestamp}_{counter:04d}.png"
                    )
                    img = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=filename)
                    logger.info("Screenshot saved: %s", filename)
                    counter += 1
                except Exception:
                    logger.exception("Error taking screenshot")
