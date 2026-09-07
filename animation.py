"""Opt-in four-frame loader; frame writes use cached labels, never snapshots."""
from ipc import call
from runtime import PLUGIN_ID

FRAMES = "◴◷◶◵"
INTERVAL = 0.25


def glyph(now):
    return FRAMES[int(now / INTERVAL) % len(FRAMES)]


def cache_rows(panes, desired):
    rows = []
    for pane in panes:
        if pane.get("agent") and pane.get("agent_status") == "working":
            values = desired[pane["pane_id"]]
            for token in ("hs_working", "hs_working_dim"):
                if values.get(token):
                    rows.append({"pane_id": pane["pane_id"], "agent": pane["agent"],
                                 "token": token, "text": values[token].partition(" ")[2]})
    return rows


def publish_frame(rows, now):
    # A single narrow registry check stops a disabled plugin even if its
    # lifecycle hooks no longer run. No CLI child or agent-list scan per frame.
    plugins = call("plugin.list", {"plugin_id": PLUGIN_ID})["plugins"]
    if not any(p["plugin_id"] == PLUGIN_ID and p["enabled"] for p in plugins):
        return False
    mark = glyph(now)
    for row in rows:
        call("pane.report_metadata", {
            "source": "plugin:" + PLUGIN_ID, "pane_id": row["pane_id"],
            "agent": row["agent"], "tokens": {row["token"]: mark + " " + row["text"]},
        })
    return True
