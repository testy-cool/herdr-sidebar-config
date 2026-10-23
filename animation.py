"""Opt-in single-cell loaders; frame writes use cached labels, never snapshots."""
from ipc import call
from runtime import PLUGIN_ID

STYLES = {
    "dots": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏",
    "orbit": "⠁⠈⠐⠠⢀⡀⠄⠂",
    "pulse": "⣀⣄⣤⣦⣶⣷⣿⣷⣶⣦⣤⣄",
}
INTERVAL = 0.125


def glyph(now, style="dots"):
    frames = STYLES[style]
    return frames[int(now / INTERVAL) % len(frames)]


# What can precede the mark: indentation and the tree in the status-first rows.
TREE = "\u2800 │├└─"


def cache_rows(panes, desired, style="dots"):
    rows = []
    for pane in panes:
        if pane.get("agent") and pane.get("agent_status") == "working":
            values = desired[pane["pane_id"]]
            for token in ("hs_working", "hs_working_dim", "hs_row_working", "hs_row_working_dim"):
                if values.get(token):
                    body = values[token].lstrip(TREE)
                    rows.append({"pane_id": pane["pane_id"], "agent": pane["agent"],
                                 "token": token, "lead": values[token][:len(values[token]) - len(body)],
                                 "text": body.partition(" ")[2], "style": style})
    return rows


def publish_frame(rows, now):
    # A single narrow registry check stops a disabled plugin even if its
    # lifecycle hooks no longer run. No CLI child or agent-list scan per frame.
    plugins = call("plugin.list", {"plugin_id": PLUGIN_ID})["plugins"]
    if not any(p["plugin_id"] == PLUGIN_ID and p["enabled"] for p in plugins):
        return False
    for row in rows:
        mark = glyph(now, row.get("style", "dots"))
        call("pane.report_metadata", {
            "source": "plugin:" + PLUGIN_ID, "pane_id": row["pane_id"],
            "agent": row["agent"], "tokens": {row["token"]: row.get("lead", "") + mark + " " + row["text"]},
        })
    return True
