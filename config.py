"""
Central configuration for the Workstation Monitoring application.
Adjust these values to match your institution's requirements.
"""

import os

# ------------------------------------------------------------------
# Base storage directory
# ------------------------------------------------------------------
BASE_DIR = os.path.join("C:\\", "WorkstationMonitor")

RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
SCREENSHOTS_DIR = os.path.join(BASE_DIR, "screenshots")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
WEBCAM_DIR = os.path.join(BASE_DIR, "webcam")

# ------------------------------------------------------------------
# Screen recording
# ------------------------------------------------------------------
SCREEN_FPS = 5                    # frames per second for screen capture
SCREENSHOT_INTERVAL = 30          # seconds between automatic screenshots
SCREEN_CODEC = "H264"            # fourcc codec for screen video (H264 better supported)
SCREEN_WRITER_TIMEOUT = 10        # seconds before giving up on VideoWriter init

# ------------------------------------------------------------------
# Webcam recording
# ------------------------------------------------------------------
WEBCAM_INDEX = 0                  # camera device index
WEBCAM_FPS = 10                   # frames per second for webcam capture
WEBCAM_WIDTH = 640
WEBCAM_HEIGHT = 480
WEBCAM_CODEC = "H264"            # H264 codec for better compatibility

# ------------------------------------------------------------------
# Keyboard monitoring
# ------------------------------------------------------------------
KEYBOARD_LOG_FILE = os.path.join(LOGS_DIR, "keyboard.log")
KEYBOARD_FLUSH_INTERVAL = 5      # seconds between log flushes

# ------------------------------------------------------------------
# Service settings
# ------------------------------------------------------------------
SERVICE_NAME = "WorkstationMonitorSvc"
SERVICE_DISPLAY_NAME = "Workstation Monitoring Service"
SERVICE_DESCRIPTION = (
    "Monitors student workstations during examinations in compliance "
    "with the institution's academic regulations."
)

# ------------------------------------------------------------------
# Dashboard settings
# ------------------------------------------------------------------
DASHBOARD_HOST = "127.0.0.1"     # listen on loopback only
DASHBOARD_PORT = 5000
# Change this to a strong secret key in production
DASHBOARD_SECRET_KEY = os.environ.get(
    "MONITOR_SECRET_KEY", "change-me-in-production"
)
# Supervisor password – set via environment variable in production.
# The plain-text value is compared directly; use a long, random password.
SUPERVISOR_PASSWORD = os.environ.get("MONITOR_SUPERVISOR_PASSWORD", "supervisor")

# ------------------------------------------------------------------
# Recording segment duration
# ------------------------------------------------------------------
SEGMENT_DURATION_SECONDS = 600  # 10-minute video segments

# ------------------------------------------------------------------
# Storage / retention
# ------------------------------------------------------------------
# Maximum age (in days) before recordings are automatically purged
MAX_RECORDING_AGE_DAYS = 30
# Maximum total disk usage in MB before oldest files are removed
MAX_STORAGE_MB = 10_240           # 10 GB
