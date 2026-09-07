"""
Standalone cleanup script.

Deletes monitoring data that is older than DELETE_DATA days (read from
config.py) and removes the oldest files when total disk usage exceeds
MAX_STORAGE_MB.

Usage:
    python cleanup.py

This performs a single cleanup pass and exits.  The built-in StorageManager
already runs this logic automatically inside the service every hour, so you
only need this script if you want to trigger a manual or scheduled cleanup
outside of the service process.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import storage.manager as store


def main():
    manager = store.StorageManager()
    print(f"Running cleanup (retention: {config.DELETE_DATA} days) …")
    manager.run_once()
    summary = store.storage_summary()
    print(
        f"Done. Storage used: {summary['total_mb']} MB / {summary['max_mb']} MB"
    )


if __name__ == "__main__":
    main()
