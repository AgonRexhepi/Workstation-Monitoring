"""
Shared utilities for the monitoring package.
"""

import os
import re
from datetime import datetime


KEY_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "page_up": "pageup",
    "page_down": "pagedown",
    "caps_lock": "capslock",
    "num_lock": "numlock",
    "scroll_lock": "scrolllock",
    "print_screen": "printscreen",
    "insert": "insert",
    "delete": "delete",
    "home": "home",
    "end": "end",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "enter": "enter",
    "escape": "escape",
    "f5": "f5",
    "alt": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "cmd": "cmd",
    "meta": "cmd",
}

SPECIAL_CHAR_ALIASES = {
    " ": "space",
    "\t": "tab",
    "\r": "enter",
    "\n": "enter",
    "\x08": "backspace",
    "\x1b": "escape",
}

SPECIAL_VK_ALIASES = {
    8: "backspace",
    9: "tab",
    13: "enter",
    27: "escape",
    32: "space",
    33: "pageup",
    34: "pagedown",
    35: "end",
    36: "home",
    37: "left",
    38: "up",
    39: "right",
    40: "down",
    45: "insert",
    46: "delete",
}

ALT_CODE_ENCODINGS = {
    128: "cp437",
    135: "cp437",
    137: "cp437",
    203: "cp1252",
}


def _normalize_key_token(token: str) -> str:
    normalized = token.strip().lower()

    if normalized.startswith("key."):
        normalized = normalized[4:]

    if normalized.endswith(("_l", "_r")) and normalized[:-2] in KEY_ALIASES:
        normalized = normalized[:-2]

    return KEY_ALIASES.get(normalized, normalized)


def _format_char(char: str) -> str:
    alias = SPECIAL_CHAR_ALIASES.get(char)

    if alias:
        return f"[{alias}]"

    codepoint = ord(char)

    if 1 <= codepoint <= 26:
        return f"[ctrl+{chr(codepoint + 96)}]"

    return char


def _decode_alt_code(code: str) -> str | None:
    try:
        value = int(code)
    except ValueError:
        return None

    if not 0 <= value <= 255:
        return None

    encoding = "cp1252" if code.startswith("0") and len(code) > 1 else ALT_CODE_ENCODINGS.get(value)

    if not encoding:
        return None

    return bytes([value]).decode(encoding)


def _format_name(name: str) -> str | None:
    tokens = [_normalize_key_token(token) for token in name.split("+")]

    if len(tokens) == 2 and tokens[0] == "alt" and tokens[1].isdigit():
        return _decode_alt_code(tokens[1])

    if len(tokens) > 1:
        return f"[{'+'.join(tokens)}]"

    token = tokens[0]

    if token in KEY_ALIASES.values() or re.fullmatch(r"f\d+", token):
        return f"[{token}]"

    if len(token) == 1:
        return _format_char(token)

    return None


def _format_vk(vk: int) -> str | None:
    alias = SPECIAL_VK_ALIASES.get(vk)

    if alias:
        return f"[{alias}]"

    if 112 <= vk <= 135:
        return f"[f{vk - 111}]"

    if 96 <= vk <= 105:
        return str(vk - 96)

    if 32 <= vk <= 126:
        return _format_char(chr(vk).lower() if 65 <= vk <= 90 else chr(vk))

    return None


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
        return _format_char(char)

    # Special pynput keys
    name = getattr(key, "name", None)

    if isinstance(name, str) and name:
        formatted = _format_name(name)

        if formatted:
            return formatted

    vk = getattr(key, "vk", None)

    if isinstance(vk, int):
        formatted = _format_vk(vk)

        if formatted:
            return formatted

    # Fallback for string representations such as:
    # 'a', ' ', '\t', '\n', Key.enter, etc.
    text = str(key)

    formatted = _format_name(text)

    if formatted:
        return formatted

    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        literal = text[1:-1]

        try:
            literal = bytes(literal, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            pass

        if literal:
            return _format_char(literal)

    match = re.fullmatch(r"<(\d+)>", text.strip())

    if match:
        formatted = _format_vk(int(match.group(1)))

        if formatted:
            return formatted

    return "[unknown]"
