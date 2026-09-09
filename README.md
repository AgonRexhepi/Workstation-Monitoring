# Workstation Monitoring

A standalone Python application for monitoring student workstations during examinations, in compliance with applicable academic regulations.

---

## Features

| Feature | Details |
|---|---|
| **Windows Background Service** | Runs as a Windows Service, starts automatically after boot |
| **Screen Recording** | Captures the primary display in 10-minute MP4 segments |
| **Webcam Recording** | Records from the connected camera in 10-minute MP4 segments |
| **Keyboard Monitoring** | Logs all key presses with timestamps |
| **Automatic Screenshots** | Periodic PNG screenshots at a configurable interval |
| **Local Dashboard** | Flask web UI (loopback only) for authorised supervisors |
| **Storage Management** | Configurable retention policy by age and total disk usage |
| **Auto-recovery** | Service configured to restart automatically on failure |

---

## Architecture

```
Windows Boot
     ↓
WorkstationMonitorSvc (Windows Service)
     ↓
MonitoringOrchestrator
     ├── ScreenRecorder      → C:\WorkstationMonitor\recordings\
     ├── WebcamRecorder      → C:\WorkstationMonitor\webcam\
     ├── KeyboardMonitor     → C:\WorkstationMonitor\keyboard\YYYY\MM\DD\keyboard.log
     ├── StorageManager      (retention policy enforcement)
     └── Dashboard (Flask)   → http://127.0.0.1:5000/
```

---

## Project Structure

```
Workstation-Monitoring/
├── config.py                  # Central configuration
├── service.py                 # Windows Service entry point
├── install_service.py         # Service installer helper
├── requirements.txt
├── monitoring/
│   ├── screen.py              # Screen recorder + screenshots
│   ├── webcam.py              # Webcam recorder
│   └── keyboard_monitor.py   # Keyboard activity logger
├── storage/
│   └── manager.py             # Storage helpers and retention
├── dashboard/
│   ├── app.py                 # Flask dashboard
│   └── templates/             # HTML templates
│       ├── base.html
│       ├── login.html
│       ├── index.html
│       ├── recordings.html
│       ├── screenshots.html
│       ├── keyboard.html
│       └── system.html
└── tests/
    └── test_monitoring.py
```

---

## Installation (Windows, run as Administrator)

### 1. Install dependencies

```powershell
pip install -r requirements.txt
# Verify pywin32 is importable by the interpreter used for service commands:
python -c "import win32service, win32serviceutil; print('pywin32 OK')"
```

If the import check fails, reinstall pywin32 explicitly:

```powershell
python -m pip install --upgrade pywin32
```

Important: for Windows Service mode, install dependencies from an elevated shell
so packages are available to the system interpreter used by the service account.
If pip reports "Defaulting to user installation", re-run in Administrator mode.

### 2. Configure

Edit `config.py` to set:

- `BASE_DIR` – where recordings and logs are stored
- `SUPERVISOR_PASSWORD` – dashboard login password (or set `MONITOR_SUPERVISOR_PASSWORD` env var)
- `DASHBOARD_SECRET_KEY` – Flask session key (or set `MONITOR_SECRET_KEY` env var)
- Recording FPS, webcam index, retention policy, etc.

### 3. Install and start the service

```powershell
python install_service.py
```

This installs the Windows Service, configures automatic startup and automatic restart on failure, and starts the service.

### Manual service management

```powershell
python service.py install   # install
python service.py start     # start
python service.py stop      # stop
python service.py remove    # uninstall
python service.py debug     # run in console (development)
```

### Troubleshooting service startup

- If debug mode works but service mode stops immediately, check Windows Event Viewer
     (Application log, provider: `Python Service`).
- Error `ModuleNotFoundError: No module named 'cv2'` means dependencies were installed
     only for the current user, not for the service runtime.
- Fix: open an elevated shell and run:

```powershell
python -m pip install -r requirements.txt
```

---

## Dashboard

Open a browser on the monitored workstation and navigate to:

```
http://127.0.0.1:5000/
```

Log in with the supervisor password. The dashboard provides:

- **Overview** – storage summary and live system snapshot
- **Screen Recordings** – list and download MP4 recordings
- **Webcam Recordings** – list and download webcam videos
- **Screenshots** – list and download PNG screenshots
- **Keyboard Log** – view the last 500 key-press entries
- **System Info** – CPU, memory, disk usage

The dashboard binds to `127.0.0.1` only. Supervisors must be physically present at the workstation (or use an authorised remote-access mechanism) to access it.

---

## Running Tests

```bash
pip install pytest flask psutil mss opencv-python numpy pynput
pytest tests/ -v
```

---

## Legal / Ethical Notice

This application is intended **strictly for authorised academic examination monitoring**.  
Students must be informed **before** the exam that workstation monitoring is active and that screen, webcam, and keyboard activity may be recorded in accordance with applicable academic regulations and data-protection legislation.


--VENV
cd C:\Users\user423\Downloads\Workstation-Monitoring-main

python.exe -m venv .venv

--Nese eshte e Script diable
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

.\.venv\Scripts\Activate.ps1

--

python -m pip install --upgrade pip

python -m pip install -r requirements.txt

--per offline
python -m pip install --no-index --find-links=offline_packages -r requirements-lock.txt

test
python -s -c "import cv2, flask, mss, numpy, psutil, pynput; print('SERVICE RUNTIME OK')"


Ekzekuto:

python install_service.py



----
sc.exe start WorkstationMonitorSvc
sc.exe query WorkstationMonitorSvc



---
1. Hiqe service-in e vjetër

Hape PowerShell Run as Administrator dhe bëj:

python service.py stop

Nëse thotë që service nuk është running, injoroje.

Pastaj:

python service.py remove

Kontrollo:

sc.exe query WorkstationMonitorSvc

Duhet të dalë:

FAILED 1060
2. Instaloje përsëri
python service.py install

Duhet:

Installing service WorkstationMonitorSvc
Service installed
3. Tani startoje
python service.py start

Pastaj menjëherë:

sc.exe query WorkstationMonitorSvc