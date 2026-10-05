import json
import os
from datetime import datetime, timezone

_LOG_DIR = os.path.expanduser("~/.local/share/fusetea")


def default_log_path(plugin):
    return os.path.join(_LOG_DIR, f"{plugin}.log")


def open_log(plugin, path=None):
    """Open a plugin's access log for appending, creating its directory if needed."""
    p = path if path is not None else default_log_path(plugin)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    return open(p, "a", buffering=1)


def log_entry(f, action, **fields):
    """Write one JSON object per line: timestamp + action + caller-supplied fields."""
    record = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": action, **fields}
    f.write(json.dumps(record) + "\n")
    f.flush()
