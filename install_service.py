"""
install_service.py – helper script that installs and configures the
Workstation Monitoring Windows Service with automatic restart-on-failure.

Run as Administrator:
    python install_service.py
"""

import os
import sys
import subprocess
import logging
import ctypes

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_SCRIPT = os.path.join(BASE_DIR, "service.py")

try:
    import win32service
    import win32serviceutil
    import win32con
    import pywintypes
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False


def install():
    if sys.platform != "win32":
        logger.error("This script is for Windows only.")
        sys.exit(1)

    if not _HAS_WIN32:
        logger.error("pywin32 is not installed. Run: pip install pywin32")
        sys.exit(1)

    if not _is_admin():
        logger.error("Administrator privileges are required to install/start the service.")
        logger.error("Re-run this command in an elevated PowerShell or Command Prompt.")
        sys.exit(1)

    _verify_service_runtime_imports()

    # Install via pywin32 helper
    logger.info("Installing service …")
    result = subprocess.run(
        [sys.executable, SERVICE_SCRIPT, "install"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Service install failed:\n%s", result.stderr)
        sys.exit(1)
    logger.info("Service installed successfully.")

    # Configure automatic restart on failure using sc.exe
    import config
    _configure_failure_actions(config.SERVICE_NAME)

    # Set startup type to Automatic
    result = subprocess.run(
        ["sc", "config", config.SERVICE_NAME, "start=", "auto"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Could not set startup type: %s", result.stderr)
    else:
        logger.info("Service configured for automatic startup.")

    # Start the service
    logger.info("Starting service …")
    result = subprocess.run(
        [sys.executable, SERVICE_SCRIPT, "start"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Could not start service: %s", result.stderr)
    else:
        logger.info("Service started.")


def _is_admin() -> bool:
    """Return True when running with administrator privileges on Windows."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _verify_service_runtime_imports():
    """
    Validate imports using -s (no user site-packages), which matches how
    PythonService commonly runs under SCM service accounts.
    """
    code = (
        "import importlib, sys; "
        "mods=['cv2','flask','mss','numpy','psutil','pynput']; "
        "missing=[m for m in mods if importlib.util.find_spec(m) is None]; "
        "print(','.join(missing)); "
        "sys.exit(1 if missing else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-s", "-c", code],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        missing = (result.stdout or "").strip() or "unknown modules"
        logger.error(
            "Service runtime is missing required modules: %s",
            missing,
        )
        logger.error(
            "Install dependencies for the system interpreter (not user-only site packages)."
        )
        logger.error("Run as Administrator: %s -m pip install -r requirements.txt", sys.executable)
        sys.exit(1)


def _configure_failure_actions(service_name: str):
    """
    Configure sc.exe failure actions: restart after 60 s, three times,
    then restart after 300 s on subsequent failures.
    """
    result = subprocess.run(
        [
            "sc", "failure", service_name,
            "reset=", "86400",          # reset failure count after 1 day
            "actions=", "restart/60000/restart/60000/restart/300000",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "Could not set failure actions (non-critical): %s", result.stderr
        )
    else:
        logger.info("Automatic restart-on-failure configured.")


if __name__ == "__main__":
    install()
