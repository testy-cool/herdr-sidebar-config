"""Read exact saved conversations and keep small local context records.

No model calls, agents, or transcript-tree scans. A parked session is accepted
only when Hibernate's record matches the native pane, tab, workspace and cwd.
"""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

from activity_titles import MAX_BYTES, SESSION_ID, _clean, _records, activity_title

FOLLOWUP = re.compile(
    r"^(?:yes|ok(?:ay)?|continue|go on|go ahead|do it|nice|thanks?|test|"
    r"how(?:'s| is) it going|are you still|where we at|review this please)\b", re.I)
CONTROL = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]")
GENERIC = re.compile(r"(?:main|shell|terminal|tab(?:[ -]?\d+)?|\d+)\Z", re.I)


def request_text(value, pane):
    if not isinstance(value, str):
        return None
    if value.lstrip().startswith(("# AGENTS.md", "AGENTS.md instructions", "<environment_context",
                                 "<INSTRUCTIONS>", "<skill", "<turn_aborted>", "<system-reminder>")):
        return None
    for line in value.splitlines():
        text = CONTROL.sub("", line).strip().lstrip("#>*- ")
        text = re.sub(r"^(?:\[Image #\d+\]\s*)+", "", text, flags=re.I)
        text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
        if not text or text.startswith(("<", "AGENTS.md instructions")) or FOLLOWUP.match(text):
            continue
        text = _clean(text, pane)
        if text:
            return text[:1].upper() + text[1:]
    return None


def _content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(part["text"] for part in value if isinstance(part, dict)
                         and part.get("type") in ("text", "input_text") and isinstance(part.get("text"), str))
    return ""


def session_file(pane):
    session = pane.get("agent_session") or {}
    value = session.get("value")
    if not isinstance(value, str) or session.get("agent", pane.get("agent")) != pane.get("agent"):
        return None
    agent = pane.get("agent")
    if agent == "pi" and session.get("kind") in ("path", "file"):
        return Path(value)
    if not SESSION_ID.fullmatch(value) or session.get("kind", "id") != "id":
        return None
    if agent == "codex":
        home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        paths = sorted(home.glob("state_*.sqlite"),
                       key=lambda p: int(p.stem.split("_")[-1]) if p.stem.split("_")[-1].isdigit() else -1,
                       reverse=True)
        for path in paths[:4]:
            try:
                with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05)) as db:
                    cols = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
                    if not {"id", "rollout_path"} <= cols:
                        continue
                    row = db.execute("SELECT rollout_path FROM threads WHERE id=?", (value,)).fetchone()
                    if row and isinstance(row[0], str) and row[0]:
                        return Path(row[0])
            except sqlite3.Error:
                continue
    elif agent == "claude" and isinstance(pane.get("cwd"), str):
        home = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        project = re.sub(r"[^A-Za-z0-9-]", "-", pane["cwd"])
        return home / "projects" / project / (value + ".jsonl")
    elif agent == "pi" and isinstance(pane.get("cwd"), str):
        home = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent")
        encoded = "--" + re.sub(r"[/\\:]", "-", re.sub(r"^[/\\]", "", pane["cwd"])) + "--"
        return next(iter((home / "sessions" / encoded).glob("*_" + value + ".jsonl")), None)
    return None


def latest_request(pane):
    """Read a bounded tail of the exact transcript; fall back to exact history."""
    session = pane.get("agent_session") or {}
    value = session.get("value")
    if not isinstance(value, str) or session.get("agent", pane.get("agent")) != pane.get("agent"):
        return None
    path = session_file(pane)
    if path:
        try:
            # Verify identity before accepting any user text from the file.
            with path.open("rb") as stream:
                header = json.loads(stream.readline(16384))
            if not isinstance(header, dict):
                return None
            agent = pane.get("agent")
            payload = header.get("payload")
            identity = payload.get("id") if agent == "codex" and isinstance(payload, dict) else header.get("id")
            if agent in ("codex", "pi") and (not isinstance(identity, str)
                    or (session.get("kind", "id") == "id" and identity != value)):
                return None
            for record in _records(path):
                if record.get("sessionId", value) != value:
                    continue
                payload = record.get("payload") if agent == "codex" else record.get("message")
                if not isinstance(payload, dict):
                    continue
                text = None
                if payload.get("role") == "user":
                    text = _content(payload.get("content"))
                elif agent == "codex" and record.get("type") == "event_msg" and payload.get("type") == "user_message":
                    text = payload.get("message")
                candidate = request_text(text, pane)
                if candidate:
                    return candidate
        except (OSError, ValueError, UnicodeError):
            pass
    # ID history is a fallback, never search another session or a project glob.
    if session.get("kind", "id") != "id" or not SESSION_ID.fullmatch(value):
        return None
    agent = pane.get("agent")
    if agent not in ("codex", "claude"):
        return None
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") if agent == "codex" else Path(
        os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    key, field = ("session_id", "text") if agent == "codex" else ("sessionId", "display")
    try:
        for record in _records(home / "history.jsonl"):
            if record.get(key) == value:
                candidate = request_text(record.get(field), pane)
                if candidate:
                    return candidate
    except OSError:
        pass
    return None


def read_json(path, limit=MAX_BYTES * 2):
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
        result = json.loads(raw) if len(raw) <= limit else {}
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def save_json(path, data):
    path = Path(path)
    if read_json(path) == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False)
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def hibernate_records():
    path = os.environ.get("HERDR_SIDEBAR_HIBERNATE_STATE")
    return read_json(path or Path.home() / ".config" / "herdr-hibernate" / "state.json")


def parked_session(pane, parked):
    rec = parked.get(pane.get("pane_id"))
    if pane.get("agent") or not isinstance(rec, dict):
        return None
    if any(rec.get(key) != pane.get(key) for key in ("tab_id", "cwd")):
        return None
    # Older Hibernate records link the pane and tab without a workspace field.
    # Keep the workspace from Herdr's native pane; reject an explicit mismatch.
    if "workspace_id" in rec and rec["workspace_id"] != pane.get("workspace_id"):
        return None
    value = rec.get("uuid")
    agent = rec.get("agent")
    if agent not in ("codex", "claude", "pi") or not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        return None
    return {"kind": "id", "agent": agent, "value": value}


def session_identity(provider, session):
    kind, value = session.get("kind", "id"), session["value"]
    if provider == "pi" and kind in ("path", "file"):
        try:
            with Path(value).open("rb") as stream:
                header = json.loads(stream.readline(16384))
            if (isinstance(header, dict) and header.get("type") == "session"
                    and isinstance(header.get("id"), str) and SESSION_ID.fullmatch(header["id"])):
                return [provider, "id", header["id"]]
        except (OSError, ValueError, UnicodeError):
            pass
    return [provider, kind, value]


def collect(panes, previous, parked, *, now):
    """Cache title/request facts, pruning closed/reused panes and stale sessions."""
    records = {}
    old = previous.get("records", {})
    if not isinstance(old, dict):
        old = {}
    for pane in panes:
        session = pane.get("agent_session") if pane.get("agent") else parked_session(pane, parked)
        if not isinstance(session, dict) or not isinstance(session.get("value"), str):
            # Exit can precede Hibernate writing its record. Retain a private
            # checkpoint through that gap, but do not display it as sleeping.
            saved = old.get(pane["pane_id"])
            if not pane.get("agent") and isinstance(saved, dict) and saved.get("cwd") == pane.get("cwd"):
                records[pane["pane_id"]] = dict(saved, detached=True, sleeping=False,
                                               workspace_id=pane["workspace_id"], tab_id=pane.get("tab_id"))
            continue
        provider = pane.get("agent") or session.get("agent")
        if session.get("agent", provider) != provider:
            continue
        identity = session_identity(provider, session)
        reader = dict(pane, agent=provider, agent_session=session)
        saved = old.get(pane["pane_id"], {})
        if not isinstance(saved, dict):
            saved = {}
        same = (saved.get("provider") == provider and saved.get("identity") == identity
                and saved.get("cwd") == pane.get("cwd"))
        sleeping = not pane.get("agent")
        if sleeping and same:
            record = dict(saved)
        else:
            override = (pane.get("tokens") or {}).get("hs_title")
            override = CONTROL.sub("", " ".join(override.split())) if isinstance(override, str) else None
            native = override or activity_title(reader)
            request = latest_request(reader)
            title = native or request
            source = "user title" if override else "saved title" if native else "user request"
            if not title:
                if not same:
                    continue
                title, request = saved.get("title"), saved.get("request")
                source = saved.get("source", "saved conversation")
                if not title:
                    continue
            record = {"provider": provider, "session": session, "identity": identity, "cwd": pane.get("cwd"),
                      "title": title, "request": request, "source": source,
                      "recorded_at": saved.get("recorded_at", now) if same and saved.get("title") == title
                      and saved.get("request") == request else now}
        record.update(workspace_id=pane["workspace_id"], tab_id=pane.get("tab_id"), sleeping=sleeping, detached=False)
        records[pane["pane_id"]] = record
    return {"version": 1, "records": records,
            "owned_tabs": previous.get("owned_tabs", {}) if isinstance(previous.get("owned_tabs"), dict) else {}}


def short_title(value, limit=40):
    text = CONTROL.sub("", " ".join(value.split()))
    def width(char):
        return 0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    if sum(width(c) for c in text) <= limit:
        return text
    used, prefix = 0, ""
    for char in text:
        used += width(char)
        if used > limit - 1:
            break
        prefix += char
    cut = prefix.rsplit(" ", 1)[0]
    return (cut or prefix).rstrip() + "…"


def tab_changes(tabs, context):
    """Rename generic or unchanged auto-owned tabs only, never sleeping tabs."""
    owned = context["owned_tabs"]
    result = []
    live = {t["tab_id"] for t in tabs}
    for tab_id in list(owned):
        if tab_id not in live:
            del owned[tab_id]
    for tab in tabs:
        tab_id, label = tab["tab_id"], tab["label"]
        before = owned.get(tab_id)
        if before and not isinstance(before, dict):
            owned.pop(tab_id)
            before = None
        if before and label != before.get("label") and not label.startswith("💤"):
            del owned[tab_id]
            before = None
        if label.startswith("💤") or not (GENERIC.fullmatch(label.strip()) or before):
            continue
        records = [r for r in context["records"].values() if r.get("tab_id") == tab_id and not r.get("detached")]
        if not records or any(r.get("sleeping") for r in records):
            continue
        # List distinct goals rather than inventing an umbrella objective.
        titles = list(dict.fromkeys(r["title"] for r in records))
        if len(titles) == 1:
            title = short_title(titles[0])
        else:
            suffix = f" +{len(titles) - 2}" if len(titles) > 2 else ""
            limit = (40 - len(suffix) - 3) // 2
            title = " / ".join(short_title(t, limit) for t in titles[:2]) + suffix
        if title != label:
            result.append((tab_id, label, title))
    return result


def sleeping_label(workspace_id, context):
    titles = []
    seen = set()
    count = 0
    for record in context.get("records", {}).values():
        tab_id = record.get("tab_id")
        if record.get("workspace_id") == workspace_id and record.get("sleeping"):
            count += 1
            title = short_title(record["title"])
            if (tab_id, title) not in seen:
                titles.append(title)
                seen.add((tab_id, title))
    if not count:
        return None
    return f"{count} sleeping agent{'s' if count != 1 else ''} · " + ", ".join(titles)
