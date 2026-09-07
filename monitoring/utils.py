"""
Shared utilities for the monitoring package.
"""

import os
from datetime import datetime


def dated_subdir(base_dir: str) -> str:
    """Return *base_dir/YYYY/MM/DD*, creating it if needed."""
    now = datetime.now()
    path = os.path.join(base_dir, now.strftime("%Y"), now.strftime("%m"), now.strftime("%d"))
    os.makedirs(path, exist_ok=True)
    return path
