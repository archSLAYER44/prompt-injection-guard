"""The shared guard log: one JSON object per line, appended by every page that handles a chat request.

The production chat page (chat_app.py) and the dashboard (dashboard.py) both write here, and the dashboard's
Monitoring tab reads it in "All sessions (live)" mode, so a second screen can watch calls as they happen.
Each record carries the same keys as a dashboard history row (time, guard, verdict, score, blocked,
"reply contains secret", provider, message, _message, _document, _reply, _error, _fired) plus ts, session
and surface. Nothing here touches the detector.

    GUARD_LOG_PATH=/some/where/guard_log.jsonl   # override the location (tests use a scratch file)
"""
import json
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "logs" / "guard_log.jsonl"


def path():
    return Path(os.environ.get("GUARD_LOG_PATH") or DEFAULT_PATH)


def append(record):
    """Append one record. Values that are not JSON (sets, numpy numbers) are written as strings."""
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def read(limit=None):
    """Every record, oldest first (the last `limit` of them when given). Damaged lines are skipped."""
    target = path()
    if not target.exists():
        return []
    rows = []
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows


def clear():
    target = path()
    if target.exists():
        target.write_text("", encoding="utf-8")


def summary(rows):
    """Counts the monitor's tiles show: requests, blocked, sessions, leaks."""
    return {
        "requests": len(rows),
        "blocked": sum(1 for r in rows if r.get("blocked") == "yes"),
        "sessions": len({r.get("session") for r in rows if r.get("session")}),
        "leaked": sum(1 for r in rows if r.get("reply contains secret") == "yes"),
        "surfaces": sorted({r.get("surface", "?") for r in rows}),
    }
