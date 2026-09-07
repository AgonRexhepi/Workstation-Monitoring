# Workstation Monitoring – Installation Instructions

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10 / 11 | The service layer uses Windows-specific APIs |
| Python 3.11+ | Tested with 3.11 and 3.12 |
| Administrator rights | Required for service installation |
| Webcam (optional) | For `WEBCAM_PHOTO` / `WEBCAM_RECORD` features |

---

## 1. Clone the Repository

```bat
git clone https://github.com/AgonRexhepi/Workstation-Monitoring.git
cd Workstation-Monitoring
```

## 2. Create and Activate a Virtual Environment

```bat
python -m venv .venv
.venv\Scripts\activate
```

## 3. Install Dependencies

```bat
pip install -r requirements.txt
```

> **Tip:** A pinned snapshot of all transitive dependencies is available in
> `requirements-lock.txt` for fully reproducible installs:
> ```bat
> pip install -r requirements-lock.txt
> ```

## 4. Configure the Application

Open `config.py` in a text editor and adjust the settings for your environment:

```python
# Storage root (all recorded data will be written here)
BASE_DIR = "C:\\WorkstationMonitor"

# --- Retention ---
# Files older than DELETE_DATA days are automatically deleted.
DELETE_DATA = 365   # days

# --- Feature flags (1 = enabled, 0 = disabled) ---
WEBCAM_RECORD = 0   # continuous webcam video
WEBCAM_PHOTO  = 1   # periodic / activity-triggered webcam snapshots
WEBCAM_PHOTO_ON_ACTIVITY = True   # capture on keyboard / mouse activity
SCREEN_RECORD = 0   # continuous screen recording
SCREEN_SHOT   = 1   # periodic screenshots
KEY_LOGGER    = 1   # keyboard logging

# --- Dashboard ---
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 5000
```

> **Security:** Set strong secrets via environment variables before deploying:
>
> ```bat
> set MONITOR_SECRET_KEY=<random-long-string>
> set MONITOR_SUPERVISOR_PASSWORD=<strong-password>
> ```

## 5. Run in Debug Mode (Recommended First Step)

Before installing as a service, verify that everything works by running in
the foreground:

```bat
python service.py debug
```

Open a browser and navigate to `http://127.0.0.1:5000/`.  
Log in with the password configured in `SUPERVISOR_PASSWORD` (default: `supervisor`).

Press **Ctrl + C** to stop.

## 6. Install as a Windows Service

> Run the following commands **as Administrator**.

### 6a. Install pywin32 (required for the service)

```bat
pip install pywin32
python .venv\Scripts\pywin32_postinstall.py -install
```

### 6b. Install the service

```bat
python service.py install
```

### 6c. Start the service

```bat
python service.py start
```

The service is configured to **restart automatically on failure**.

### Other service commands

| Command | Effect |
|---|---|
| `python service.py stop` | Stop the service |
| `python service.py restart` | Restart the service |
| `python service.py remove` | Uninstall the service |
| `python service.py status` | Show current status |

---

## 7. Folder Structure

All data is stored under `BASE_DIR` organised by date:

```
C:\WorkstationMonitor\
├── screenshots\
│   └── 2026\09\07\
│       └── screenshot_20260907_143000_0001.png
├── webcam_photos\
│   └── 2026\09\07\
│       └── webcam_photo_20260907_143005.jpg
├── recordings\
│   └── 2026\09\07\
│       └── screen_20260907_120000.mp4
├── webcam\
│   └── 2026\09\07\
│       └── webcam_20260907_120000.mp4
└── logs\
    └── 2026\09\07\
        └── keyboard.log
```

---

## 8. Automatic Data Cleanup

The built-in `StorageManager` runs automatically every day at **08:00** and:

1. **Deletes files older than `DELETE_DATA` days** (configured in `config.py`).  
2. **Removes the oldest files** when total disk usage exceeds `MAX_STORAGE_MB`.

No separate cron job is required; the cleanup runs inside the service process.

If you prefer an external script, a standalone helper is also included:

```bat
python cleanup.py
```

---

## 9. Accessing the Dashboard

While the service is running, open:

```
http://127.0.0.1:5000/
```

The dashboard provides:

- **Overview** – storage usage, file counts per category  
- **Webcam Photos** – gallery with inline preview and download  
- **Screenshots** – gallery with inline preview and download  
- **Screen Recordings** – list with download  
- **Webcam Recordings** – list with download  
- **Keyboard Log** – live view of captured keystrokes  
- **System Info** – CPU / RAM / disk usage  

---

## 10. Uninstalling

```bat
python service.py stop
python service.py remove
```

Delete the data directory if no longer needed:

```bat
rmdir /s /q C:\WorkstationMonitor
```

---

## Troubleshooting

| Symptom | Resolution |
|---|---|
| Service fails to start | Check `C:\WorkstationMonitor\logs\monitor_service.log` |
| Webcam not detected | Verify `WEBCAM_INDEX` in `config.py`; try index 1 if multiple cameras |
| Dashboard not reachable | Ensure the service is running and no firewall blocks port 5000 |
| `pywin32` import errors | Re-run `python .venv\Scripts\pywin32_postinstall.py -install` as Admin |
