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
SCREENSHOT_INTERVAL = 60         # seconds between automatic screenshots (1 minute)
SCREEN_CODEC = "mp4v"            # default codec with broad OpenCV/FFmpeg availability
SCREEN_WRITER_TIMEOUT = 10        # seconds before giving up on VideoWriter init

# ------------------------------------------------------------------
# Webcam recording
# ------------------------------------------------------------------
WEBCAM_INDEX = 0                  # camera device index
WEBCAM_FPS = 10                   # frames per second for webcam capture
WEBCAM_WIDTH = 640
WEBCAM_HEIGHT = 480
WEBCAM_CODEC = "mp4v"            # default codec with broad OpenCV/FFmpeg availability

# ------------------------------------------------------------------
# Webcam photo settings
# ------------------------------------------------------------------
WEBCAM_PHOTOS_DIR      = os.path.join(BASE_DIR, "webcam_photos")
WEBCAM_PHOTO_INTERVAL  = 60   # seconds between webcam snapshots (1 minute)

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
    "MONITOR_SECRET_KEY", "S3cr3tK3yD43H804R6"
)
# Supervisor password – set via environment variable in production.
# The plain-text value is compared directly; use a long, random password.
SUPERVISOR_PASSWORD = os.environ.get("MONITOR_SUPERVISOR_PASSWORD", "supervisor")

# ------------------------------------------------------------------
# Recording segment duration
# ------------------------------------------------------------------
SEGMENT_DURATION_SECONDS = 1800  # 30-minute video segments

# ------------------------------------------------------------------
# Storage / retention
# ------------------------------------------------------------------
# DELETE_DATA: files older than this many days are automatically purged.
DELETE_DATA = 365

# CLEANUP_HOUR: the hour of the day when the storage cleanup runs (0-23)
CLEANUP_HOUR = 8

# Maximum total disk usage in MB before oldest files are removed
MAX_STORAGE_MB = 10_240           # 10 GB

# ------------------------------------------------------------------
# Feature flags  (set to 1 to enable, 0 to disable)
# ------------------------------------------------------------------
WEBCAM_RECORD = 0    # continuous webcam video recording
WEBCAM_PHOTO  = 1    # periodic webcam snapshots (one photo per interval)
# When True, webcam photos are taken on keyboard/mouse activity instead of
# (only) on a fixed timer.  WEBCAM_PHOTO_INTERVAL still acts as the minimum
# gap between consecutive captures.
WEBCAM_PHOTO_ON_ACTIVITY = True
SCREEN_RECORD = 0    # continuous screen video recording
SCREEN_SHOT   = 1    # periodic screenshots
# When True, screenshots are taken on keyboard/mouse activity instead of
# (only) on a fixed timer.  SCREENSHOT_INTERVAL still acts as the minimum
# gap between consecutive captures.
SCREENSHOT_ON_ACTIVITY = True
KEY_LOGGER    = 1    # keyboard activity logging

# Pagination settings for the dashboard
ITEMS_PER_PAGE = 10

