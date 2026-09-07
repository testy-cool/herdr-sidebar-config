"""Publish compact task rows from native Herdr facts, only when values change."""
import fcntl
import argparse
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path
from inactivity import update_inactivity
from activity_titles import activity_title
from runtime import PLUGIN_ID, herdr_binary, icon_mode, logo_for, run_herdr

STATES = {"working": "◔", "blocked": "?", "done": "✓", "idle": "○", "unknown": "·"}
# A braille blank occupies a terminal cell but survives metadata trimming.
BLANK = "\u2800"
HISTORY = {
    "codex": (".codex/history.jsonl", "session_id", "text"),
    "claude": (".claude/history.jsonl", "sessionId", "display"),
}
VAGUE = re.compile(
    r"^(yes|okay|ok|go ahead|go on|continue|nice|thank|where we at|are you still|"
    r"how(?:'s| is) it going|also i like)\b",
    re.I,
)


def _task_text(value):
    if not isinstance(value, str):
        return None
    for raw in value.splitlines():
        text = re.sub(r"\s+", " ", raw).strip().lstrip("#>*- ")
        text = re.sub(r"^(?:\[Image #\d+\]\s*)+", "", text, flags=re.I)
        if not text or text.startswith(("AGENTS.md instructions", "<environment_context", "<INSTRUCTIONS", "<skill")):
            continue
        if VAGUE.match(text):
            continue
        text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
        return text[:96].rstrip(" ,.;:-")
    return None


def _reverse_history(path, max_bytes=512 * 1024):
    try:
        with path.open("rb") as stream:
            end = stream.seek(0, os.SEEK_END)
            start = max(0, end - max_bytes)
            stream.seek(start)
            data = stream.read()
    except OSError:
        return
    if start:
        data = data.split(b"\n", 1)[-1]
    for raw in reversed(data.splitlines()):
        yield raw.decode("utf-8", "replace")


def latest_history_task(pane):
    source = HISTORY.get(pane.get("agent"))
    session = pane.get("agent_session") or {}
    session_id = session.get("value") if isinstance(session, dict) else None
    if not source or not session_id:
        return None
    relative_path, session_key, text_key = source
    for line in _reverse_history(Path.home() / relative_path):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict) or record.get(session_key) != session_id:
            continue
        text = _task_text(record.get(text_key))
        if text:
            return text
    return None


def task_label(pane, tabs):
    tokens = pane.get("tokens") or {}
    if tokens.get("hs_title"):
        return tokens["hs_title"]
    native = activity_title(pane)
    if native:
        return native
    if pane.get("agent_status") == "working":
        task = latest_history_task(pane)
        if task:
            return task[:1].upper() + task[1:]
    raw = pane.get("terminal_title_stripped") or ""
    parts = [p.strip().rstrip(".… ") for p in raw.split(" | ")]
    candidates = [p for p in parts if p and not p.startswith(("[", "~/", "/", "<"))
                  and not re.match(r"^[A-Za-z]:[/\\]", p)]
    # Claude's named session is more durable than its transient prompt snippets.
    if candidates and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", candidates[0]):
        return candidates[0].replace("-", " ").capitalize()
    for text in reversed(candidates):
        if not VAGUE.match(text):
            text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
            return text[:1].upper() + text[1:]
    tab = tabs.get(pane.get("tab_id"), "")
    if tab and tab not in {"main", "shell"} and not re.fullmatch(r"(?:💤\s*)?\d+", tab):
        return tab.replace("-", " ")
    name = pane.get("name") or pane.get("label")
    if name:
        return name.replace("-", " ")
    return {"agy": "AGY session", "codex": "Codex session", "claude": "Claude session"}.get(
        pane.get("agent"), f"{pane.get('agent', 'Agent')} session")


def desired_headers(panes, workspaces):
    names = {w["workspace_id"]: w["label"] for w in workspaces}
    seen = set()
    result = {}
    for pane in panes:
        workspace = pane["workspace_id"]
        heading = None
        if pane.get("agent") and workspace not in seen:
            heading = names.get(workspace)
            seen.add(workspace)
        result[pane["pane_id"]] = heading
    return result


def desired_rows(panes, workspaces, tabs, icons="font", inactive_ids=frozenset()):
    headers = desired_headers(panes, workspaces)
    groups = {}
    tab_ids = {}
    for pane in panes:
        tab_ids.setdefault(pane["workspace_id"], set()).add(pane.get("tab_id"))
        if pane.get("agent"):
            groups.setdefault(pane["workspace_id"], {}).setdefault(
                pane.get("tab_id"), []
            ).append(pane["pane_id"])
    previous = None
    result = {}
    for pane in panes:
        heading = headers[pane["pane_id"]]
        values = {"hs_group": heading, "hs_tab": None,
                  "hs_gap": None, "hs_logo": None, "hs_terminals": None}
        values.update({f"hs_{state}": None for state in STATES})
        if pane.get("agent"):
            if heading and previous is not None:
                result[previous]["hs_gap"] = BLANK
            if heading:
                shells = [tabs.get(t, "terminal") for t in tab_ids[pane["workspace_id"]]
                          if t not in groups[pane["workspace_id"]]]
                if shells:
                    values["hs_terminals"] = "terminals: " + ", ".join(sorted(shells))
            tab_id = pane.get("tab_id")
            workspace_tabs = groups[pane["workspace_id"]]
            show_tree = len(tab_ids[pane["workspace_id"]]) > 1
            siblings = workspace_tabs[tab_id]
            first_in_tab = pane["pane_id"] == siblings[0]
            last_in_tab = pane["pane_id"] == siblings[-1]
            if show_tree and first_in_tab:
                tab_label = tabs.get(tab_id) or "tab"
                # Continuation rows start two cells to the right of first rows.
                values["hs_tab"] = ("" if heading else BLANK * 2) + tab_label
            logo = logo_for(pane["agent"], icons)
            if show_tree:
                prefix = "" if first_in_tab else BLANK * 2
                prefix += "└─ " if last_in_tab else "├─ "
            else:
                prefix = "" if heading else BLANK * 2
            values["hs_logo"] = prefix + logo
            status = pane.get("agent_status", "unknown")
            if status not in STATES:
                status = "unknown"
            values[f"hs_{status}"] = STATES[status] + " " + task_label(pane, tabs)
            previous = pane["pane_id"]
        # Mutually exclusive tokens let static Herdr styles dim a whole group.
        for key in ["hs_group", "hs_tab", "hs_logo", *[f"hs_{s}" for s in STATES]]:
            values[key + "_dim"] = values[key] if pane["workspace_id"] in inactive_ids else None
            if pane["workspace_id"] in inactive_ids:
                values[key] = None
        result[pane["pane_id"]] = values
    return result


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def refresh(clear=False):
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True)
    with (state / "group-headers.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        herdr = herdr_binary()
        snapshot = run_herdr(herdr, "api", "snapshot")["result"]["snapshot"]
        agents = {a["pane_id"]: a for a in snapshot["agents"]}
        panes = [{**p, **agents.get(p["pane_id"], {})} for p in snapshot["panes"]]
        workspaces = snapshot["workspaces"]
        tabs = {t["tab_id"]: t["label"] for t in snapshot["tabs"]}
        settings_path = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", str(state))) / "config.toml"
        settings = tomllib.loads(settings_path.read_text()) if settings_path.exists() else {}
        activity = update_inactivity([w["workspace_id"] for w in workspaces], panes,
                                     read_state(state / "activity.json"), now=time.time(),
                                     timeout=settings.get("inactive_after_seconds", 600))
        saved = dict(activity.state, next_deadline=None if clear else activity.next_deadline)
        temporary = state / "activity.tmp"
        temporary.write_text(json.dumps(saved))
        temporary.replace(state / "activity.json")
        desired = desired_rows(panes, workspaces, tabs, icon_mode(), activity.inactive_ids)
        source = "plugin:" + os.environ.get("HERDR_PLUGIN_ID", PLUGIN_ID)
        for pane in panes:
            wanted = dict.fromkeys(desired[pane["pane_id"]]) if clear else desired[pane["pane_id"]]
            changes = changed_tokens(pane.get("tokens") or {}, wanted)
            if not changes:
                continue
            args = ["pane", "report-metadata", pane["pane_id"], "--source", source]
            for key, value in changes.items():
                args += ["--token", key + "=" + value] if value is not None else ["--clear-token", key]
            run_herdr(herdr, *args)
        for workspace in workspaces:
            wid = workspace["workspace_id"]
            dim = wid in activity.inactive_ids
            wanted = {"hs_space": None if dim else workspace["label"],
                      "hs_space_dim": workspace["label"] if dim else None}
            if clear:
                wanted = dict.fromkeys(wanted)
            changes = changed_tokens(workspace.get("tokens") or {}, wanted)
            if changes:
                args = ["workspace", "report-metadata", wid, "--source", source]
                for key, value in changes.items():
                    args += ["--token", key + "=" + value] if value is not None else ["--clear-token", key]
                run_herdr(herdr, *args)
        if activity.next_deadline is not None or (state / "deadline.lock").exists():
            from deadline import ensure_timer
            ensure_timer(state, start=not clear and activity.next_deadline is not None)


def changed_tokens(existing, desired):
    return {key: value for key, value in desired.items() if existing.get(key) != value}


def main():
    parser = argparse.ArgumentParser(description="Refresh the Herdr workspace/tab/agent sidebar.")
    parser.add_argument("--clear", action="store_true", help="clear this plugin's display tokens")
    parser.add_argument("--settings", action="store_true", help="run the settings popup")
    parser.add_argument("--settings-open", action="store_true", help="open the settings popup")
    args = parser.parse_args()
    if not os.environ.get("HERDR_PLUGIN_STATE_DIR"):
        raise RuntimeError("Run through Herdr: herdr plugin action invoke refresh --plugin " + PLUGIN_ID)
    if args.settings or args.settings_open:
        import settings_ui
        settings_ui.open_popup() if args.settings_open else settings_ui.main()
        return
    refresh(args.clear)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Herdr Sidebar: {error}", file=sys.stderr)
        sys.exit(1)
