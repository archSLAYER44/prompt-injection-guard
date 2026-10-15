"""The shared guard log: one JSON object per line, appended by every page that handles a chat request.

The production chat page (chat_app.py) and the dashboard (dashboard.py) both write here, and the dashboard's
Monitoring tab reads it in "All sessions (live)" mode, so a second screen can watch calls as they happen.
Each record carries the same keys as a dashboard history row (time, guard, verdict, score, blocked,
"reply contains secret", provider, message, _message, _document, _reply, _error, _fired) plus ts, session
and surface, and since 2026-10-14 conversation and model (the Assistant page's chats; `conversations()`
groups rows into chats, `history_for()` rebuilds what the model may remember, `remove()` deletes one chat).
Nothing here touches the detector.

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


# ---------------------------------------------------------------- conversations (the Assistant page, 2026-10-14)

def user_content(message, document):
    """The user turn as the model receives it: the message, then the retrieved document when there is one."""
    return message + (f"\n\nRetrieved document:\n{document}" if document else "")


def conversation_id(row):
    """The chat a row belongs to: its conversation id, or its session for rows written before conversations existed."""
    return row.get("conversation") or row.get("session") or "?"


def conversations(rows):
    """One summary per chat, newest activity first: id, title (the first message), turn counts, times, model."""
    groups = {}
    for row in rows:
        cid = conversation_id(row)
        g = groups.get(cid)
        if g is None:
            g = groups[cid] = {"id": cid, "title": (row.get("_message") or "")[:60], "session": row.get("session"),
                               "surface": row.get("surface"), "started": row.get("ts"), "last": row.get("ts"),
                               "turns": 0, "blocked": 0, "flagged": 0, "leaked": 0, "errors": 0,
                               "provider": row.get("provider"), "model": row.get("model"), "grouped_by_session": not row.get("conversation")}
        g["turns"] += 1
        g["last"] = row.get("ts") or g["last"]
        g["blocked"] += row.get("blocked") == "yes"
        g["flagged"] += row.get("verdict") == "injection"
        g["leaked"] += row.get("reply contains secret") == "yes"
        g["errors"] += bool(row.get("_error"))
        g["provider"], g["model"] = row.get("provider") or g["provider"], row.get("model") or g["model"]
    return sorted(groups.values(), key=lambda g: g["last"] or "", reverse=True)


def history_for(rows, conversation, limit=None):
    """The turns the model may remember from one chat: every message that reached it and the reply it gave.

    Blocked messages never reached the model and messages that ended in an error got no reply, so neither is
    part of the history. The user turn is rebuilt as the model saw it (message, then the document).
    """
    turns = []
    for row in rows:
        if conversation_id(row) != conversation or row.get("blocked") == "yes" or row.get("_error") or not row.get("_reply"):
            continue
        turns.append({"role": "user", "content": user_content(row.get("_message") or "", row.get("_document") or "")})
        turns.append({"role": "assistant", "content": row["_reply"]})
    return turns[-limit:] if limit else turns


def remove(conversation):
    """Delete one chat from the log (the file is rewritten without its rows). Returns how many rows went."""
    rows = read()
    keep = [r for r in rows if conversation_id(r) != conversation]
    if len(keep) == len(rows):
        return 0
    target = path()
    target.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in keep), encoding="utf-8")
    return len(rows) - len(keep)
