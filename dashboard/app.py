"""
Flask dashboard – accessible only to authorised exam supervisors.
Runs on loopback (127.0.0.1) so it is never exposed to the network by default.
"""

import os
import platform
import logging
import math
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
    send_file,
)

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
import storage.manager as store

logger = logging.getLogger(__name__)
ITEMS_PER_PAGE = config.ITEMS_PER_PAGE

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="assets",
    static_url_path="/assets"
)
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




def _safe_send(path: str, allowed_dirs: list[str]):
    """Validate *abs_path* is inside an allowed directory, then serve it.
    
        The directory passed to ``send_from_directory`` is taken from the
        *allowed_dirs* list (a hardcoded value), not from the user-provided path,
        so the taint from user input does not reach the filesystem call.
        """
    target = Path(path).resolve()

    for directory in allowed_dirs:
        allowed = Path(directory).resolve()

        try:
            target.relative_to(allowed)
        except ValueError:
            continue

        if not target.is_file():
            abort(404)

        return send_file(target)

    abort(403)


def _parse_datetime_filter(value: str, *, end_of_day: bool = False) -> float | None:
    value = value.strip()
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if end_of_day and "T" not in value:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed.timestamp()


def _filter_media_items(items: list[dict], search: str, date_from: str, date_to: str) -> list[dict]:
    search_term = search.strip().lower()
    date_from_ts = None
    date_to_ts = None

    try:
        date_from_ts = _parse_datetime_filter(date_from)
        date_to_ts = _parse_datetime_filter(date_to, end_of_day=True)
    except ValueError:
        flash("Invalid date/time format.", "danger")

    filtered_items = []
    for item in items:
        if search_term:
            name = str(item.get("name", "")).lower()
            modified = str(item.get("modified", "")).lower()
            if search_term not in name and search_term not in modified:
                continue

        modified_timestamp = item.get("modified_timestamp", 0)
        if date_from_ts is not None and modified_timestamp < date_from_ts:
            continue
        if date_to_ts is not None and modified_timestamp > date_to_ts:
            continue

        filtered_items.append(item)

    return filtered_items


def _get_page_number() -> int:
    try:
        return max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        return 1


def _paginate_items(items: list[dict], page: int, per_page: int = ITEMS_PER_PAGE) -> tuple[list[dict], dict]:
    total_items = len(items)
    total_pages = max(math.ceil(total_items / per_page), 1)
    page = min(page, total_pages)
    start_index = (page - 1) * per_page
    paginated_items = items[start_index:start_index + per_page]
    return paginated_items, {
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "start_index": start_index,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def _build_pagination_links(endpoint: str, pagination: dict, search: str, date_from: str, date_to: str) -> dict:
    query_args = {
        "search": search,
        "date_from": date_from,
        "date_to": date_to,
    }
    total_pages = pagination["total_pages"]
    page = pagination["page"]
    return {
        "prev_url": url_for(endpoint, page=page - 1, **query_args) if pagination["has_prev"] else None,
        "next_url": url_for(endpoint, page=page + 1, **query_args) if pagination["has_next"] else None,
        "pages": [
            {
                "number": page_number,
                "url": url_for(endpoint, page=page_number, **query_args),
                "active": page_number == page,
            }
            for page_number in range(1, total_pages + 1)
        ],
    }


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
    search = request.args.get("search", "").strip()
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()
    filtered_items = _filter_media_items(items, search, date_from_str, date_to_str)
    paginated_items, pagination = _paginate_items(filtered_items, _get_page_number())

    return render_template(
        "webcam_photos.html",
        items=paginated_items,
        pagination=pagination,
        pagination_links=_build_pagination_links(
            "webcam_photos", pagination, search, date_from_str, date_to_str
        ),
        search=search,
        date_from=date_from_str,
        date_to=date_to_str,
    )


@app.route("/screenshots")
@login_required
def screenshots():
    items = store.list_screenshots()
    search = request.args.get("search", "").strip()
    date_from_str = request.args.get("date_from", "").strip()
    date_to_str = request.args.get("date_to", "").strip()
    filtered_items = _filter_media_items(items, search, date_from_str, date_to_str)
    paginated_items, pagination = _paginate_items(filtered_items, _get_page_number())
    return render_template(
        "screenshots.html",
        items=paginated_items,
        pagination=pagination,
        pagination_links=_build_pagination_links(
            "screenshots", pagination, search, date_from_str, date_to_str
        ),
        search=search,
        date_from=date_from_str,
        date_to=date_to_str,
    )


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
    # Search inside the keyboard log and time
    # --------------------------------------------------------------
    search = request.args.get("search", "").strip().lower()

    if search:
        filtered_entries = []

        for entry in entries:
            key = str(entry.get("key", ""))
            time = str(entry.get("time", ""))

            if search in key.lower():
                filtered_entries.append(entry)
            elif search in time.lower():
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
