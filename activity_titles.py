"""Read native session names without model calls or scanning transcript trees.

Codex uses its native SQLite/index precedence; Claude uses explicit names before
summary metadata; Pi uses the latest session_info name. Only exact session IDs
or an explicitly reported Pi session file are consulted. Missing metadata is
normal: callers should retain their existing task/terminal-title fallback.
"""
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

MAX_BYTES = 512 * 1024
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
VAGUE = re.compile(r"(?:yes|ok(?:ay)?|continue|go on|go ahead|nice|thanks?|test)[.!?]*\Z", re.I)


def _clean(value, pane):
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    # Strip terminal control characters from display metadata.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f]", "", text)
    cwd = pane.get("cwd") or ""
    project = Path(cwd).name if isinstance(cwd, str) else ""
    canonical = lambda s: re.sub(r"[\W_]+", "", s).casefold()
    if (not text or VAGUE.fullmatch(text) or text.startswith(("<", "# AGENTS.md"))
            or (project and (canonical(text) == canonical(project)
                            or re.fullmatch(re.escape(project) + r"-[a-z0-9]{2}", text, re.I)))):
        return None
    return text[:160]


def _records(path):
    """Read at most a half MiB from the end, newest record first."""
    with path.open("rb") as stream:
        end = stream.seek(0, os.SEEK_END)
        start = max(0, end - MAX_BYTES)
        stream.seek(start)
        data = stream.read(MAX_BYTES)
    if start:
        data = data.partition(b"\n")[2]
    for line in reversed(data.splitlines()):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if isinstance(record, dict):
            yield record


def _codex(pane, session_id):
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    databases = sorted(home.glob("state_*.sqlite"),
                       key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1,
                       reverse=True)
    for path in databases[:4]:
        try:
            with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)) as db:
                db.row_factory = sqlite3.Row
                columns = {r[1] for r in db.execute("PRAGMA table_info(threads)")}
                selected = [c for c in ("title", "name", "first_user_message", "history_mode") if c in columns]
                if "id" not in columns or not selected:
                    continue
                row = db.execute("SELECT " + ",".join(selected) + " FROM threads WHERE id=?", (session_id,)).fetchone()
                row = dict(row) if row else None
        except sqlite3.Error:
            continue
        if row is None:
            continue
        if row.get("history_mode") == "paginated":
            return _clean(row.get("name"), pane)
        title = row.get("title")
        first = row.get("first_user_message")
        if isinstance(title, str) and title.strip() != (first or "").strip():
            cleaned = _clean(title, pane)
            if cleaned:
                return cleaned
        break
    for record in _records(home / "session_index.jsonl"):
        if record.get("id") == session_id:
            return _clean(record.get("thread_name"), pane)
    return None


def _claude(pane, session_id):
    cwd = pane.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return None
    home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    project = home / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", cwd)
    names = {}
    try:
        for record in _records(project / (session_id + ".jsonl")):
            if record.get("sessionId", session_id) != session_id:
                continue
            kind = record.get("type")
            field = {"custom-title": "customTitle", "ai-title": "aiTitle",
                     "agent-name": "agentName", "summary": "summary"}.get(kind)
            if field and kind not in names:
                names[kind] = _clean(record.get(field), pane)
    except OSError:
        pass
    for kind in ("custom-title", "ai-title", "agent-name", "summary"):
        if names.get(kind):
            return names[kind]
    # Older Claude versions keep compact summary metadata in this index.
    try:
        with (project / "sessions-index.json").open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return None
        index = json.loads(raw)
        for entry in index.get("entries", []) if isinstance(index, dict) else []:
            if isinstance(entry, dict) and entry.get("sessionId") == session_id:
                return _clean(entry.get("customTitle"), pane) or _clean(entry.get("summary"), pane)
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def _pi(pane, session):
    value = session["value"]
    if session.get("kind") in {"path", "file"}:
        paths = [Path(value)]
        expected_id = None
    else:
        if not SESSION_ID.fullmatch(value):
            return None
        cwd = pane.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return None
        home = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
        encoded = "--" + re.sub(r"[/\\:]", "-", re.sub(r"^[/\\]", "", cwd)) + "--"
        paths = list((home / "sessions" / encoded).glob("*_" + value + ".jsonl"))[:4]
        expected_id = value
    for path in paths:
        try:
            with path.open("rb") as stream:
                header = json.loads(stream.readline(16384))
            if (not isinstance(header, dict) or header.get("type") != "session"
                    or not isinstance(header.get("id"), str)
                    or (expected_id and header["id"] != expected_id)):
                continue
            for record in _records(path):
                if record.get("type") == "session_info":
                    # Empty names intentionally clear the previous name.
                    return _clean(record.get("name"), pane)
        except (OSError, ValueError, UnicodeError):
            continue
    return None


def activity_title(pane):
    """Return a meaningful native session title, or None; never contact agents."""
    if not isinstance(pane, dict):
        return None
    session = pane.get("agent_session")
    if not isinstance(session, dict) or not isinstance(session.get("value"), str):
        return None
    agent = pane.get("agent")
    if session.get("agent", agent) != agent:
        return None
    try:
        if agent == "pi":
            return _pi(pane, session)
        if session.get("kind", "id") != "id" or not SESSION_ID.fullmatch(session["value"]):
            return None
        if agent == "codex":
            return _codex(pane, session["value"])
        if agent == "claude":
            return _claude(pane, session["value"])
    except (OSError, ValueError, TypeError, sqlite3.Error):
        pass
    return None
