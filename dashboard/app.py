"""
Flask dashboard – accessible only to authorised exam supervisors.
Runs on loopback (127.0.0.1) so it is never exposed to the network by default.
"""

import os
import hmac
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
    return hmac.compare_digest(password, config.SUPERVISOR_PASSWORD)


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


@app.route("/screenshots")
@login_required
def screenshots():
    items = store.list_screenshots()
    return render_template("screenshots.html", items=items)


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
    # Resolve to a canonical absolute path before any checks.
    abs_path = os.path.realpath(os.path.abspath(path))
    allowed = [
        os.path.realpath(os.path.abspath(config.RECORDINGS_DIR)),
        os.path.realpath(os.path.abspath(config.SCREENSHOTS_DIR)),
        os.path.realpath(os.path.abspath(config.WEBCAM_DIR)),
        os.path.realpath(os.path.abspath(config.LOGS_DIR)),
    ]

    # Determine which allowed directory contains the requested file.
    # Using os.path.commonpath prevents the sibling-directory bypass
    # that plain startswith() is vulnerable to.
    containing_dir: str | None = None
    for allowed_dir in allowed:
        try:
            if os.path.commonpath([abs_path, allowed_dir]) == allowed_dir:
                containing_dir = allowed_dir
                break
        except ValueError:
            # commonpath raises ValueError on mixed drive letters (Windows)
            pass

    if containing_dir is None:
        abort(403)

    # Use send_from_directory so Flask handles path safety; only the
    # filename (not the full path) is passed through user-controlled input.
    filename = os.path.basename(abs_path)
    return send_from_directory(containing_dir, filename, as_attachment=True)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _system_info() -> dict:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(config.BASE_DIR if os.path.isdir(config.BASE_DIR) else "/")
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
