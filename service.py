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
from monitoring.webcam import WebcamRecorder
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
        self._screen = ScreenRecorder()
        self._webcam = WebcamRecorder()
        self._keyboard = KeyboardMonitor()
        self._storage = store_manager.StorageManager()
        self._dashboard_thread: threading.Thread | None = None

    def start(self):
        logger.info("Starting monitoring components …")
        store_manager.ensure_directories()
        self._storage.start()
        self._keyboard.start()
        self._screen.start()
        self._webcam.start()
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
        self._screen.stop()
        self._webcam.stop()
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

        def __init__(self, args):
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
            self._orchestrator = MonitoringOrchestrator()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
            self._orchestrator.stop()

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
            self._orchestrator.start()
            win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)

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
    if len(sys.argv) == 1 and _WINDOWS_SERVICE_AVAILABLE:
        # Called by the Service Control Manager
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(WorkstationMonitorService)
        servicemanager.StartServiceCtrlDispatcher()
    elif len(sys.argv) > 1 and sys.argv[1] == "debug":
        # Console / development mode
        import signal

        orchestrator = MonitoringOrchestrator()
        orchestrator.start()

        stop_evt = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop_evt.set())
        signal.signal(signal.SIGTERM, lambda *_: stop_evt.set())
        logger.info("Running in debug mode. Press Ctrl+C to stop.")
        stop_evt.wait()
        orchestrator.stop()
    elif _WINDOWS_SERVICE_AVAILABLE:
        win32serviceutil.HandleCommandLine(WorkstationMonitorService)
    else:
        print(
            "pywin32 is not installed. Install it with:\n"
            "    pip install pywin32\n"
            "Or run in debug mode:\n"
            "    python service.py debug"
        )
        sys.exit(1)
