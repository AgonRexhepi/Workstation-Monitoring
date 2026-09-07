"""
Flask dashboard – accessible only to authorised exam supervisors.
Runs on loopback (127.0.0.1) so it is never exposed to the network by default.
"""

import os
import platform
import logging
from datetime import datetime
from functools import wraps
from pathlib import Path

import psutil
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    send_from_directory,
    abort,
    flash,
)

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
import storage.manager as store

logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = config.DASHBOARD_SECRET_KEY


# ------------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------------

def _check_password(password: str) -> bool:
    return password == config.SUPERVISOR_PASSWORD


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ------------------------------------------------------------------
# Auth routes
# ------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if _check_password(password):
            session["authenticated"] = True
            return redirect(url_for("index"))
        flash("Invalid password", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# Dashboard routes
# ------------------------------------------------------------------

def _is_safe(target: str, allowed_dirs: list) -> bool:
    """Return True if *target* is strictly inside one of the *allowed_dirs*."""
    for allowed_dir in allowed_dirs:
        try:
            if os.path.commonpath([target, allowed_dir]) == allowed_dir:
                return True
        except ValueError:
            # commonpath raises ValueError on mixed drive letters (Windows)
            pass
    return False


def _safe_send(abs_path: str, allowed_dirs: list, as_attachment: bool = False):
    """Validate *abs_path* is inside an allowed directory, then serve it.

    The directory passed to ``send_from_directory`` is taken from the
    *allowed_dirs* list (a hardcoded value), not from the user-provided path,
    so the taint from user input does not reach the filesystem call.
    """
    if not _is_safe(abs_path, allowed_dirs):
        abort(403)
    if not os.path.isfile(abs_path):
        abort(404)
    filename = os.path.basename(abs_path)
    # Identify which allowed directory contains this file so we pass a
    # server-controlled directory to send_from_directory, not user input.
    for allowed_dir in allowed_dirs:
        try:
            if os.path.commonpath([abs_path, allowed_dir]) == allowed_dir:
                return send_from_directory(allowed_dir, os.path.relpath(abs_path, allowed_dir), as_attachment=as_attachment)
        except ValueError:
            pass
    # Unreachable after _is_safe check above, but keeps the function well-formed.
    abort(403)


@app.route("/")
@login_required
def index():
    summary = store.storage_summary()
    system_info = _system_info()
    return render_template("index.html", summary=summary, system_info=system_info)


@app.route("/recordings")
@login_required
def recordings():
    items = store.list_screen_recordings()
    return render_template("recordings.html", items=items, title="Screen Recordings")


@app.route("/webcam")
@login_required
def webcam():
    items = store.list_webcam_recordings()
    return render_template("recordings.html", items=items, title="Webcam Recordings")


@app.route("/webcam_photos")
@login_required
def webcam_photos():
    items = store.list_webcam_photos()
    return render_template("webcam_photos.html", items=items)


@app.route("/screenshots")
@login_required
def screenshots():
    items = store.list_screenshots()
    return render_template("screenshots.html", items=items)


@app.route("/view_image")
@login_required
def view_image():
    """Serve an image file inline for in-browser preview."""
    path = request.args.get("path", "")
    abs_path = os.path.realpath(os.path.abspath(path))
    allowed = [
        os.path.realpath(os.path.abspath(config.SCREENSHOTS_DIR)),
        os.path.realpath(os.path.abspath(config.WEBCAM_PHOTOS_DIR)),
    ]
    return _safe_send(abs_path, allowed)


@app.route("/keyboard")
@login_required
def keyboard_log():
    lines = store.get_keyboard_log_lines()
    return render_template("keyboard.html", lines=lines)


@app.route("/system")
@login_required
def system():
    info = _system_info()
    return render_template("system.html", info=info)


@app.route("/download")
@login_required
def download():
    path = request.args.get("path", "")
    # Security: resolve to an absolute, canonical path, then verify it is
    # strictly inside one of the known storage directories.  Using
    # os.path.commonpath avoids the sibling-directory bypass that plain
    # startswith() is vulnerable to.
    abs_path = os.path.realpath(os.path.abspath(path))
    allowed = [
        os.path.realpath(os.path.abspath(config.RECORDINGS_DIR)),
        os.path.realpath(os.path.abspath(config.SCREENSHOTS_DIR)),
        os.path.realpath(os.path.abspath(config.WEBCAM_DIR)),
        os.path.realpath(os.path.abspath(config.WEBCAM_PHOTOS_DIR)),
        os.path.realpath(os.path.abspath(config.LOGS_DIR)),
    ]
    return _safe_send(abs_path, allowed, as_attachment=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _system_info() -> dict:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.version()}",
        "cpu_percent": cpu,
        "mem_total_gb": round(mem.total / (1024 ** 3), 2),
        "mem_used_percent": mem.percent,
        "disk_total_gb": round(disk.total / (1024 ** 3), 2),
        "disk_used_percent": disk.percent,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def run_dashboard():
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
    )
