"""
Webcam recorder – captures video from a connected camera and saves MP4 segments.
"""

import os
import time
import logging
import threading
from datetime import datetime

import cv2

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config

logger = logging.getLogger(__name__)


class WebcamRecorder:
    """Captures webcam video in 10-minute MP4 segments."""

    # Codecs tried in order until one opens successfully.
    _CODEC_FALLBACKS = ["mp4v", "XVID", "H264"]

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("WebcamRecorder already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._record_loop, daemon=True, name="webcam-record"
        )
        self._thread.start()
        logger.info("WebcamRecorder started")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("WebcamRecorder stopped")

    def _open_writer(self, filename: str):
        """Try codecs in fallback order; return (VideoWriter, codec_str) or (None, None)."""
        seen: set = set()
        codecs_to_try = [config.WEBCAM_CODEC] + self._CODEC_FALLBACKS
        tried: list = []
        for codec in codecs_to_try:
            if codec in seen:
                continue
            seen.add(codec)
            tried.append(codec)
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(
                filename,
                fourcc,
                config.WEBCAM_FPS,
                (config.WEBCAM_WIDTH, config.WEBCAM_HEIGHT),
            )
            if writer.isOpened():
                if codec != config.WEBCAM_CODEC:
                    logger.warning(
                        "Codec %s unavailable for webcam; using %s instead",
                        config.WEBCAM_CODEC, codec,
                    )
                return writer, codec
            writer.release()

        logger.error(
            "Failed to initialize VideoWriter for webcam recording. "
            "Tried codecs %s, Resolution: %dx%d. Retrying in 30s.",
            tried,
            config.WEBCAM_WIDTH,
            config.WEBCAM_HEIGHT,
        )
        return None, None

    def _record_loop(self):
        os.makedirs(config.WEBCAM_DIR, exist_ok=True)
        while not self._stop_event.is_set():
            cap = cv2.VideoCapture(config.WEBCAM_INDEX)
            if not cap.isOpened():
                logger.warning(
                    "Webcam index %d not available; retrying in 30 s",
                    config.WEBCAM_INDEX,
                )
                self._stop_event.wait(30)
                continue

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WEBCAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.WEBCAM_HEIGHT)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(config.WEBCAM_DIR, f"webcam_{timestamp}.mp4")
            writer, used_codec = self._open_writer(filename)
            if writer is None:
                cap.release()
                self._stop_event.wait(30)
                continue

            segment_end = time.time() + config.SEGMENT_DURATION_SECONDS
            frames_written = 0
            try:
                while not self._stop_event.is_set() and time.time() < segment_end:
                    ret, frame = cap.read()
                    if not ret:
                        logger.warning("Webcam frame read failed; stopping segment")
                        break
                    writer.write(frame)
                    frames_written += 1
                    time.sleep(1.0 / config.WEBCAM_FPS)
            except Exception:
                logger.exception("Error in webcam record loop")
            finally:
                writer.release()
                cap.release()

            if frames_written > 0:
                logger.info("Saved webcam segment: %s", filename)
            else:
                try:
                    if os.path.exists(filename):
                        os.remove(filename)
                except OSError:
                    logger.debug("Could not remove empty webcam segment: %s", filename)
                logger.warning("Dropped empty webcam segment: %s", filename)
