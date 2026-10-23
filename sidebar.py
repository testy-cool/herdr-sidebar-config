"""Publish compact task rows from native Herdr facts, only when values change."""
import argparse
import json
import os
import re
import stat
import sys
import time
import tomllib
import unicodedata
from pathlib import Path
from host import Lock, entry
from inactivity import update_inactivity
from activity_titles import activity_title
from preferences import load as load_preferences
from ordering import order_groups, apply_view
from runtime import PLUGIN_ID, herdr_binary, icon_mode, logo_for, run_herdr

STATES = {"working": "◔", "blocked": "?", "done": "✓", "idle": "○", "unknown": "·"}
# A braille blank occupies a terminal cell but survives metadata trimming.
BLANK = "\u2800"
# Herdr accepts rows_by_agent only for agents it knows, and a row holds at most
# 16 tokens, so an agent that reports itself gets one accent token for its mark.
ACCENT_LOGOS = {"kimchi": "hs_logo_kimchi"}
ROW_ACCENT_LOGOS = {"kimchi": "hs_row_logo_kimchi"}
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


# Terminal titles of the form "<brand> <separator> <directory>": Pi sets
# "π - <cwd basename>" and never changes it, so it says where the agent is,
# which the space row already shows, and not what it is doing.
BRANDED_DIRECTORY = re.compile(r"^(?:π|pi|omp|codex|claude)?\s*[-–—>:·|]?\s*(.+?)\s*$", re.I)


def _names_own_directory(text, pane):
    cwd = pane.get("cwd") or pane.get("foreground_cwd") or ""
    if not cwd:
        return False
    # Windows snapshot paths use backslashes.
    base = re.split(r"[/\\]", cwd.rstrip("/\\"))[-1]
    if not base:
        return False
    match = BRANDED_DIRECTORY.match(text)
    return bool(match) and match.group(1).lower() == base.lower()


def task_label(pane, tabs):
    tokens = pane.get("tokens") or {}
    if tokens.get("hs_title"):
        return tokens["hs_title"]
    saved = pane.get("saved_context")
    if isinstance(saved, dict) and saved.get("title") and not saved.get("detached"):
        return saved["title"]
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
                  and not re.match(r"^[A-Za-z]:[/\\]", p)
                  and not _names_own_directory(p, pane)]
    # Claude's named session is more durable than its transient prompt snippets.
    if candidates and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+){2,}", candidates[0]):
        return candidates[0].replace("-", " ").capitalize()
    for text in reversed(candidates):
        if not VAGUE.match(text):
            text = re.sub(r"^(?:can|could|would) (?:you|we) (?:please )?", "", text, flags=re.I)
            return text[:1].upper() + text[1:]
    # A herdr agent name is chosen by whoever started the agent and says which
    # one this is; a tab label is usually automatic-rename's program name
    # ("agent"), which every agent tab shares.
    name = pane.get("name") or pane.get("label")
    if name:
        return name
    # automatic-rename prefixes tabs with their jump key; the agent row is not
    # a jump target, so the bracket says nothing here.
    tab = re.sub(r"^\[\d+\]\s*", "", tabs.get(pane.get("tab_id"), ""))
    if tab and tab not in {"main", "shell"} and not re.fullmatch(r"(?:💤\s*)?\d+", tab):
        return tab.replace("-", " ")
    return {"agy": "AGY session", "codex": "Codex session", "claude": "Claude session"}.get(
        pane.get("agent"), f"{pane.get('agent', 'Agent')} session")


def with_pane_name(pane, label):
    """Prefix a pane's own name, unless the label already starts with it."""
    name = (pane.get("name") or pane.get("label") or "").strip()
    normalize = lambda text: text.replace("-", " ").casefold()
    if not name or normalize(label).startswith(normalize(name)):
        return label
    return name + " - " + label


# Optional file in the folder an agent runs in, for people who keep one folder
# per named agent: `name` (default: the folder's name) and an `icon`.
IDENTITY_FILE = ".herdr-agent.toml"


def _display_text(value, limit):
    if not isinstance(value, str):
        return ""
    # C1 controls (\x80-\x9f) include a one-byte CSI that some terminals obey.
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]", "", " ".join(value.split()))
    return text[:limit].strip()


def folder_identity(pane):
    """Return (icon, name) from the agent folder's identity file, or None."""
    # The shell's cwd is where the pane started, often another agent's folder;
    # foreground_cwd is the folder the agent process itself runs in.
    folder = pane.get("foreground_cwd")
    if not isinstance(folder, str) or not folder:
        return None
    path = Path(folder) / IDENTITY_FILE
    try:
        # A pipe or device here would block the refresh while it holds the
        # group lock, so the open never waits and only a small regular file
        # is read. Checking the opened file, not the path, leaves no gap for
        # a swap in between. Windows has no O_NONBLOCK and no such pipes.
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return None
            raw = stream.read(4097)
        if len(raw) > 4096:
            return None
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    name = _display_text(data.get("name"), 32) or _display_text(Path(folder).name, 32)
    return _display_text(data.get("icon"), 8), name


def named_row(identity, label):
    """Split a named agent's row into its icon and name, and its task line."""
    icon, name = identity
    # Some session titles already start with the agent's name ("teresa · ...",
    # or "Minion god 12" for minion-god); the task line leaves it out.
    normalize = lambda text: re.sub(r"[-_]", " ", text).casefold()
    start, rest = label[:len(name)], label[len(name):]
    if normalize(start) == normalize(name) and not rest[:1].isalnum():
        label = rest.lstrip(" ·-–—:|")
        # The "12" left of "Minion god 12" is a session number, so no task line.
        if re.fullmatch(r"\d*", label):
            label = ""
    return (icon + " " + name if icon else name), label


# Characters that join the one before them into a single picture: variation
# selectors, the zero-width joiner, skin tones, keycaps and tags. Combining
# marks of any script join too (unicodedata.combining).
_JOINS = re.compile("[\ufe00-\ufe0f\u200d\u20e3\U0001f3fb-\U0001f3ff\U000e0020-\U000e007f]")


def _cells(text):
    """Terminal cells a short icon or logo takes, as Herdr's unicode-width counts.

    An emoji that is wide on its own, made wide by U+FE0F (❤️) or joined from
    several (👩‍💻) takes two cells; U+FE0E asks for the one-cell text form.
    Other characters take one cell, and their combining marks none.
    """
    clusters = []
    for char in text:
        joins = _JOINS.match(char) or unicodedata.combining(char)
        if clusters and (joins or clusters[-1][-1] == "\u200d"):
            clusters[-1] += char
        elif not joins:
            clusters.append(char)
    def width(cluster):
        if "\ufe0e" in cluster:
            return 1
        if "\u200d" in cluster or "\u20e3" in cluster:
            return 2
        if "\ufe0f" in cluster and ord(cluster[0]) >= 0x2000:
            return 2
        return 2 if unicodedata.east_asian_width(cluster[0]) in "WF" else 1
    return sum(width(c) for c in clusters)


# Herdr puts " · " between the logo token and the status token.
TOKEN_GAP = 3


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


def child_parents(panes, groups):
    """Map each agent pane to the agent it is drawn under, or None.

    Herdr does not record which pane opened another, so the opener tags the
    new pane with hs_parent=<its own pane id>. The pane is drawn under that
    agent only when it comes right after the agent's own rows in the same
    tab; a split from the opener lands there. Otherwise the tag is ignored.
    """
    tags = {pane["pane_id"]: (pane.get("tokens") or {}).get("hs_parent") for pane in panes}
    parents = {}
    for workspace_tabs in groups.values():
        for ids in workspace_tabs.values():
            open_rows = []
            for pane_id in ids:
                parent = tags.get(pane_id)
                if parent in open_rows:
                    del open_rows[open_rows.index(parent) + 1:]
                else:
                    parent = None
                    open_rows.clear()
                parents[pane_id] = parent
                open_rows.append(pane_id)
    return parents


def desired_rows(panes, workspaces, tabs, icons="font", inactive_ids=frozenset(), working_glyph="◔", branch_length="standard", pane_names=False, inactive_pane_ids=frozenset()):
    headers = desired_headers(panes, workspaces)
    groups = {}
    tab_ids = {}
    for pane in panes:
        tab_ids.setdefault(pane["workspace_id"], set()).add(pane.get("tab_id"))
        if pane.get("agent"):
            groups.setdefault(pane["workspace_id"], {}).setdefault(
                pane.get("tab_id"), []
            ).append(pane["pane_id"])
    parents = child_parents(panes, groups)
    # Per pane: its branch with everything left of it, and what its children's
    # rows and its task line repeat in that space (the tree lines carrying on).
    shapes = {}
    # The same space in the status-first rows, where a child's branch starts
    # under its parent's status mark instead of its logo.
    row_carries = {}
    previous = None
    result = {}
    for pane in panes:
        heading = headers[pane["pane_id"]]
        values = {"hs_group": heading, "hs_tab": None, "hs_logo_focus": None,
                  "hs_gap": None, "hs_logo": None, "hs_terminals": None, "hs_task": None,
                  "hs_row_logo": None, "hs_row_task": None}
        values.update({f"hs_{state}": None for state in STATES})
        values.update({f"hs_row_{state}": None for state in STATES})
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
            parent = parents[pane["pane_id"]]
            # Last among the agents at its own level: the tab's top-level
            # agents, or the children of the same parent.
            last = pane["pane_id"] == [p for p in siblings if parents[p] == parent][-1]
            has_children = pane["pane_id"] in parents.values()
            if show_tree and first_in_tab:
                tab_label = tabs.get(tab_id) or "tab"
                # Continuation rows start two cells to the right of first rows.
                values["hs_tab"] = ("" if heading else BLANK * 2) + tab_label
            logo = logo_for(pane["agent"], icons)
            # A child's branch starts under its parent's logo.
            base = shapes[parent][1] + BLANK if parent else ""
            branch = ""
            if show_tree or parent:
                branch = ("└" if last else "├") + (" " if branch_length == "short" else "─ ")
            carry = ("│" if not last else BLANK) + BLANK * (len(branch) - 1) if branch else ""
            shapes[pane["pane_id"]] = (base + branch, base + carry)
            if show_tree:
                prefix = "" if first_in_tab else BLANK * 2
            else:
                prefix = "" if heading else BLANK * 2
            values["hs_logo"] = prefix + base + branch + BLANK + logo
            row_base = row_carries[parent] if parent else ""
            row_head = row_base + branch if branch else BLANK
            row_carries[pane["pane_id"]] = row_base + carry if branch else BLANK
            status = pane.get("agent_status", "unknown")
            if status not in STATES:
                status = "unknown"
            mark = working_glyph if status == "working" else STATES[status]
            title = task_label(pane, tabs)
            label = with_pane_name(pane, title) if pane_names else title
            row_label, row_task = label, ""
            identity = folder_identity(pane)
            if identity:
                # A named agent's row holds its icon and name; the task goes on
                # the line below, under the name. That line is always a
                # continuation row, so it needs no first-row offset. The tree's
                # lines carry on beside it, and a line drops from the logo to
                # this agent's children.
                label, task = named_row(identity, label)
                if task:
                    under = 1 + _cells(logo) + TOKEN_GAP + _cells(mark) + 1
                    if identity[0]:
                        under += _cells(identity[0]) + 1
                    values["hs_task"] = (shapes[pane["pane_id"]][1] + BLANK
                                         + ("│" if has_children else BLANK)
                                         + BLANK * (under - 2) + task)
                # In the status-first rows the pane's own name sits beside the
                # agent's name, and the task starts under the icon.
                row_label, row_task = named_row(identity, title)
                pane_name = (pane.get("name") or pane.get("label") or "").strip() if pane_names else ""
                same = lambda a, b: a.replace("-", " ").casefold() == b.replace("-", " ").casefold()
                if pane_name and not same(pane_name, identity[1]):
                    row_label += " · " + pane_name
                    # With no title of its own the task is the pane name, already shown.
                    if same(row_task, pane_name):
                        row_task = ""
            values[f"hs_{status}"] = mark + " " + label
            # The status-first rows: the mark leads, the logo ends the line,
            # and a line drops from the mark to this agent's children.
            values[f"hs_row_{status}"] = prefix + row_head + mark + " " + row_label
            values["hs_row_logo"] = logo
            if row_task:
                values["hs_row_task"] = (row_carries[pane["pane_id"]] + ("│" if has_children else BLANK)
                                         + BLANK * _cells(mark) + row_task)
            previous = pane["pane_id"]
        dim_group = pane["workspace_id"] in inactive_ids
        dim_agent = dim_group or pane["pane_id"] in inactive_pane_ids
        # Keep shared headings bright while another agent is active.
        for key in ["hs_group", "hs_tab", "hs_logo", "hs_task", "hs_row_logo", "hs_row_task",
                    *[f"hs_{s}" for s in STATES], *[f"hs_row_{s}" for s in STATES]]:
            dim = dim_group if key in {"hs_group", "hs_tab"} else dim_agent
            values[key + "_dim"] = values[key] if dim else None
            if dim:
                values[key] = None
        for key, accents in (("hs_logo", ACCENT_LOGOS), ("hs_row_logo", ROW_ACCENT_LOGOS)):
            for agent, accent in accents.items():
                values[accent] = values[key] if pane.get("agent") == agent else None
                if values[accent]:
                    values[key] = None
        result[pane["pane_id"]] = values
    return result


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh(clear=False, restore_view=False):
    state = Path(os.environ["HERDR_PLUGIN_STATE_DIR"])
    state.mkdir(parents=True, exist_ok=True)
    with Lock(state / "group-headers.lock"):
        herdr = herdr_binary()
        snapshot = run_herdr(herdr, "api", "snapshot")["result"]["snapshot"]
        agents = {a["pane_id"]: a for a in snapshot["agents"]}
        panes = [{**p, **agents.get(p["pane_id"], {})} for p in snapshot["panes"]]
        workspaces = snapshot["workspaces"]
        tabs = {t["tab_id"]: t["label"] for t in snapshot["tabs"]}
        settings_path = Path(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", str(state))) / "config.toml"
        settings = load_preferences(settings_path)
        from conversation_context import collect, hibernate_records, read_json, save_json, tab_changes
        context_path = state / "context.json"
        context = collect(panes, read_json(context_path), hibernate_records(), now=time.time()) if not clear else {}
        if settings["conversation_titles"] and not clear:
            for tab_id, previous_label, title in tab_changes(snapshot["tabs"], context):
                # A user rename can race the snapshot. Never overwrite it.
                current = run_herdr(herdr, "tab", "get", tab_id)["result"]["tab"]
                if current.get("label") != previous_label:
                    context["owned_tabs"].pop(tab_id, None)
                    continue
                run_herdr(herdr, "tab", "rename", tab_id, title)
                context["owned_tabs"][tab_id] = {"label": title}
                tabs[tab_id] = title
        if not clear:
            save_json(context_path, context)
            panes = [dict(pane, saved_context=context["records"].get(pane["pane_id"])) for pane in panes]
        activity = update_inactivity([w["workspace_id"] for w in workspaces], panes,
                                     read_state(state / "activity.json"), now=time.time(),
                                     timeout=settings.get("inactive_after_seconds", 600))
        from animation import glyph, cache_rows
        ordered_panes, ranks = order_groups(panes, workspaces, settings["order"])
        animated = settings["animated_loaders"] and not clear
        desired = desired_rows(ordered_panes, workspaces, tabs, icon_mode(), activity.inactive_ids,
                               working_glyph=glyph(time.monotonic(), settings["loader_style"]) if animated else "◔",
                               branch_length=settings["branch_length"],
                               pane_names=settings["pane_names"],
                               inactive_pane_ids=activity.inactive_pane_ids)
        for pane in panes:
            desired[pane["pane_id"]]["hs_workspace_rank"] = ranks.get(pane["workspace_id"]) if pane.get("agent") else None
        rows = cache_rows(panes, desired, settings["loader_style"]) if animated else []
        saved = dict(activity.state, next_deadline=None if clear else activity.next_deadline,
                     animation_rows=rows)
        temporary = state / "activity.tmp"
        temporary.write_text(json.dumps(saved), encoding="utf-8")
        temporary.replace(state / "activity.json")
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
                      "hs_space_dim": workspace["label"] if dim else None,
                      "hs_parked": None}
            if clear:
                wanted = dict.fromkeys(wanted)
            changes = changed_tokens(workspace.get("tokens") or {}, wanted)
            if changes:
                args = ["workspace", "report-metadata", wid, "--source", source]
                for key, value in changes.items():
                    args += ["--token", key + "=" + value] if value is not None else ["--clear-token", key]
                run_herdr(herdr, *args)
        mode = "workspace" if clear else settings["order"]
        view_path = state / "view.json"
        if clear or restore_view or read_state(view_path).get("order") != mode:
            apply_view(mode)
            view_path.write_text(json.dumps({"order": mode}), encoding="utf-8")
        pending = not clear and (activity.next_deadline is not None or bool(rows))
        if pending or (state / "deadline.lock").exists():
            from deadline import ensure_timer
            ensure_timer(state, start=pending)


def changed_tokens(existing, desired):
    return {key: value for key, value in desired.items() if existing.get(key) != value}


def main():
    parser = argparse.ArgumentParser(description="Refresh the Herdr workspace/tab/agent sidebar.")
    parser.add_argument("--clear", action="store_true", help="clear this plugin's display tokens")
    parser.add_argument("--settings", action="store_true", help="run the settings popup")
    parser.add_argument("--settings-open", action="store_true", help="open the settings popup")
    parser.add_argument("--restore-view", action="store_true", help="restore saved ordering on startup")
    parser.add_argument("--context", action="store_true", help="show saved conversation context")
    parser.add_argument("--context-open", action="store_true", help="open saved context for the selected tab")
    args = parser.parse_args()
    if not os.environ.get("HERDR_PLUGIN_STATE_DIR"):
        raise RuntimeError(f"Run through Herdr: herdr plugin action invoke {entry('refresh')} --plugin {PLUGIN_ID}")
    if args.settings or args.settings_open:
        import settings_ui
        settings_ui.open_popup() if args.settings_open else settings_ui.main()
        return
    if args.context or args.context_open:
        import context_ui
        context_ui.open_popup() if args.context_open else context_ui.main()
        return
    refresh(args.clear, restore_view=args.restore_view)


if __name__ == "__main__":
    # Hook output is UTF-8 whatever the Windows code page is.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        main()
    except (RuntimeError, OSError, ValueError) as error:
        print(f"Herdr Sidebar: {error}", file=sys.stderr)
        sys.exit(1)
