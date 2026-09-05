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

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(BASE_DIR))

from monitoring.screen import ScreenRecorder


def main() -> None:
    recorder = ScreenRecorder()
    recorder.start()

    stop_evt = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_evt.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_evt.set())
    stop_evt.wait()
    recorder.stop()


if __name__ == "__main__":
    main()
