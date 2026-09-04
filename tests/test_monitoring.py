"""
Unit tests for the Workstation Monitoring application.

These tests do not require a display, camera, or Windows service –
they validate configuration, storage helpers, and dashboard routing.
"""

import os
import sys
import time
import tempfile
import unittest
from unittest.mock import patch, MagicMock
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

# pynput (keyboard listener) – needs a display / uinput on Linux
pynput_mock = MagicMock()
sys.modules.setdefault("pynput", pynput_mock)
sys.modules.setdefault("pynput.keyboard", pynput_mock.keyboard)

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
        ):
            self.assertTrue(hasattr(config, attr), f"config.{attr} missing")

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
            "KEYBOARD_LOG_FILE": config.KEYBOARD_LOG_FILE,
        }
        config.RECORDINGS_DIR = os.path.join(self._tmp, "recordings")
        config.SCREENSHOTS_DIR = os.path.join(self._tmp, "screenshots")
        config.LOGS_DIR = os.path.join(self._tmp, "logs")
        config.WEBCAM_DIR = os.path.join(self._tmp, "webcam")
        config.KEYBOARD_LOG_FILE = os.path.join(self._tmp, "logs", "keyboard.log")

    def tearDown(self):
        for k, v in self._orig_dirs.items():
            setattr(config, k, v)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ensure_directories_creates_dirs(self):
        store.ensure_directories()
        for attr in ("RECORDINGS_DIR", "SCREENSHOTS_DIR", "LOGS_DIR", "WEBCAM_DIR"):
            self.assertTrue(
                os.path.isdir(getattr(config, attr)), f"{attr} not created"
            )

    def test_list_empty_returns_empty(self):
        store.ensure_directories()
        self.assertEqual(store.list_screen_recordings(), [])
        self.assertEqual(store.list_webcam_recordings(), [])
        self.assertEqual(store.list_screenshots(), [])

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
        log_path = Path(config.KEYBOARD_LOG_FILE)
        log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
        lines = store.get_keyboard_log_lines()
        self.assertEqual(len(lines), 3)

    def test_keyboard_log_max_lines(self):
        store.ensure_directories()
        log_path = Path(config.KEYBOARD_LOG_FILE)
        log_path.write_text(
            "\n".join(f"entry {i}" for i in range(1000)) + "\n", encoding="utf-8"
        )
        lines = store.get_keyboard_log_lines(max_lines=500)
        self.assertLessEqual(len(lines), 500)

    def test_storage_summary_keys(self):
        store.ensure_directories()
        summary = store.storage_summary()
        for key in ("total_mb", "max_mb", "recordings", "webcam", "screenshots"):
            self.assertIn(key, summary)

    def test_age_policy_removes_old_file(self):
        store.ensure_directories()
        old_file = Path(config.RECORDINGS_DIR) / "old.mp4"
        old_file.write_bytes(b"x")
        # Set mtime to 31 days ago
        old_time = time.time() - (config.MAX_RECORDING_AGE_DAYS + 1) * 86400
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


class TestDashboard(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        config.RECORDINGS_DIR = os.path.join(self._tmp, "recordings")
        config.SCREENSHOTS_DIR = os.path.join(self._tmp, "screenshots")
        config.LOGS_DIR = os.path.join(self._tmp, "logs")
        config.WEBCAM_DIR = os.path.join(self._tmp, "webcam")
        config.KEYBOARD_LOG_FILE = os.path.join(self._tmp, "logs", "keyboard.log")
        store.ensure_directories()

        from dashboard.app import app as flask_app
        flask_app.config["TESTING"] = True
        flask_app.config["SECRET_KEY"] = "test-secret"
        flask_app.config["WTF_CSRF_ENABLED"] = False
        self._client = flask_app.test_client()

    def tearDown(self):
        import shutil
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

    def test_screenshots_page(self):
        self._login()
        resp = self._client.get("/screenshots")
        self.assertEqual(resp.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
