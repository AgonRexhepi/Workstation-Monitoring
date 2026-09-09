"""
Unit tests for the Workstation Monitoring application.

These tests do not require a display, camera, or Windows service –
they validate configuration, storage helpers, and dashboard routing.
"""

import os
import sys
import time
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Patch heavy native dependencies BEFORE importing application modules.
# ---------------------------------------------------------------------------
# mss (screen capture) – not available in CI / Linux
sys.modules.setdefault("mss", MagicMock())
sys.modules.setdefault("mss.tools", MagicMock())

# cv2 (OpenCV) – may not be installed in CI
cv2_mock = MagicMock()
sys.modules.setdefault("cv2", cv2_mock)

# numpy – required by cv2 and screen.py
sys.modules.setdefault("numpy", MagicMock())

# psutil – may not be installed in CI
sys.modules.setdefault("psutil", MagicMock())

# pynput (keyboard listener) – needs a display / uinput on Linux
pynput_mock = MagicMock()
sys.modules.setdefault("pynput", pynput_mock)
sys.modules.setdefault("pynput.keyboard", pynput_mock.keyboard)
sys.modules.setdefault("pynput.mouse", pynput_mock.mouse)

# pywin32 – Windows only
sys.modules.setdefault("win32serviceutil", MagicMock())
sys.modules.setdefault("win32service", MagicMock())
sys.modules.setdefault("win32event", MagicMock())
sys.modules.setdefault("servicemanager", MagicMock())

# Insert the project root so imports resolve
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.abspath(ROOT))

import config
import storage.manager as store


class TestConfig(unittest.TestCase):
    def test_required_attrs(self):
        for attr in (
            "BASE_DIR",
            "RECORDINGS_DIR",
            "SCREENSHOTS_DIR",
            "LOGS_DIR",
            "WEBCAM_DIR",
            "SCREEN_FPS",
            "SCREENSHOT_INTERVAL",
            "WEBCAM_FPS",
            "SERVICE_NAME",
            "DASHBOARD_HOST",
            "DASHBOARD_PORT",
            "MAX_STORAGE_MB",
            "DELETE_DATA",
            # Feature flags
            "WEBCAM_RECORD",
            "WEBCAM_PHOTO",
            "WEBCAM_PHOTO_ON_ACTIVITY",
            "SCREEN_RECORD",
            "SCREEN_SHOT",
            "SCREENSHOT_ON_ACTIVITY",
            "KEY_LOGGER",
            # Webcam photo settings
            "WEBCAM_PHOTOS_DIR",
            "WEBCAM_PHOTO_INTERVAL",
        ):
            self.assertTrue(hasattr(config, attr), f"config.{attr} missing")

    def test_feature_flags_are_int(self):
        for flag in ("WEBCAM_RECORD", "WEBCAM_PHOTO", "SCREEN_RECORD", "SCREEN_SHOT", "KEY_LOGGER"):
            self.assertIn(getattr(config, flag), (0, 1), f"config.{flag} must be 0 or 1")

    def test_webcam_photo_interval_positive(self):
        self.assertGreater(config.WEBCAM_PHOTO_INTERVAL, 0)

    def test_fps_positive(self):
        self.assertGreater(config.SCREEN_FPS, 0)
        self.assertGreater(config.WEBCAM_FPS, 0)

    def test_dashboard_port_range(self):
        self.assertGreater(config.DASHBOARD_PORT, 0)
        self.assertLess(config.DASHBOARD_PORT, 65536)

    def test_storage_size_positive(self):
        self.assertGreater(config.MAX_STORAGE_MB, 0)


class TestStorageManager(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # Redirect storage paths to a temp dir so tests are isolated
        self._orig_dirs = {
            "RECORDINGS_DIR": config.RECORDINGS_DIR,
            "SCREENSHOTS_DIR": config.SCREENSHOTS_DIR,
            "LOGS_DIR": config.LOGS_DIR,
            "WEBCAM_DIR": config.WEBCAM_DIR,
            "WEBCAM_PHOTOS_DIR": config.WEBCAM_PHOTOS_DIR,
            "KEYBOARD_DIR": config.KEYBOARD_DIR,
        }
        config.RECORDINGS_DIR = os.path.join(self._tmp, "recordings")
        config.SCREENSHOTS_DIR = os.path.join(self._tmp, "screenshots")
        config.LOGS_DIR = os.path.join(self._tmp, "logs")
        config.WEBCAM_DIR = os.path.join(self._tmp, "webcam")
        config.WEBCAM_PHOTOS_DIR = os.path.join(self._tmp, "webcam_photos")
        config.KEYBOARD_DIR = os.path.join(self._tmp, "logs", "keyboard.log")

    def tearDown(self):
        for k, v in self._orig_dirs.items():
            setattr(config, k, v)
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ensure_directories_creates_dirs(self):
        store.ensure_directories()
        for attr in ("RECORDINGS_DIR", "SCREENSHOTS_DIR", "LOGS_DIR", "WEBCAM_DIR", "WEBCAM_PHOTOS_DIR"):
            self.assertTrue(
                os.path.isdir(getattr(config, attr)), f"{attr} not created"
            )

    def test_list_empty_returns_empty(self):
        store.ensure_directories()
        self.assertEqual(store.list_screen_recordings(), [])
        self.assertEqual(store.list_webcam_recordings(), [])
        self.assertEqual(store.list_screenshots(), [])
        self.assertEqual(store.list_webcam_photos(), [])

    def test_list_files_found(self):
        store.ensure_directories()
        # Create a dummy recording
        rec_path = Path(config.RECORDINGS_DIR) / "screen_20240101_120000.mp4"
        rec_path.write_bytes(b"\x00" * 1024)
        results = store.list_screen_recordings()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], rec_path.name)
        self.assertEqual(results[0]["size_bytes"], 1024)

    def test_keyboard_log_empty(self):
        store.ensure_directories()
        lines = store.get_keyboard_log_lines()
        self.assertEqual(lines, [])

    def test_keyboard_log_reads_lines(self):
        store.ensure_directories()
        log_path = Path(config.KEYBOARD_DIR)
        log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
        lines = store.get_keyboard_log_lines()
        self.assertEqual(len(lines), 3)

    def test_keyboard_log_max_lines(self):
        store.ensure_directories()
        log_path = Path(config.KEYBOARD_DIR)
        log_path.write_text(
            "\n".join(f"entry {i}" for i in range(1000)) + "\n", encoding="utf-8"
        )
        lines = store.get_keyboard_log_lines(max_lines=500)
        self.assertLessEqual(len(lines), 500)

    def test_keyboard_log_by_day_empty(self):
        store.ensure_directories()
        days = store.get_keyboard_log_by_day()
        self.assertEqual(days, [])

    def test_keyboard_log_by_day_groups_by_date(self):
        store.ensure_directories()
        log_path = Path(config.KEYBOARD_DIR)
        log_path.write_text(
            "2024-01-01T10:00:00.000000 a\n"
            "2024-01-01T10:00:01.000000 b\n"
            "2024-01-02T11:00:00.000000 c\n",
            encoding="utf-8",
        )
        days = store.get_keyboard_log_by_day()
        self.assertEqual(len(days), 2)
        self.assertEqual(days[0]["date"], "2024-01-01")
        self.assertEqual(len(days[0]["entries"]), 2)
        self.assertEqual(days[0]["entries"][0]["key"], "a")
        self.assertEqual(days[0]["entries"][0]["time"], "10:00:00")
        self.assertEqual(days[1]["date"], "2024-01-02")
        self.assertEqual(len(days[1]["entries"]), 1)

    def test_keyboard_log_by_day_all_lines(self):
        """All lines should be returned (no 500-row cap)."""
        store.ensure_directories()
        log_path = Path(config.KEYBOARD_DIR)
        entries = "\n".join(
            f"2024-01-01T10:00:{i:02d}.000000 x" for i in range(60)
        ) + "\n"
        log_path.write_text(entries, encoding="utf-8")
        days = store.get_keyboard_log_by_day()
        self.assertEqual(len(days), 1)
        self.assertEqual(len(days[0]["entries"]), 60)

    def test_storage_summary_keys(self):
        store.ensure_directories()
        summary = store.storage_summary()
        for key in ("total_mb", "max_mb", "recordings", "webcam", "screenshots", "webcam_photos"):
            self.assertIn(key, summary)

    def test_storage_summary_includes_daily_counts(self):
        store.ensure_directories()
        screenshot = Path(config.SCREENSHOTS_DIR) / "shot_today.png"
        webcam_photo = Path(config.WEBCAM_PHOTOS_DIR) / "webcam_today.jpg"
        screenshot.write_bytes(b"x")
        webcam_photo.write_bytes(b"x")

        old_file = Path(config.SCREENSHOTS_DIR) / "shot_old.png"
        old_file.write_bytes(b"x")
        old_time = time.time() - 2 * 86400
        os.utime(old_file, (old_time, old_time))

        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        Path(config.KEYBOARD_DIR).write_text(
            f"{today}T10:00:00.000000 a\n"
            f"{today}T11:00:00.000000 b\n"
            f"{yesterday}T09:00:00.000000 c\n",
            encoding="utf-8",
        )

        summary = store.storage_summary()
        self.assertEqual(summary["screenshots"], 2)
        self.assertEqual(summary["screenshots_today"], 1)
        self.assertEqual(summary["webcam_photos"], 1)
        self.assertEqual(summary["webcam_photos_today"], 1)
        self.assertEqual(summary["keylogger_days"], 2)
        self.assertEqual(summary["keylogger_days_today"], 1)

    def test_age_policy_removes_old_file(self):
        store.ensure_directories()
        old_file = Path(config.RECORDINGS_DIR) / "old.mp4"
        old_file.write_bytes(b"x")
        # Set mtime to DELETE_DATA + 1 days ago
        old_time = time.time() - (config.DELETE_DATA + 1) * 86400
        os.utime(old_file, (old_time, old_time))

        mgr = store.StorageManager()
        mgr._enforce_age_policy()
        self.assertFalse(old_file.exists())

    def test_age_policy_keeps_new_file(self):
        store.ensure_directories()
        new_file = Path(config.RECORDINGS_DIR) / "new.mp4"
        new_file.write_bytes(b"x")

        mgr = store.StorageManager()
        mgr._enforce_age_policy()
        self.assertTrue(new_file.exists())

    def test_size_policy_removes_oldest(self):
        store.ensure_directories()
        # Create a file that exceeds the limit
        orig_max = config.MAX_STORAGE_MB
        config.MAX_STORAGE_MB = 0  # 0 MB limit → every file is over limit

        big_file = Path(config.RECORDINGS_DIR) / "big.mp4"
        big_file.write_bytes(b"x" * 1024)

        mgr = store.StorageManager()
        mgr._enforce_size_policy()
        self.assertFalse(big_file.exists())

        config.MAX_STORAGE_MB = orig_max

    def test_cleanup_schedule_helpers(self):
        mgr = store.StorageManager()
        before_cleanup = datetime(2024, 1, 1, 7, 30, 0)
        after_cleanup = datetime(2024, 1, 1, 8, 30, 0)

        self.assertFalse(mgr._should_run_cleanup_now(before_cleanup))
        self.assertEqual(mgr._next_cleanup_time(before_cleanup), datetime(2024, 1, 1, 8, 0, 0))
        self.assertEqual(mgr._seconds_until_next_cleanup(before_cleanup), 1800.0)

        self.assertTrue(mgr._should_run_cleanup_now(after_cleanup))
        mgr._last_cleanup_date = after_cleanup.date()
        self.assertFalse(mgr._should_run_cleanup_now(after_cleanup))
        self.assertEqual(mgr._next_cleanup_time(after_cleanup), datetime(2024, 1, 2, 8, 0, 0))


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        config.RECORDINGS_DIR = os.path.join(self._tmp, "recordings")
        config.SCREENSHOTS_DIR = os.path.join(self._tmp, "screenshots")
        config.LOGS_DIR = os.path.join(self._tmp, "logs")
        config.WEBCAM_DIR = os.path.join(self._tmp, "webcam")
        config.WEBCAM_PHOTOS_DIR = os.path.join(self._tmp, "webcam_photos")
        config.KEYBOARD_DIR = os.path.join(self._tmp, "logs", "keyboard.log")
        store.ensure_directories()

        from dashboard.app import app as flask_app
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-secret"
        flask_app.config["WTF_CSRF_ENABLED"] = False
        self._client = flask_app.test_client()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _login(self):
        with patch.object(
            sys.modules.get("dashboard.app") or __import__("dashboard.app"),
            "_check_password",
            return_value=True,
        ):
            return self._client.post(
                "/login",
                data={"password": "supervisor"},
                follow_redirects=True,
            )

    def test_login_page_accessible(self):
        resp = self._client.get("/login")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Supervisor Login", resp.data)

    def test_redirect_to_login_when_unauthenticated(self):
        resp = self._client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_index_accessible_after_login(self):
        self._login()
        resp = self._client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_recordings_page(self):
        self._login()
        resp = self._client.get("/recordings")
        self.assertEqual(resp.status_code, 200)

    def test_webcam_page(self):
        self._login()
        resp = self._client.get("/webcam")
        self.assertEqual(resp.status_code, 200)

    def test_webcam_photos_page(self):
        self._login()
        resp = self._client.get("/webcam_photos")
        self.assertEqual(resp.status_code, 200)

    def test_screenshots_page(self):
        self._login()
        resp = self._client.get("/screenshots")
        self.assertEqual(resp.status_code, 200)

    def test_webcam_photos_support_filters_and_pagination(self):
        self._login()
        base_time = time.time()
        for index in range(11):
            path = Path(config.WEBCAM_PHOTOS_DIR) / f"match_{index:02d}.jpg"
            path.write_bytes(b"x")
            timestamp = base_time - (11 - index) * 60
            os.utime(path, (timestamp, timestamp))
        (Path(config.WEBCAM_PHOTOS_DIR) / "ignore.jpg").write_bytes(b"x")

        resp = self._client.get("/webcam_photos?search=match&page=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Page 1 of 2", resp.data)
        self.assertIn(b"match_10.jpg", resp.data)
        self.assertNotIn(b"match_00.jpg", resp.data)
        self.assertNotIn(b"ignore.jpg", resp.data)

        resp = self._client.get("/webcam_photos?search=match&page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"match_00.jpg", resp.data)

    def test_screenshots_support_filters_and_pagination(self):
        self._login()
        base_time = time.time()
        for index in range(11):
            path = Path(config.SCREENSHOTS_DIR) / f"needle_{index:02d}.png"
            path.write_bytes(b"x")
            timestamp = base_time - (11 - index) * 60
            os.utime(path, (timestamp, timestamp))
        old_path = Path(config.SCREENSHOTS_DIR) / "needle_old.png"
        old_path.write_bytes(b"x")
        old_timestamp = base_time - 3 * 86400
        os.utime(old_path, (old_timestamp, old_timestamp))

        date_from = datetime.fromtimestamp(base_time - 3600).strftime("%Y-%m-%dT%H:%M")
        resp = self._client.get(f"/screenshots?search=needle&date_from={date_from}&page=1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Page 1 of 2", resp.data)
        self.assertIn(b"needle_10.png", resp.data)
        self.assertNotIn(b"needle_00.png", resp.data)
        self.assertNotIn(b"needle_old.png", resp.data)

        resp = self._client.get(f"/screenshots?search=needle&date_from={date_from}&page=2")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"needle_00.png", resp.data)

    def test_keyboard_page(self):
        self._login()
        resp = self._client.get("/keyboard")
        self.assertEqual(resp.status_code, 200)

    def test_system_page(self):
        self._login()
        resp = self._client.get("/system")
        self.assertEqual(resp.status_code, 200)

    def test_download_blocked_outside_allowed_dirs(self):
        self._login()
        resp = self._client.get("/download?path=/etc/passwd")
        self.assertEqual(resp.status_code, 403)

    def test_download_missing_file_returns_404(self):
        self._login()
        safe_path = os.path.join(config.RECORDINGS_DIR, "nonexistent.mp4")
        resp = self._client.get(f"/download?path={safe_path}")
        self.assertEqual(resp.status_code, 404)

    def test_logout_clears_session(self):
        self._login()
        resp = self._client.get("/logout", follow_redirects=True)
        self.assertIn(b"Supervisor Login", resp.data)


class TestWebcamPhotoCapture(unittest.TestCase):
    """Tests for the periodic webcam snapshot feature."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_photos_dir = config.WEBCAM_PHOTOS_DIR
        self._orig_interval = config.WEBCAM_PHOTO_INTERVAL
        config.WEBCAM_PHOTOS_DIR = os.path.join(self._tmp, "webcam_photos")
        config.WEBCAM_PHOTO_INTERVAL = 60

    def tearDown(self):
        config.WEBCAM_PHOTOS_DIR = self._orig_photos_dir
        config.WEBCAM_PHOTO_INTERVAL = self._orig_interval
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_start_stop(self):
        from monitoring.webcam import WebcamPhotoCapture
        cap = WebcamPhotoCapture()
        cap.start()
        self.assertTrue(cap._thread.is_alive())
        cap.stop()
        self.assertFalse(cap._thread.is_alive())

    def test_double_start_is_idempotent(self):
        from monitoring.webcam import WebcamPhotoCapture
        cap = WebcamPhotoCapture()
        cap.start()
        thread_id = id(cap._thread)
        cap.start()  # second call should be a no-op
        self.assertEqual(id(cap._thread), thread_id)
        cap.stop()


class TestScreenRecorderScreenshot(unittest.TestCase):
    """Tests for the activity-triggered screenshot mode in ScreenRecorder."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_screenshots_dir = config.SCREENSHOTS_DIR
        self._orig_interval = config.SCREENSHOT_INTERVAL
        self._orig_on_activity = config.SCREENSHOT_ON_ACTIVITY
        config.SCREENSHOTS_DIR = os.path.join(self._tmp, "screenshots")
        config.SCREENSHOT_INTERVAL = 60
        config.SCREENSHOT_ON_ACTIVITY = True

    def tearDown(self):
        config.SCREENSHOTS_DIR = self._orig_screenshots_dir
        config.SCREENSHOT_INTERVAL = self._orig_interval
        config.SCREENSHOT_ON_ACTIVITY = self._orig_on_activity
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_start_stop_activity_mode(self):
        from monitoring.screen import ScreenRecorder
        rec = ScreenRecorder()
        rec.start(record=False, screenshot=True)
        self.assertTrue(rec._screenshot_thread.is_alive())
        rec.stop()
        rec._screenshot_thread.join(timeout=5)
        self.assertFalse(rec._screenshot_thread.is_alive())

    def test_start_stop_timer_mode(self):
        config.SCREENSHOT_ON_ACTIVITY = False
        from monitoring.screen import ScreenRecorder
        rec = ScreenRecorder()
        rec.start(record=False, screenshot=True)
        self.assertTrue(rec._screenshot_thread.is_alive())
        rec.stop()
        rec._screenshot_thread.join(timeout=5)
        self.assertFalse(rec._screenshot_thread.is_alive())

    def test_double_start_is_idempotent(self):
        from monitoring.screen import ScreenRecorder
        rec = ScreenRecorder()
        rec.start(record=False, screenshot=True)
        thread_id = id(rec._screenshot_thread)
        rec.start(record=False, screenshot=True)  # second call should be a no-op
        self.assertEqual(id(rec._screenshot_thread), thread_id)
        rec.stop()


if __name__ == "__main__":
    unittest.main()
