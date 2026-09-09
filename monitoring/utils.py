"""
Shared utilities for the monitoring package.
"""

import os
from datetime import datetime


def dated_subdir(base_dir: str) -> str:
    """Return *base_dir/YYYY/MM/DD*, creating it if needed."""
    now = datetime.now()
    path = os.path.join(base_dir, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
    os.makedirs(path, exist_ok=True)
    return path


def format_logged_key(key) -> str:
    """Return a stable string representation for a captured key press."""

    # Character keys
    char = getattr(key, "char", None)

    if isinstance(char, str) and char:
        if char == " ":
            return "[space]"
        if char == "\t":
            return "[tab]"
        if char in ("\r", "\n"):
            return "[enter]"

        return char

    # Special pynput keys
    name = getattr(key, "name", None)

    if isinstance(name, str) and name:
        normalized = name.lower()

        if normalized == "return":
            normalized = "enter"

        return f"[{normalized}]"

    # Fallback for string representations such as:
    # 'a', ' ', '\t', '\n', Key.enter, etc.
    text = str(key)

    if text.startswith("Key."):
        normalized = text[4:].lower()

        if normalized == "return":
            normalized = "enter"

        return f"[{normalized}]"

    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        literal = text[1:-1]

        if literal == " ":
            return "[space]"
        if literal == "\\t":
            return "[tab]"
        if literal in ("\\r", "\\n"):
            return "[enter]"

        return literal

    return "[unknown]"