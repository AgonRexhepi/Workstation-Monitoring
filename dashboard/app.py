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
    """Return True if *target* is strictly inside one of the *allowed_dirs*.

    Uses ``Path.is_relative_to`` (Python 3.9+) for strict containment so that
    a sibling path such as ``/data/webcam_photos`` cannot be confused with
    ``/data/webcam`` the way a plain ``commonpath`` prefix check can.
    """
    target_path = Path(target)
    for allowed_dir in allowed_dirs:
        try:
            if target_path.is_relative_to(allowed_dir):
                return True
        except (TypeError, ValueError):
            pass
    return False


def _safe_send(abs_path: str, allowed_dirs: list, as_attachment: bool = False):
    """Validate *abs_path* is inside an allowed directory, then serve it.

    The directory passed to ``send_from_directory`` is taken from the
    *allowed_dirs* list (a hardcoded value), not from the user-provided path,
    so the taint from user input does not reach the filesystem call.
    """
    target_path = Path(abs_path)
    for allowed_dir in allowed_dirs:
        try:
            if target_path.is_relative_to(allowed_dir):
                relpath = os.path.relpath(abs_path, allowed_dir)
                # send_from_directory raises 404 if the file does not exist.
                return send_from_directory(allowed_dir, relpath, as_attachment=as_attachment)
        except (TypeError, ValueError):
            pass
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

    search = request.args.get("search", "").strip().lower()
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()

    date_from = None
    date_to = None

    try:
        if date_from_str:
            date_from = datetime.fromisoformat(date_from_str).timestamp()

        if date_to_str:
            date_to = datetime.fromisoformat(date_to_str).timestamp()

    except ValueError:
        flash("Invalid date/time format.", "danger")

    filtered_items = []

    for item in items:

        # Search
        if search:
            name = str(item.get("name", "")).lower()
            modified = str(item.get("modified", "")).lower()

            if search not in name and search not in modified:
                continue

        # Date Time From
        if date_from is not None:
            if item.get("modified_timestamp", 0) < date_from:
                continue

        # Date Time To
        if date_to is not None:
            if item.get("modified_timestamp", 0) > date_to:
                continue

        filtered_items.append(item)

    return render_template(
        "webcam_photos.html",
        items=filtered_items,
        search=search,
        date_from=date_from_str,
        date_to=date_to_str
    )


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
    """
    Display keyboard logs grouped by day.

    Supports:
        ?search=
        ?date_from=YYYY-MM-DD
        ?date_to=YYYY-MM-DD
    """

    days = store.get_keyboard_log_by_day()

    search = request.args.get("search", "").strip().lower()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    filtered_days = []

    for day in days:
        day_date = str(day.get("date", ""))

        # ----------------------------------------------------------
        # Search by date
        # ----------------------------------------------------------
        if search and search not in day_date.lower():
            continue

        # ----------------------------------------------------------
        # Date From
        # ----------------------------------------------------------
        if date_from and day_date < date_from:
            continue

        # ----------------------------------------------------------
        # Date To
        # ----------------------------------------------------------
        if date_to and day_date > date_to:
            continue

        filtered_days.append(day)

    return render_template(
        "keyboard.html",
        days=filtered_days
    )


@app.route("/keyboard/<date>")
@login_required
def single_log(date):
    """
    Display keyboard log entries for a single day.

    Supports:
        ?search=
    """

    days = store.get_keyboard_log_by_day()

    selected_day = None

    for day in days:
        if str(day.get("date", "")) == date:
            selected_day = day
            break

    # Day does not exist
    if selected_day is None:
        abort(404)

    entries = selected_day.get("entries", [])

    # --------------------------------------------------------------
    # Search inside the keyboard log
    # --------------------------------------------------------------
    search = request.args.get("search", "").strip().lower()

    if search:
        filtered_entries = []

        for entry in entries:
            key = str(entry.get("key", ""))

            if search in key.lower():
                filtered_entries.append(entry)

        entries = filtered_entries

    return render_template(
        "single_log.html",
        date=date,
        entries=entries
    )


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
