"""
Windows Service wrapper for the Workstation Monitoring application.

Usage (run as Administrator):
    python service.py install   – install and configure the service
    python service.py start     – start the service
    python service.py stop      – stop the service
    python service.py remove    – uninstall the service
    python service.py debug     – run in console (for development)

The service is configured to restart automatically on failure.
"""

import os
import sys
import logging
import threading

# ---------------------------------------------------------------------------
# Path setup so that all sibling packages resolve correctly regardless of cwd.
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import config
import storage.manager as store_manager
from monitoring.screen import ScreenRecorder
from monitoring.webcam import WebcamRecorder, WebcamPhotoCapture
from monitoring.keyboard_monitor import KeyboardMonitor
from dashboard.app import run_dashboard

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
os.makedirs(config.LOGS_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(config.LOGS_DIR, "monitor_service.log"), encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core monitoring orchestrator (platform-independent)
# ---------------------------------------------------------------------------

class MonitoringOrchestrator:
    """Starts and stops all monitoring components."""

    def __init__(self):
        self._screen = (
            ScreenRecorder() if (config.SCREEN_RECORD or config.SCREEN_SHOT) else None
        )
        self._webcam = WebcamRecorder() if config.WEBCAM_RECORD else None
        self._webcam_photo = WebcamPhotoCapture() if config.WEBCAM_PHOTO else None
        self._keyboard = KeyboardMonitor() if config.KEY_LOGGER else None
        self._storage = store_manager.StorageManager()
        self._dashboard_thread: threading.Thread | None = None

    def start(self):
        logger.info("Starting monitoring components …")
        store_manager.ensure_directories()
        self._storage.start()
        if self._keyboard:
            self._keyboard.start()
        if self._screen:
            self._screen.start(
                record=bool(config.SCREEN_RECORD),
                screenshot=bool(config.SCREEN_SHOT),
            )
        if self._webcam:
            self._webcam.start()
        if self._webcam_photo:
            self._webcam_photo.start()
        self._dashboard_thread = threading.Thread(
            target=run_dashboard, daemon=True, name="dashboard"
        )
        self._dashboard_thread.start()
        logger.info(
            "All components started. Dashboard at http://%s:%d/",
            config.DASHBOARD_HOST,
            config.DASHBOARD_PORT,
        )

    def stop(self):
        logger.info("Stopping monitoring components …")
        if self._screen:
            self._screen.stop()
        if self._webcam:
            self._webcam.stop()
        if self._webcam_photo:
            self._webcam_photo.stop()
        if self._keyboard:
            self._keyboard.stop()
        self._storage.stop()
        logger.info("All components stopped.")


# ---------------------------------------------------------------------------
# Windows Service (pywin32)
# ---------------------------------------------------------------------------

try:
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager

    class WorkstationMonitorService(win32serviceutil.ServiceFramework):
        _svc_name_ = config.SERVICE_NAME
        _svc_display_name_ = config.SERVICE_DISPLAY_NAME
        _svc_description_ = config.SERVICE_DESCRIPTION
        _svc_start_type_ = win32service.SERVICE_AUTO_START

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._orchestrator = None

        def SvcStop(self):
            logger.info("Windows Service stop requested.")

            self.ReportServiceStatus(
                win32service.SERVICE_STOP_PENDING
            )

            win32event.SetEvent(self._stop_event)

            if self._orchestrator:
                try:
                    self._orchestrator.stop()
                except Exception:
                    logger.exception("Error while stopping service")

            logger.info("Windows Service stopped.")

        def SvcDoRun(self):
            try:
                servicemanager.LogInfoMsg(
                    f"{self._svc_name_} is starting..."
                )

                logger.info("Windows Service is starting...")

                self._orchestrator = MonitoringOrchestrator()
                self._orchestrator.start()

                logger.info("Windows Service started successfully.")

                win32event.WaitForSingleObject(
                    self._stop_event,
                    win32event.INFINITE
                )

            except Exception:
                logger.exception("FATAL ERROR while starting Windows Service")

                servicemanager.LogErrorMsg(
                    f"{self._svc_name_} failed to start. "
                    f"Check monitor_service.log"
                )

                raise

    _WINDOWS_SERVICE_AVAILABLE = True

except ImportError:
    _WINDOWS_SERVICE_AVAILABLE = False
    logger.warning(
        "pywin32 not available – Windows Service mode disabled. "
        "Use 'python service.py debug' to run in console mode."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower() == "debug":
        # Console / development mode
        import signal

        orchestrator = MonitoringOrchestrator()
        orchestrator.start()

        stop_evt = threading.Event()

        signal.signal(
            signal.SIGINT,
            lambda *_: stop_evt.set()
        )

        signal.signal(
            signal.SIGTERM,
            lambda *_: stop_evt.set()
        )

        logger.info("Running in debug mode. Press Ctrl+C to stop.")

        try:
            stop_evt.wait()
        finally:
            orchestrator.stop()

    elif _WINDOWS_SERVICE_AVAILABLE:
        # install / start / stop / remove and SCM dispatch
        win32serviceutil.HandleCommandLine(
            WorkstationMonitorService
        )

    else:
        print(
            "pywin32 is not installed. Install it with:\n"
            "    pip install pywin32\n"
            "Or run in debug mode:\n"
            "    python service.py debug"
        )
        sys.exit(1)
