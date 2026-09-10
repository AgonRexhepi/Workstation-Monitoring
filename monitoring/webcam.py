"""
Webcam monitoring components.

WebcamRecorder
---------------
Records webcam video continuously when enabled.

WebcamPhotoCapture
------------------
Captures webcam photos periodically, either:
    - on user activity (keyboard/mouse), or
    - on a fixed timer.

Windows Service / Session 0
---------------------------
When running as a Windows Service, the service normally runs in Session 0.
Interactive keyboard/mouse hooks and webcam access are therefore delegated to
webcam_agent.py, which is launched inside the active interactive user session
using CreateProcessAsUser.
"""

import os
import sys
import time
import uuid
import logging
import threading
from datetime import datetime

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
from monitoring.utils import dated_subdir


logger = logging.getLogger(__name__)


# ============================================================================
# Helpers
# ============================================================================

_AGENT_SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "webcam_agent.py",
)


def _resolve_python_executable() -> str:
    """
    Resolve a Python executable suitable for launching child agents.

    When running through pywin32/pythonservice.exe, use python.exe from the
    same directory instead.
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


def _is_session_0() -> bool:
    """
    Return True when the current process is running in Windows Session 0.
    """
    try:
        import ctypes

        ProcessIdToSessionId = ctypes.windll.kernel32.ProcessIdToSessionId

        session = ctypes.c_ulong(0)

        success = ProcessIdToSessionId(
            os.getpid(),
            ctypes.byref(session),
        )

        if not success:
            return False

        return session.value == 0

    except Exception:
        return False


def _spawn_agent_in_user_session(
    photos_dir: str,
    diag_log_file: str,
    stop_file: str,
):
    """
    Launch webcam_agent.py inside the active interactive user session.

    Returns:
    Tuple containing:
        - Win32 process handle
        - Windows session ID
    or None on failure.
    """
    user_token = None
    primary_token = None
    proc_handle = None
    thread_handle = None

    try:
        import win32ts
        import win32security
        import win32process
        import win32con
        import win32api

        # ---------------------------------------------------------------
        # Get active console session
        # ---------------------------------------------------------------
        session_id = win32ts.WTSGetActiveConsoleSessionId()

        if session_id == 0xFFFFFFFF:
            logger.warning(
                "Webcam agent: no active user session found"
            )
            return None

        # ---------------------------------------------------------------
        # Get user token for active session
        # ---------------------------------------------------------------
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
            user_token = None

        # ---------------------------------------------------------------
        # Prepare paths
        # ---------------------------------------------------------------
        os.makedirs(config.LOGS_DIR, exist_ok=True)
        os.makedirs(photos_dir, exist_ok=True)

        python_exe = _resolve_python_executable()

        python_exe = python_exe.replace('"', '\\"')
        agent_script = _AGENT_SCRIPT.replace('"', '\\"')
        photos_dir_esc = photos_dir.replace('"', '\\"')
        diag_log_file_esc = diag_log_file.replace('"', '\\"')
        stop_file_esc = stop_file.replace('"', '\\"')

        # ---------------------------------------------------------------
        # Build command
        # ---------------------------------------------------------------
        cmd = (
            f'"{python_exe}" '
            f'"{agent_script}" '
            f'"{photos_dir_esc}" '
            f'"{diag_log_file_esc}" '
            f'"{stop_file_esc}"'
        )

        # ---------------------------------------------------------------
        # Create process inside user's desktop
        # ---------------------------------------------------------------
        startup = win32process.STARTUPINFO()

        startup.dwFlags = win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE

        # Important:
        # webcam/pynput needs the interactive user's desktop.
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
            if primary_token is not None:
                try:
                    win32api.CloseHandle(primary_token)
                except Exception:
                    pass

                primary_token = None

        proc_handle, thread_handle, pid, _tid = proc_info

        # We only need the process handle.
        if thread_handle is not None:
            try:
                win32api.CloseHandle(thread_handle)
            except Exception:
                pass

            thread_handle = None

        logger.info(
            "Webcam agent spawned in user session %d (PID %d)",
            session_id,
            pid,
        )

        return proc_handle, session_id

    except Exception as exc:
        logger.warning(
            "Could not spawn webcam agent in user session: %s",
            exc,
        )

        # Cleanup if something failed before CreateProcessAsUser finished.
        try:
            import win32api

            if thread_handle is not None:
                win32api.CloseHandle(thread_handle)

            if proc_handle is not None:
                win32api.CloseHandle(proc_handle)

            if user_token is not None:
                win32api.CloseHandle(user_token)

            if primary_token is not None:
                win32api.CloseHandle(primary_token)

        except Exception:
            pass

        return None


# ============================================================================
# WebcamRecorder
# ============================================================================

class WebcamRecorder:
    """
    Continuously records webcam video.

    This component is independent from WebcamPhotoCapture.
    """

    _CODEC_FALLBACKS = [
        "mp4v",
        "XVID",
        "H264",
    ]

    def __init__(self):
        self._stop_event = threading.Event()
        self._thread = None
        self._cap = None

    def start(self):
        """
        Start continuous webcam recording.
        """
        if self._thread and self._thread.is_alive():
            logger.warning(
                "WebcamRecorder already running"
            )
            return

        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._record_loop,
            daemon=True,
            name="webcam-recorder",
        )

        self._thread.start()

        logger.info(
            "WebcamRecorder started"
        )

    def stop(self):
        """
        Stop webcam recording.
        """
        self._stop_event.set()

        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=10)

        self._thread = None
        self._cap = None

        logger.info(
            "WebcamRecorder stopped"
        )

    def _record_loop(self):
        """
        Recording worker.
        """
        os.makedirs(
            config.WEBCAM_RECORDINGS_DIR,
            exist_ok=True,
        )

        cap = cv2.VideoCapture(
            config.WEBCAM_INDEX
        )

        self._cap = cap

        try:
            if not cap.isOpened():
                logger.warning(
                    "WebcamRecorder: webcam index %d not available",
                    config.WEBCAM_INDEX,
                )
                return

            cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                config.WEBCAM_WIDTH,
            )

            cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                config.WEBCAM_HEIGHT,
            )

            fps = 20.0

            width = int(
                cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            )

            height = int(
                cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            )

            if width <= 0:
                width = config.WEBCAM_WIDTH

            if height <= 0:
                height = config.WEBCAM_HEIGHT

            while not self._stop_event.is_set():

                day_dir = dated_subdir(
                    config.WEBCAM_RECORDINGS_DIR
                )

                timestamp = datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )

                filename = os.path.join(
                    day_dir,
                    f"webcam_{timestamp}.mp4",
                )

                writer = None

                for codec in self._CODEC_FALLBACKS:
                    try:
                        fourcc = cv2.VideoWriter_fourcc(
                            *codec
                        )

                        candidate = cv2.VideoWriter(
                            filename,
                            fourcc,
                            fps,
                            (width, height),
                        )

                        if candidate.isOpened():
                            writer = candidate

                            logger.info(
                                "WebcamRecorder: using codec %s",
                                codec,
                            )

                            break

                        candidate.release()

                    except Exception:
                        logger.exception(
                            "WebcamRecorder: codec %s failed",
                            codec,
                        )

                if writer is None:
                    logger.warning(
                        "WebcamRecorder: could not initialize "
                        "video writer"
                    )
                    return

                try:
                    # Record until stop is requested.
                    # Re-create the file when the configured interval
                    # is reached.
                    started_at = time.time()

                    while not self._stop_event.is_set():

                        ret, frame = cap.read()

                        if not ret:
                            logger.warning(
                                "WebcamRecorder: frame read failed"
                            )
                            break

                        writer.write(frame)

                        # If an interval is configured, rotate files.
                        interval = getattr(
                            config,
                            "WEBCAM_RECORD_INTERVAL",
                            3600,
                        )

                        if interval > 0:
                            if (
                                time.time() - started_at
                                >= interval
                            ):
                                break

                        time.sleep(0.001)

                finally:
                    writer.release()

        except Exception:
            logger.exception(
                "Error in webcam recording loop"
            )

        finally:
            try:
                cap.release()
            except Exception:
                pass

            self._cap = None


# ============================================================================
# WebcamPhotoCapture
# ============================================================================

class WebcamPhotoCapture:
    """
    Periodic webcam photo capture.

    Activity mode:
        pynput monitors keyboard/mouse activity.

    Timer mode:
        photo is captured every WEBCAM_PHOTO_INTERVAL seconds.

    In Windows Service Session 0:
        webcam_agent.py is spawned in the active user session.
    """

    def __init__(self):
        self._stop_event = threading.Event()

        self._thread = None

        self._last_capture = 0.0

        self._activity_event = threading.Event()

        self._listeners = []

        # Session 0 / user-session agent state
        self._agent_handle = None
        self._agent_session_id = None
        self._agent_lock = threading.Lock()
        self._agent_watchdog_thread = None
        self._using_agent = False

        self._agent_stop_file = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """
        Start webcam photo capture.
        """
        if self._thread and self._thread.is_alive():
            logger.warning(
                "WebcamPhotoCapture already running"
            )
            return

        self._stop_event.clear()
        self._activity_event.clear()
        self._last_capture = 0.0

        # ---------------------------------------------------------------
        # Windows Service / Session 0
        # ---------------------------------------------------------------
        if _is_session_0():
            logger.info(
                "WebcamPhotoCapture: detected Session 0, "
                "spawning user-session agent"
            )

            os.makedirs(
                config.LOGS_DIR,
                exist_ok=True,
            )

            # Unique stop file for this agent.
            stop_file = os.path.join(
                config.LOGS_DIR,
                f"webcam_agent_stop_{uuid.uuid4().hex}.flag",
            )

            diag_log_file = os.path.join(
                config.LOGS_DIR,
                "webcam_agent.log",
            )

            self._agent_stop_file = stop_file

            spawned = _spawn_agent_in_user_session(
                config.WEBCAM_PHOTOS_DIR,
                diag_log_file,
                stop_file,
            )

            if spawned is not None:

                handle, session_id = spawned

                with self._agent_lock:
                    self._agent_handle = handle
                    self._agent_session_id = session_id

                self._using_agent = True

                self._agent_watchdog_thread = threading.Thread(
                    target=self._agent_watchdog_loop,
                    daemon=True,
                    name="webcam-agent-watchdog",
                )

                self._agent_watchdog_thread.start()

                logger.info(
                    "WebcamPhotoCapture started "
                    "(user-session agent, session=%d, activity_mode=%s)",
                    session_id,
                    config.WEBCAM_PHOTO_ON_ACTIVITY,
                )

                return

            logger.warning(
                "WebcamPhotoCapture: could not spawn "
                "user-session agent; webcam photos "
                "will be unavailable."
            )

            return

        # ---------------------------------------------------------------
        # Interactive / debug session
        # ---------------------------------------------------------------
        if config.WEBCAM_PHOTO_ON_ACTIVITY:
            listener_started = self._start_activity_listeners()

            if listener_started:
                target = self._activity_loop
            else:
                logger.warning(
                    "WebcamPhotoCapture: activity listeners "
                    "could not start; falling back to timer mode."
                )

                target = self._timer_loop

        else:
            target = self._timer_loop

        self._thread = threading.Thread(
            target=target,
            daemon=True,
            name="webcam-photo",
        )

        self._thread.start()

        logger.info(
            "WebcamPhotoCapture started (activity_mode=%s)",
            config.WEBCAM_PHOTO_ON_ACTIVITY,
        )

    def stop(self):
        """
        Stop webcam photo capture and user-session agent if active.
        """
        self._stop_event.set()
        self._activity_event.set()

        # ---------------------------------------------------------------
        # Stop user-session agent
        # ---------------------------------------------------------------
        if self._using_agent:

            with self._agent_lock:
                handle = self._agent_handle
                self._agent_handle = None
                self._agent_session_id = None

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
                            "Error terminating webcam agent: %s",
                            exc,
                        )

                    finally:
                        try:
                            win32api.CloseHandle(handle)
                        except Exception:
                            pass

                except Exception as exc:
                    logger.debug(
                        "Error cleaning up webcam agent handle: %s",
                        exc,
                    )

            if self._agent_watchdog_thread:
                self._agent_watchdog_thread.join(
                    timeout=5
                )

            self._agent_watchdog_thread = None
            self._using_agent = False

        # ---------------------------------------------------------------
        # Stop local pynput listeners
        # ---------------------------------------------------------------
        for listener in self._listeners:
            try:
                listener.stop()
            except Exception as exc:
                logger.debug(
                    "Error stopping webcam activity listener: %s",
                    exc,
                )

        self._listeners = []

        # ---------------------------------------------------------------
        # Stop worker thread
        # ---------------------------------------------------------------
        if self._thread:
            self._thread.join(timeout=10)

        self._thread = None

        # ---------------------------------------------------------------
        # Remove agent stop file
        # ---------------------------------------------------------------
        if self._agent_stop_file:
            try:
                if os.path.exists(
                    self._agent_stop_file
                ):
                    os.remove(
                        self._agent_stop_file
                    )
            except OSError:
                pass

            self._agent_stop_file = None

        logger.info(
            "WebcamPhotoCapture stopped"
        )

    # ------------------------------------------------------------------
    # Activity listeners
    # ------------------------------------------------------------------

    def _start_activity_listeners(self):
        """
        Start pynput keyboard/mouse activity listeners.

        Returns:
            True if at least the listeners started successfully.
        """
        try:
            from pynput import keyboard as kb
            from pynput import mouse as ms

            kb_listener = kb.Listener(
                on_press=self._on_activity,
            )

            ms_listener = ms.Listener(
                on_move=self._on_activity,
                on_click=self._on_activity,
                on_scroll=self._on_activity,
            )

            kb_listener.start()
            ms_listener.start()

            self._listeners = [
                kb_listener,
                ms_listener,
            ]

            logger.info(
                "WebcamPhotoCapture: activity listeners started"
            )

            return True

        except Exception as exc:
            logger.warning(
                "WebcamPhotoCapture: could not start "
                "activity listeners: %s",
                exc,
            )

            self._listeners = []

            return False

    def _on_activity(self, *args, **kwargs):
        """
        Signal that user activity occurred.
        """
        if not self._stop_event.is_set():
            self._activity_event.set()

    # ------------------------------------------------------------------
    # Interactive activity mode
    # ------------------------------------------------------------------

    def _activity_loop(self):
        """
        Capture a photo after user activity while respecting the interval.
        """
        os.makedirs(
            config.WEBCAM_PHOTOS_DIR,
            exist_ok=True,
        )

        while not self._stop_event.is_set():

            # Wait for keyboard/mouse activity.
            self._activity_event.wait()

            if self._stop_event.is_set():
                break

            self._activity_event.clear()

            now = time.time()

            since_last = (
                now - self._last_capture
            )

            interval = max(
                0,
                config.WEBCAM_PHOTO_INTERVAL,
            )

            # -----------------------------------------------------------
            # Respect minimum capture interval
            # -----------------------------------------------------------
            if since_last < interval:

                remaining = (
                    interval - since_last
                )

                self._stop_event.wait(
                    remaining
                )

                if self._stop_event.is_set():
                    break

                # Activity happened during the interval.
                # Capture now because the interval has elapsed.
                self._activity_event.clear()

            if self._stop_event.is_set():
                break

            self._capture_photo()

    # ------------------------------------------------------------------
    # Timer mode
    # ------------------------------------------------------------------

    def _timer_loop(self):
        """
        Capture photos on a fixed interval.
        """
        os.makedirs(
            config.WEBCAM_PHOTOS_DIR,
            exist_ok=True,
        )

        interval = max(
            1,
            config.WEBCAM_PHOTO_INTERVAL,
        )

        while not self._stop_event.wait(
            interval
        ):

            if self._stop_event.is_set():
                break

            self._capture_photo()

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _capture_photo(self):
        """
        Capture one webcam frame and save it to the daily directory.
        """
        cap = None

        try:
            cap = cv2.VideoCapture(
                config.WEBCAM_INDEX
            )

            if not cap.isOpened():
                logger.warning(
                    "WebcamPhotoCapture: webcam index %d "
                    "not available",
                    config.WEBCAM_INDEX,
                )
                return False

            cap.set(
                cv2.CAP_PROP_FRAME_WIDTH,
                config.WEBCAM_WIDTH,
            )

            cap.set(
                cv2.CAP_PROP_FRAME_HEIGHT,
                config.WEBCAM_HEIGHT,
            )

            ret, frame = cap.read()

            if not ret or frame is None:
                logger.warning(
                    "WebcamPhotoCapture: frame read failed"
                )
                return False

            day_dir = dated_subdir(
                config.WEBCAM_PHOTOS_DIR
            )

            # Include microseconds to avoid filename collisions.
            timestamp = datetime.now().strftime(
                "%Y%m%d_%H%M%S_%f"
            )

            filename = os.path.join(
                day_dir,
                f"webcam_photo_{timestamp}.jpg",
            )

            success = cv2.imwrite(
                filename,
                frame,
            )

            if not success:
                logger.warning(
                    "WebcamPhotoCapture: failed to write "
                    "image: %s",
                    filename,
                )
                return False

            self._last_capture = time.time()

            logger.info(
                "Webcam photo saved: %s",
                filename,
            )

            return True

        except Exception:
            logger.exception(
                "Error in webcam photo capture"
            )
            return False

        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Agent watchdog
    # ------------------------------------------------------------------

    def _agent_watchdog_loop(self):
        """
        Monitor the user-session webcam agent.

        The Windows service runs in Session 0. The webcam agent runs
        inside the active interactive user session.

        If the active console session changes, the old agent is stopped
        and a new agent is spawned in the new active session.
        """
        try:
            import win32event
            import win32process
            import win32api
            import win32ts
        except ImportError:
            logger.warning(
                "Webcam agent watchdog unavailable: "
                "pywin32 is not installed."
            )
            return

        while not self._stop_event.wait(10):

            with self._agent_lock:
                handle = self._agent_handle
                agent_session_id = self._agent_session_id

            if handle is None:
                continue

            # ----------------------------------------------------------
            # Check active Windows console session
            # ----------------------------------------------------------

            try:
                active_session_id = (
                    win32ts.WTSGetActiveConsoleSessionId()
                )
            except Exception as exc:
                logger.warning(
                    "Could not determine active console session: %s",
                    exc,
                )
                active_session_id = None

            # ----------------------------------------------------------
            # Session changed
            # ----------------------------------------------------------

            if (
                active_session_id is not None
                and active_session_id != 0xFFFFFFFF
                and agent_session_id is not None
                and active_session_id != agent_session_id
            ):
                logger.info(
                    "Active user session changed: %d -> %d. "
                    "Restarting webcam agent.",
                    agent_session_id,
                    active_session_id,
                )

                # ------------------------------------------------------
                # Detach old agent from our state
                # ------------------------------------------------------

                with self._agent_lock:
                    old_handle = self._agent_handle
                    old_stop_file = self._agent_stop_file

                    self._agent_handle = None
                    self._agent_stop_file = None
                    self._agent_session_id = None

                # ------------------------------------------------------
                # Ask old agent to stop
                # ------------------------------------------------------

                if old_stop_file:
                    try:
                        with open(old_stop_file, "w", encoding="utf-8"):
                            pass
                    except OSError as exc:
                        logger.debug(
                            "Could not create old webcam agent "
                            "stop file: %s",
                            exc,
                        )

                # ------------------------------------------------------
                # Wait for old agent
                # ------------------------------------------------------

                if old_handle is not None:
                    try:
                        wait_rc = win32event.WaitForSingleObject(
                            old_handle,
                            3000,
                        )

                        if wait_rc != win32event.WAIT_OBJECT_0:
                            try:
                                win32process.TerminateProcess(
                                    old_handle,
                                    0,
                                )
                            except Exception as exc:
                                logger.debug(
                                    "Could not terminate old webcam "
                                    "agent: %s",
                                    exc,
                                )

                    except Exception as exc:
                        logger.debug(
                            "Error waiting for old webcam agent: %s",
                            exc,
                        )

                    try:
                        win32api.CloseHandle(old_handle)
                    except Exception:
                        pass

                # ------------------------------------------------------
                # Remove old stop file
                # ------------------------------------------------------

                if old_stop_file:
                    try:
                        if os.path.exists(old_stop_file):
                            os.remove(old_stop_file)
                    except OSError:
                        pass

                # ------------------------------------------------------
                # Create a fresh stop file
                # ------------------------------------------------------

                new_stop_file = os.path.join(
                    config.LOGS_DIR,
                    f"webcam_agent_stop_{uuid.uuid4().hex}.flag",
                )

                diag_log_file = os.path.join(
                    config.LOGS_DIR,
                    "webcam_agent.log",
                )

                with self._agent_lock:
                    self._agent_stop_file = new_stop_file

                # ------------------------------------------------------
                # Spawn in the new active session
                # ------------------------------------------------------

                spawned = _spawn_agent_in_user_session(
                    config.WEBCAM_PHOTOS_DIR,
                    diag_log_file,
                    new_stop_file,
                )

                if spawned is not None:
                    new_handle, new_session_id = spawned

                    with self._agent_lock:
                        self._agent_handle = new_handle
                        self._agent_session_id = new_session_id

                    logger.info(
                        "Webcam agent successfully moved to "
                        "user session %d",
                        new_session_id,
                    )
                else:
                    logger.warning(
                        "Failed to respawn webcam agent after "
                        "session change"
                    )

                continue

            # ----------------------------------------------------------
            # Check whether current agent exited
            # ----------------------------------------------------------

            status = win32event.WaitForSingleObject(
                handle,
                0,
            )

            if status != win32event.WAIT_OBJECT_0:
                continue

            try:
                exit_code = win32process.GetExitCodeProcess(
                    handle
                )
            except Exception:
                exit_code = -1

            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass

            with self._agent_lock:
                if self._agent_handle is handle:
                    self._agent_handle = None
                    self._agent_session_id = None

            if self._stop_event.is_set():
                break

            logger.warning(
                "Webcam agent exited unexpectedly "
                "(code %s); attempting restart",
                exit_code,
            )

            # ----------------------------------------------------------
            # Fresh stop file for restarted agent
            # ----------------------------------------------------------

            old_stop_file = self._agent_stop_file

            if old_stop_file:
                try:
                    if os.path.exists(old_stop_file):
                        os.remove(old_stop_file)
                except OSError:
                    pass

            new_stop_file = os.path.join(
                config.LOGS_DIR,
                f"webcam_agent_stop_{uuid.uuid4().hex}.flag",
            )

            diag_log_file = os.path.join(
                config.LOGS_DIR,
                "webcam_agent.log",
            )

            with self._agent_lock:
                self._agent_stop_file = new_stop_file

            spawned = _spawn_agent_in_user_session(
                config.WEBCAM_PHOTOS_DIR,
                diag_log_file,
                new_stop_file,
            )

            if spawned is not None:
                new_handle, new_session_id = spawned

                with self._agent_lock:
                    self._agent_handle = new_handle
                    self._agent_session_id = new_session_id

                logger.info(
                    "Webcam agent restarted in user session %d",
                    new_session_id,
                )

            else:
                logger.warning(
                    "Webcam agent restart failed; will retry"
                )