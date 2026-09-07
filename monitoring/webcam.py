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
from monitoring.utils import dated_subdir

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
            day_dir = dated_subdir(config.WEBCAM_DIR)
            filename = os.path.join(day_dir, f"webcam_{timestamp}.mp4")
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


class WebcamPhotoCapture:
    """Takes a JPEG snapshot from the webcam.

    Two modes (controlled by ``config.WEBCAM_PHOTO_ON_ACTIVITY``):

    * **Activity-triggered** (default): a photo is captured whenever keyboard
      or mouse activity is detected, subject to a minimum gap of
      ``WEBCAM_PHOTO_INTERVAL`` seconds between consecutive captures.
    * **Timer-only**: a photo is captured every ``WEBCAM_PHOTO_INTERVAL``
      seconds regardless of user activity.
    """

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_capture: float = 0.0
        self._activity_event = threading.Event()
        self._listeners: list = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("WebcamPhotoCapture already running")
            return
        self._stop_event.clear()
        self._activity_event.clear()
        self._last_capture = 0.0

        if config.WEBCAM_PHOTO_ON_ACTIVITY:
            self._start_activity_listeners()
            target = self._activity_loop
        else:
            target = self._timer_loop

        self._thread = threading.Thread(target=target, daemon=True, name="webcam-photo")
        self._thread.start()
        logger.info("WebcamPhotoCapture started (activity_mode=%s)", config.WEBCAM_PHOTO_ON_ACTIVITY)

    def stop(self):
        self._stop_event.set()
        self._activity_event.set()  # unblock waiting thread
        self._stop_activity_listeners()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("WebcamPhotoCapture stopped")

    # ------------------------------------------------------------------
    # Activity listeners (pynput keyboard + mouse)
    # ------------------------------------------------------------------

    def _on_activity(self, *_args, **_kwargs):
        """Signal that user activity was detected."""
        self._activity_event.set()

    def _start_activity_listeners(self):
        try:
            from pynput import keyboard as kb, mouse as ms

            kb_listener = kb.Listener(
                on_press=self._on_activity,
                daemon=True,
            )
            ms_listener = ms.Listener(
                on_move=self._on_activity,
                on_click=self._on_activity,
                on_scroll=self._on_activity,
                daemon=True,
            )
            kb_listener.start()
            ms_listener.start()
            self._listeners = [kb_listener, ms_listener]
        except Exception as exc:
            logger.warning(
                "WebcamPhotoCapture: could not start activity listeners (%s); "
                "falling back to timer mode.",
                exc,
            )
            self._listeners = []

    def _stop_activity_listeners(self):
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._listeners = []

    # ------------------------------------------------------------------
    # Capture loops
    # ------------------------------------------------------------------

    def _activity_loop(self):
        """Wait for activity, then capture – respecting the minimum interval."""
        os.makedirs(config.WEBCAM_PHOTOS_DIR, exist_ok=True)
        while not self._stop_event.is_set():
            # Block until activity or stop
            self._activity_event.wait()
            if self._stop_event.is_set():
                break
            self._activity_event.clear()

            now = time.time()
            since_last = now - self._last_capture
            if since_last < config.WEBCAM_PHOTO_INTERVAL:
                # Too soon – wait out the remaining cooldown
                remaining = config.WEBCAM_PHOTO_INTERVAL - since_last
                self._stop_event.wait(remaining)
                if self._stop_event.is_set():
                    break
                # Discard any activity that fired during the cooldown so it
                # does not immediately trigger another capture.
                self._activity_event.clear()

            if self._stop_event.is_set():
                break
            self._capture_photo()

    def _timer_loop(self):
        """Capture on a fixed interval."""
        os.makedirs(config.WEBCAM_PHOTOS_DIR, exist_ok=True)
        while not self._stop_event.wait(config.WEBCAM_PHOTO_INTERVAL):
            self._capture_photo()

    # ------------------------------------------------------------------
    # Single-shot capture
    # ------------------------------------------------------------------

    def _capture_photo(self):
        cap = cv2.VideoCapture(config.WEBCAM_INDEX)
        try:
            if not cap.isOpened():
                logger.warning(
                    "WebcamPhotoCapture: webcam index %d not available",
                    config.WEBCAM_INDEX,
                )
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.WEBCAM_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.WEBCAM_HEIGHT)
            ret, frame = cap.read()
            if not ret:
                logger.warning("WebcamPhotoCapture: frame read failed")
                return
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            day_dir = dated_subdir(config.WEBCAM_PHOTOS_DIR)
            filename = os.path.join(day_dir, f"webcam_photo_{timestamp}.jpg")
            cv2.imwrite(filename, frame)
            self._last_capture = time.time()
            logger.info("Webcam photo saved: %s", filename)
        except Exception:
            logger.exception("Error in webcam photo capture")
        finally:
            cap.release()

