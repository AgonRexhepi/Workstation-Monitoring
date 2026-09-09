"""
Interactive user-session webcam agent.

This process is launched by WebcamPhotoCapture when the parent application
is running as a Windows Service in Session 0.

The agent runs inside the active user's interactive session and therefore
has access to:

    - pynput keyboard activity
    - pynput mouse activity
    - OpenCV webcam

Arguments:
    1. photos_dir
    2. diagnostic_log_file
    3. stop_file
"""

import os
import sys
import time
import logging
import threading
from datetime import datetime


# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------

CURRENT_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

PROJECT_ROOT = os.path.abspath(
    os.path.join(
        CURRENT_DIR,
        "..",
    )
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(
        0,
        PROJECT_ROOT,
    )


import cv2

import config

from monitoring.utils import dated_subdir


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

if len(sys.argv) < 4:
    print(
        "Usage: webcam_agent.py "
        "<photos_dir> <diagnostic_log_file> <stop_file>"
    )

    sys.exit(2)


PHOTOS_DIR = sys.argv[1]
DIAGNOSTIC_LOG_FILE = sys.argv[2]
STOP_FILE = sys.argv[3]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

os.makedirs(
    os.path.dirname(DIAGNOSTIC_LOG_FILE),
    exist_ok=True,
)

logger = logging.getLogger(
    "webcam_agent"
)

logger.setLevel(
    logging.INFO
)

formatter = logging.Formatter(
    "%(asctime)s %(levelname)s webcam_agent – %(message)s"
)


file_handler = logging.FileHandler(
    DIAGNOSTIC_LOG_FILE,
    encoding="utf-8",
)

file_handler.setFormatter(
    formatter
)

logger.addHandler(
    file_handler
)


# Also log to stdout/stderr for manual debug mode.
stream_handler = logging.StreamHandler(
    sys.stdout
)

stream_handler.setFormatter(
    formatter
)

logger.addHandler(
    stream_handler
)


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

stop_event = threading.Event()

activity_event = threading.Event()

last_capture = 0.0

listeners = []


# ---------------------------------------------------------------------------
# Stop-file watcher
# ---------------------------------------------------------------------------

def stop_file_watcher():
    """
    Watch for the stop file created by the parent service.

    This gives the service a clean way to request agent shutdown.
    """
    while not stop_event.wait(1):

        try:
            if os.path.exists(STOP_FILE):

                logger.info(
                    "Stop file detected; shutting down"
                )

                stop_event.set()
                activity_event.set()

                break

        except Exception:
            logger.exception(
                "Error while checking stop file"
            )


# ---------------------------------------------------------------------------
# Activity callbacks
# ---------------------------------------------------------------------------

def on_activity(*args, **kwargs):
    """
    Called by pynput for keyboard/mouse activity.
    """
    if not stop_event.is_set():
        activity_event.set()


# ---------------------------------------------------------------------------
# Activity listeners
# ---------------------------------------------------------------------------

def start_activity_listeners():
    """
    Start pynput keyboard and mouse listeners.

    Returns:
        True on success, False otherwise.
    """
    global listeners

    try:
        from pynput import keyboard
        from pynput import mouse

        # ---------------------------------------------------------------
        # Keyboard
        # ---------------------------------------------------------------
        keyboard_listener = keyboard.Listener(
            on_press=on_activity,
        )

        # ---------------------------------------------------------------
        # Mouse
        # ---------------------------------------------------------------
        mouse_listener = mouse.Listener(
            on_move=on_activity,
            on_click=on_activity,
            on_scroll=on_activity,
        )

        keyboard_listener.start()
        mouse_listener.start()

        listeners = [
            keyboard_listener,
            mouse_listener,
        ]

        logger.info(
            "Keyboard and mouse activity listeners started"
        )

        return True

    except Exception:
        logger.exception(
            "Could not start keyboard/mouse activity listeners"
        )

        listeners = []

        return False


# ---------------------------------------------------------------------------
# Webcam capture
# ---------------------------------------------------------------------------

def capture_photo():
    """
    Capture one photo from the webcam.
    """
    global last_capture

    cap = None

    try:
        os.makedirs(
            PHOTOS_DIR,
            exist_ok=True,
        )

        # ---------------------------------------------------------------
        # Open webcam
        # ---------------------------------------------------------------
        logger.info(
            "Opening webcam index %d",
            config.WEBCAM_INDEX,
        )

        cap = cv2.VideoCapture(
            config.WEBCAM_INDEX
        )

        if not cap.isOpened():

            logger.warning(
                "Webcam index %d not available",
                config.WEBCAM_INDEX,
            )

            return False

        # ---------------------------------------------------------------
        # Resolution
        # ---------------------------------------------------------------
        cap.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            config.WEBCAM_WIDTH,
        )

        cap.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            config.WEBCAM_HEIGHT,
        )

        # ---------------------------------------------------------------
        # Give camera a short moment to initialize.
        # ---------------------------------------------------------------
        time.sleep(0.15)

        # ---------------------------------------------------------------
        # Read frame
        # ---------------------------------------------------------------
        ret, frame = cap.read()

        if not ret or frame is None:

            logger.warning(
                "Webcam frame read failed"
            )

            return False

        # ---------------------------------------------------------------
        # Daily directory
        # ---------------------------------------------------------------
        day_dir = dated_subdir(
            PHOTOS_DIR
        )

        # ---------------------------------------------------------------
        # Unique filename
        # ---------------------------------------------------------------
        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

        filename = os.path.join(
            day_dir,
            f"webcam_photo_{timestamp}.jpg",
        )

        # ---------------------------------------------------------------
        # Save image
        # ---------------------------------------------------------------
        success = cv2.imwrite(
            filename,
            frame,
        )

        if not success:

            logger.warning(
                "Failed to write webcam image: %s",
                filename,
            )

            return False

        last_capture = time.time()

        logger.info(
            "Webcam photo saved: %s",
            filename,
        )

        return True

    except Exception:
        logger.exception(
            "Error while capturing webcam photo"
        )

        return False

    finally:
        if cap is not None:

            try:
                cap.release()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Activity mode
# ---------------------------------------------------------------------------

def activity_loop():
    """
    Wait for keyboard/mouse activity and capture a photo while respecting
    WEBCAM_PHOTO_INTERVAL.
    """
    global last_capture

    interval = max(
        0,
        config.WEBCAM_PHOTO_INTERVAL,
    )

    logger.info(
        "Webcam agent activity mode started "
        "(interval=%s seconds)",
        interval,
    )

    while not stop_event.is_set():

        # ---------------------------------------------------------------
        # Wait for activity
        # ---------------------------------------------------------------
        activity_event.wait()

        if stop_event.is_set():
            break

        activity_event.clear()

        # ---------------------------------------------------------------
        # Respect capture interval
        # ---------------------------------------------------------------
        now = time.time()

        since_last = (
            now - last_capture
        )

        if since_last < interval:

            remaining = (
                interval - since_last
            )

            logger.debug(
                "Capture delayed %.2f seconds",
                remaining,
            )

            stop_event.wait(
                remaining
            )

            if stop_event.is_set():
                break

            activity_event.clear()

        if stop_event.is_set():
            break

        capture_photo()

    logger.info(
        "Webcam agent activity loop stopped"
    )


# ---------------------------------------------------------------------------
# Timer mode
# ---------------------------------------------------------------------------

def timer_loop():
    """
    Capture a photo periodically without activity detection.
    """
    interval = max(
        1,
        config.WEBCAM_PHOTO_INTERVAL,
    )

    logger.info(
        "Webcam agent timer mode started "
        "(interval=%s seconds)",
        interval,
    )

    while not stop_event.wait(
        interval
    ):

        if stop_event.is_set():
            break

        capture_photo()

    logger.info(
        "Webcam agent timer loop stopped"
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup():
    """
    Stop pynput listeners and clean up.
    """
    global listeners

    for listener in listeners:

        try:
            listener.stop()
        except Exception as exc:
            logger.debug(
                "Error stopping listener: %s",
                exc,
            )

    listeners = []

    logger.info(
        "Webcam agent cleanup completed"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """
    Main agent entry point.
    """
    logger.info(
        "=================================================="
    )

    logger.info(
        "Webcam agent starting"
    )

    logger.info(
        "PID=%d",
        os.getpid(),
    )

    logger.info(
        "Photos directory: %s",
        PHOTOS_DIR,
    )

    logger.info(
        "Stop file: %s",
        STOP_FILE,
    )

    logger.info(
        "WEBCAM_INDEX=%s",
        config.WEBCAM_INDEX,
    )

    logger.info(
        "WEBCAM_WIDTH=%s",
        config.WEBCAM_WIDTH,
    )

    logger.info(
        "WEBCAM_HEIGHT=%s",
        config.WEBCAM_HEIGHT,
    )

    logger.info(
        "WEBCAM_PHOTO_INTERVAL=%s",
        config.WEBCAM_PHOTO_INTERVAL,
    )

    logger.info(
        "WEBCAM_PHOTO_ON_ACTIVITY=%s",
        config.WEBCAM_PHOTO_ON_ACTIVITY,
    )

    # ---------------------------------------------------------------
    # Start stop-file watcher
    # ---------------------------------------------------------------
    watcher_thread = threading.Thread(
        target=stop_file_watcher,
        daemon=True,
        name="webcam-stop-watcher",
    )

    watcher_thread.start()

    # ---------------------------------------------------------------
    # Activity mode
    # ---------------------------------------------------------------
    if config.WEBCAM_PHOTO_ON_ACTIVITY:

        if start_activity_listeners():

            activity_loop()

        else:

            logger.warning(
                "Activity listeners unavailable; "
                "falling back to timer mode"
            )

            timer_loop()

    # ---------------------------------------------------------------
    # Timer mode
    # ---------------------------------------------------------------
    else:

        timer_loop()

    # ---------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------
    cleanup()

    logger.info(
        "Webcam agent stopped"
    )

    logger.info(
        "=================================================="
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        logger.info(
            "Webcam agent interrupted"
        )

        stop_event.set()
        activity_event.set()

        cleanup()

    except Exception:

        logger.exception(
            "Fatal webcam agent error"
        )

        stop_event.set()
        activity_event.set()

        cleanup()

        sys.exit(1)