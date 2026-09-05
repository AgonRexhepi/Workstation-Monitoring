"""
Standalone screen agent.

This script is spawned by ScreenRecorder into the active interactive user
session (via CreateProcessAsUser) so that mss can capture the desktop when
main service code runs in Session 0.
"""

import os
import sys
import signal
import threading
import logging

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(BASE_DIR))

from monitoring.screen import ScreenRecorder


def main() -> None:
    diag_log = None
    if len(sys.argv) >= 2:
        diag_log = sys.argv[1]
    else:
        diag_log = os.path.join(os.path.abspath(BASE_DIR), "logs", "screen_agent.log")

    os.makedirs(os.path.dirname(os.path.abspath(diag_log)), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
        handlers=[logging.FileHandler(diag_log, encoding="utf-8")],
    )
    logger = logging.getLogger("screen_agent")
    logger.info("Screen agent starting")

    recorder = ScreenRecorder()
    try:
        recorder.start()
        stop_evt = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop_evt.set())
        signal.signal(signal.SIGTERM, lambda *_: stop_evt.set())
        stop_evt.wait()
    except Exception:
        logger.exception("Screen agent crashed")
        raise
    finally:
        recorder.stop()
        logger.info("Screen agent stopped")


if __name__ == "__main__":
    main()
