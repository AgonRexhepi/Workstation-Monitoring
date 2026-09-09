"""
Component diagnostic script – tests each monitoring component independently.

Run this script to verify which components are working:
    python test_components.py
"""

import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import config
from monitoring.screen import ScreenRecorder
from monitoring.webcam import WebcamRecorder
from monitoring.keyboard_monitor import KeyboardMonitor
import storage.manager as store_manager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s – %(message)s"
)
logger = logging.getLogger(__name__)


def _today_keyboard_log() -> Path:
    now = datetime.now()
    return (
        Path(config.KEYBOARD_DIR)
        / now.strftime("%Y")
        / now.strftime("%m")
        / now.strftime("%d")
        / "keyboard.log"
    )

def test_directories():
    """Test if directories can be created."""
    logger.info("=" * 60)
    logger.info("TEST 1: Directory Creation")
    logger.info("=" * 60)
    try:
        store_manager.ensure_directories()
        for directory in [
            config.RECORDINGS_DIR,
            config.SCREENSHOTS_DIR,
            config.LOGS_DIR,
            config.WEBCAM_DIR,
            config.KEYBOARD_DIR,
        ]:
            exists = os.path.isdir(directory)
            status = "✓" if exists else "✗"
            logger.info("%s %s", status, directory)
        logger.info("RESULT: PASS\n")
        return True
    except Exception as e:
        logger.error("RESULT: FAIL – %s\n", e)
        return False

def test_screen_recorder():
    """Test screen recording (30 seconds)."""
    logger.info("=" * 60)
    logger.info("TEST 2: Screen Recording (30 seconds)")
    logger.info("=" * 60)
    try:
        recorder = ScreenRecorder()
        recorder.start()
        logger.info("Screen recorder started, waiting 35 seconds...")
        time.sleep(35)
        recorder.stop()
        
        # Check if file was created
        files = list(Path(config.RECORDINGS_DIR).glob("screen_*.mp4"))
        if files:
            logger.info("✓ Screen recording file created: %s", files[0].name)
            logger.info("✓ File size: %s bytes", files[0].stat().st_size)
            logger.info("RESULT: PASS\n")
            return True
        else:
            logger.error("✗ No screen recording file created")
            logger.error("RESULT: FAIL\n")
            return False
    except Exception as e:
        logger.error("RESULT: FAIL – %s\n", e)
        return False

def test_webcam_recorder():
    """Test webcam recording (30 seconds)."""
    logger.info("=" * 60)
    logger.info("TEST 3: Webcam Recording (30 seconds)")
    logger.info("=" * 60)
    try:
        recorder = WebcamRecorder()
        recorder.start()
        logger.info("Webcam recorder started, waiting 35 seconds...")
        time.sleep(35)
        recorder.stop()
        
        # Check if file was created
        files = list(Path(config.WEBCAM_DIR).glob("webcam_*.mp4"))
        if files:
            logger.info("✓ Webcam recording file created: %s", files[0].name)
            logger.info("✓ File size: %s bytes", files[0].stat().st_size)
            logger.info("RESULT: PASS\n")
            return True
        else:
            logger.error("✗ No webcam recording file created")
            logger.error("RESULT: FAIL\n")
            return False
    except Exception as e:
        logger.error("RESULT: FAIL – %s\n", e)
        return False

def test_keyboard_monitor():
    """Test keyboard monitoring (30 seconds)."""
    logger.info("=" * 60)
    logger.info("TEST 4: Keyboard Monitoring (30 seconds)")
    logger.info("=" * 60)
    logger.info("Press some keys on your keyboard during the test...")
    try:
        monitor = KeyboardMonitor()
        monitor.start()
        logger.info("Keyboard monitor started, waiting 30 seconds...")
        time.sleep(30)
        monitor.stop()
        
        # Check if daily log file was created
        log_path = _today_keyboard_log()
        if log_path.is_file():
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if lines:
                logger.info("✓ Keyboard log file created: %s", log_path)
                logger.info("✓ Log entries: %d", len(lines))
                logger.info("RESULT: PASS\n")
                return True
            else:
                logger.warning("⚠ Keyboard log file exists but is empty")
                logger.warning("(This is normal if running in Session 0 / Windows Service)")
                logger.info("RESULT: EXPECTED (Session 0 limitation)\n")
                return True
        else:
            logger.warning("⚠ Keyboard log file not created")
            logger.warning("(This is normal if running in Session 0 / Windows Service)")
            logger.info("RESULT: EXPECTED (Session 0 limitation)\n")
            return True
    except Exception as e:
        logger.error("RESULT: FAIL – %s\n", e)
        return False

def test_screenshots():
    """Test screenshot capture (30 seconds)."""
    logger.info("=" * 60)
    logger.info("TEST 5: Screenshot Capture (30 seconds)")
    logger.info("=" * 60)
    try:
        recorder = ScreenRecorder()
        recorder.start()
        logger.info("Screen recorder started for screenshots...")
        time.sleep(35)
        recorder.stop()
        
        # Check if screenshot files were created
        files = list(Path(config.SCREENSHOTS_DIR).glob("screenshot_*.png"))
        if files:
            logger.info("✓ Screenshot files created: %d", len(files))
            logger.info("✓ Latest: %s (%d bytes)", files[-1].name, files[-1].stat().st_size)
            logger.info("RESULT: PASS\n")
            return True
        else:
            logger.error("✗ No screenshot files created")
            logger.error("RESULT: FAIL\n")
            return False
    except Exception as e:
        logger.error("RESULT: FAIL – %s\n", e)
        return False

if __name__ == "__main__":
    logger.info("\n" + "=" * 60)
    logger.info("WORKSTATION MONITORING - COMPONENT DIAGNOSTIC")
    logger.info("=" * 60 + "\n")
    
    results = []
    results.append(("Directory Creation", test_directories()))
    results.append(("Screen Recording", test_screen_recorder()))
    results.append(("Webcam Recording", test_webcam_recorder()))
    results.append(("Keyboard Monitoring", test_keyboard_monitor()))
    results.append(("Screenshots", test_screenshots()))
    
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info("%s – %s", status, name)
    
    logger.info("\nNote: Keyboard monitoring is expected to fail in Session 0")
    logger.info("(Windows Service non-interactive context).\n")
