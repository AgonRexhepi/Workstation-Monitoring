"""
Screen recorder – captures the primary display and saves MP4 segments.
Also takes periodic screenshots (PNG).
"""

import os
import time
import logging
import threading
import uuid
from datetime import datetime

import cv2
import numpy as np
import mss
import mss.tools

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from monitoring.utils import dated_subdir

logger = logging.getLogger(__name__)

_AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_agent.py")


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


def _spawn_agent_in_user_session():
    """Spawn the screen agent in the active console user session."""
    try:
        import win32ts
        import win32security
        import win32process
        import win32con
        import win32api

        session_id = win32ts.WTSGetActiveConsoleSessionId()
        if session_id == 0xFFFFFFFF:
            logger.warning("Screen agent: no active user session found")
            return None

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

        os.makedirs(config.LOGS_DIR, exist_ok=True)
        agent_log_file = os.path.join(config.LOGS_DIR, "screen_agent.log")
        stop_file = os.path.join(
            config.LOGS_DIR,
            f"screen_agent_stop_{uuid.uuid4().hex}.flag",
        )

        python_exe = _resolve_python_executable().replace('"', '\\"')
        agent_script = _AGENT_SCRIPT.replace('"', '\\"')
        agent_log_file_esc = agent_log_file.replace('"', '\\"')
        stop_file_esc = stop_file.replace('"', '\\"')
        cmd = (
            f'"{python_exe}" "{agent_script}" '
            f'"{agent_log_file_esc}" "{stop_file_esc}"'
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
            win32api.CloseHandle(primary_token)

        proc_handle, thread_handle, pid, _tid = proc_info
        win32api.CloseHandle(thread_handle)
        logger.info("Screen agent spawned in user session %d (PID %d)", session_id, pid)
        return proc_handle, stop_file
    except Exception as exc:
        logger.warning("Could not spawn screen agent in user session: %s", exc)
        return None


class ScreenRecorder:
    """Records the primary screen at a configurable FPS and takes periodic screenshots."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._record_thread: threading.Thread | None = None
        self._screenshot_thread: threading.Thread | None = None
        self._agent_handle = None
        self._agent_stop_file: str | None = None
        self._agent_lock = threading.Lock()
        self._agent_watchdog_thread: threading.Thread | None = None
        self._using_agent = False
        # Activity-triggered screenshot state
        self._screenshot_activity_event = threading.Event()
        self._screenshot_last_capture: float = 0.0
        self._screenshot_listeners: list = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, record: bool = True, screenshot: bool = True):
        self._stop_event.clear()
        self._screenshot_activity_event.clear()
        self._screenshot_last_capture = 0.0
        if _is_session_0():
            logger.info("ScreenRecorder: detected Session 0, spawning user-session agent")
            spawned = _spawn_agent_in_user_session()
            if spawned is not None:
                handle, stop_file = spawned
                with self._agent_lock:
                    self._agent_handle = handle
                    self._agent_stop_file = stop_file
                self._using_agent = True
                self._agent_watchdog_thread = threading.Thread(
                    target=self._agent_watchdog_loop,
                    daemon=True,
                    name="screen-agent-watchdog",
                )
                self._agent_watchdog_thread.start()
                logger.info("ScreenRecorder started (user-session agent)")
                return
            logger.warning(
                "ScreenRecorder: could not spawn user-session agent; "
                "screen recording will run in Session 0 and may fail."
            )

        if self._record_thread and self._record_thread.is_alive():
            logger.warning("ScreenRecorder already running")
            return
        if record:
            self._record_thread = threading.Thread(
                target=self._record_loop, daemon=True, name="screen-record"
            )
            self._record_thread.start()
        if screenshot:
            if self._screenshot_thread and self._screenshot_thread.is_alive():
                logger.warning("ScreenRecorder screenshot already running")
            else:
                if config.SCREENSHOT_ON_ACTIVITY:
                    self._start_screenshot_listeners()
                    target = self._screenshot_activity_loop
                else:
                    target = self._screenshot_timer_loop
                self._screenshot_thread = threading.Thread(
                    target=target, daemon=True, name="screen-screenshot"
                )
                self._screenshot_thread.start()
        logger.info(
            "ScreenRecorder started (record=%s, screenshot=%s, activity_mode=%s)",
            record, screenshot, config.SCREENSHOT_ON_ACTIVITY,
        )

    def stop(self):
        self._stop_event.set()
        self._screenshot_activity_event.set()  # unblock any waiting screenshot thread
        self._stop_screenshot_listeners()
        if self._using_agent:
            with self._agent_lock:
                handle = self._agent_handle
                stop_file = self._agent_stop_file
                self._agent_handle = None
                self._agent_stop_file = None
            self._using_agent = False
            if stop_file:
                try:
                    with open(stop_file, "w", encoding="utf-8"):
                        pass
                except OSError as exc:
                    logger.debug("Could not create screen agent stop file: %s", exc)

            exited_cleanly = False
            if handle is not None:
                try:
                    import win32event
                    wait_rc = win32event.WaitForSingleObject(handle, 7000)
                    exited_cleanly = wait_rc == win32event.WAIT_OBJECT_0
                except Exception:
                    exited_cleanly = False

            if handle is not None:
                try:
                    import win32process
                    import win32api
                    try:
                        if not exited_cleanly:
                            try:
                                win32process.TerminateProcess(handle, 0)
                            except Exception as exc:
                                logger.debug("Error terminating screen agent: %s", exc)
                    finally:
                        win32api.CloseHandle(handle)
                except Exception as exc:
                    logger.debug("Error cleaning up screen agent handle: %s", exc)
            if stop_file:
                try:
                    if os.path.exists(stop_file):
                        os.remove(stop_file)
                except OSError:
                    logger.debug("Could not remove screen agent stop file: %s", stop_file)
            if self._agent_watchdog_thread:
                self._agent_watchdog_thread.join(timeout=5)
            logger.info("ScreenRecorder stopped")
            return

        if self._record_thread:
            self._record_thread.join(timeout=10)
        if self._screenshot_thread:
            self._screenshot_thread.join(timeout=5)
        logger.info("ScreenRecorder stopped")

    def _agent_watchdog_loop(self):
        """Respawn the agent if it exits unexpectedly while service is running."""
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
                "Screen agent exited unexpectedly (code %s); attempting restart",
                exit_code,
            )
            spawned = _spawn_agent_in_user_session()
            if spawned is not None:
                new_handle, stop_file = spawned
                with self._agent_lock:
                    self._agent_handle = new_handle
                    self._agent_stop_file = stop_file
            else:
                logger.warning("Screen agent restart failed; will retry")

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Activity-listener helpers (screenshot)
    # ------------------------------------------------------------------

    def _on_screenshot_activity(self, *_args, **_kwargs):
        self._screenshot_activity_event.set()

    def _start_screenshot_listeners(self):
        try:
            from pynput import keyboard as kb, mouse as ms
            kb_listener = kb.Listener(on_press=self._on_screenshot_activity, daemon=True)
            ms_listener = ms.Listener(
                on_move=self._on_screenshot_activity,
                on_click=self._on_screenshot_activity,
                on_scroll=self._on_screenshot_activity,
                daemon=True,
            )
            kb_listener.start()
            ms_listener.start()
            self._screenshot_listeners = [kb_listener, ms_listener]
        except Exception as exc:
            logger.warning(
                "ScreenRecorder: could not start activity listeners (%s); "
                "falling back to timer mode for screenshots.", exc,
            )
            self._screenshot_listeners = []

    def _stop_screenshot_listeners(self):
        for listener in self._screenshot_listeners:
            try:
                listener.stop()
            except Exception:
                pass
        self._screenshot_listeners = []

    # ------------------------------------------------------------------
    # Screenshot loops
    # ------------------------------------------------------------------

    def _screenshot_activity_loop(self):
        """Take a screenshot on any keyboard/mouse activity, with a minimum interval."""
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        counter = 0
        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                logger.error("No primary monitor available for screenshots")
                return
            monitor = sct.monitors[1]
            while not self._stop_event.is_set():
                self._screenshot_activity_event.wait()
                if self._stop_event.is_set():
                    break
                self._screenshot_activity_event.clear()

                now = time.time()
                since_last = now - self._screenshot_last_capture
                if since_last < config.SCREENSHOT_INTERVAL:
                    remaining = config.SCREENSHOT_INTERVAL - since_last
                    self._stop_event.wait(remaining)
                    if self._stop_event.is_set():
                        break
                # Cooldown (if any) has elapsed – take the screenshot now.
                # Clear any activity that fired during the cooldown to avoid
                # an immediate second capture on the next loop iteration.
                self._screenshot_activity_event.clear()

                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    day_dir = dated_subdir(config.SCREENSHOTS_DIR)
                    filename = os.path.join(
                        day_dir, f"screenshot_{timestamp}_{counter:04d}.png"
                    )
                    img = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=filename)
                    self._screenshot_last_capture = time.time()
                    logger.info("Screenshot saved: %s", filename)
                    counter += 1
                except Exception:
                    logger.exception("Error taking screenshot")

    def _screenshot_timer_loop(self):
        """Take a screenshot every SCREENSHOT_INTERVAL seconds."""
        os.makedirs(config.SCREENSHOTS_DIR, exist_ok=True)
        counter = 0
        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                logger.error("No primary monitor available for screenshots")
                return
            monitor = sct.monitors[1]
            while not self._stop_event.wait(config.SCREENSHOT_INTERVAL):
                try:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    day_dir = dated_subdir(config.SCREENSHOTS_DIR)
                    filename = os.path.join(
                        day_dir, f"screenshot_{timestamp}_{counter:04d}.png"
                    )
                    img = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=filename)
                    logger.info("Screenshot saved: %s", filename)
                    counter += 1
                except Exception:
                    logger.exception("Error taking screenshot")

    # Codecs tried in order until one opens successfully.
    _CODEC_FALLBACKS = ["H264", "XVID", "mp4v"]

    def _open_writer(self, filename: str, width: int, height: int):
        """Try codecs in fallback order; return (VideoWriter, codec_str) or (None, None)."""
        seen: set = set()
        codecs_to_try = [config.SCREEN_CODEC] + self._CODEC_FALLBACKS
        tried: list = []
        for codec in codecs_to_try:
            if codec in seen:
                continue
            seen.add(codec)
            tried.append(codec)
            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(filename, fourcc, config.SCREEN_FPS, (width, height))
            if writer.isOpened():
                if codec != config.SCREEN_CODEC:
                    logger.warning(
                        "Codec %s unavailable; using %s instead",
                        config.SCREEN_CODEC, codec,
                    )
                return writer, codec
            writer.release()
        logger.error(
            "Failed to initialize VideoWriter for screen recording. "
            "Tried codecs %s, Resolution: %dx%d. Retrying in 30s.",
            tried, width, height
        )
        return None, None

    def _record_loop(self):
        os.makedirs(config.RECORDINGS_DIR, exist_ok=True)
        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                logger.error("No primary monitor available for screen recording")
                return
            monitor = sct.monitors[1]  # primary monitor
            width = monitor["width"]
            height = monitor["height"]
            while not self._stop_event.is_set():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                day_dir = dated_subdir(config.RECORDINGS_DIR)
                final_filename = os.path.join(day_dir, f"screen_{timestamp}.mp4")
                active_filename = final_filename.replace(".mp4", "_active.mp4")
                writer, used_codec = self._open_writer(active_filename, width, height)
                # Check if VideoWriter was successfully initialized
                if writer is None:
                    self._stop_event.wait(30)
                    continue
                # Record in segments
                segment_end = time.time() + config.SEGMENT_DURATION_SECONDS
                frames_written = 0
                segment_failed = False
                try:
                    while not self._stop_event.is_set() and time.time() < segment_end:
                        frame_start = time.time()
                        try:
                            img = np.array(sct.grab(monitor))
                        except Exception as exc:
                            # Session 0 services can intermittently lose access to
                            # the interactive desktop; back off instead of hot-looping.
                            logger.error("Screen capture failed: %s", exc)
                            segment_failed = True
                            break
                        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                        writer.write(frame)
                        frames_written += 1
                        elapsed = time.time() - frame_start
                        sleep_time = (1.0 / config.SCREEN_FPS) - elapsed
                        if sleep_time > 0:
                            time.sleep(sleep_time)
                except Exception:
                    logger.exception("Error in screen record loop")
                finally:
                    writer.release()
                if frames_written > 0:
                    try:
                        if os.path.exists(final_filename):
                            os.remove(final_filename)
                        os.replace(active_filename, final_filename)
                        logger.info("Saved screen segment: %s", final_filename)
                    except OSError:
                        logger.exception("Failed to finalize screen segment: %s", active_filename)
                else:
                    try:
                        if os.path.exists(active_filename):
                            os.remove(active_filename)
                    except OSError:
                        logger.debug("Could not remove empty screen segment: %s", active_filename)
                    logger.warning("Dropped empty screen segment: %s", active_filename)

                if segment_failed:
                    self._stop_event.wait(10)



