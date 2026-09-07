"""Move whole workspaces; never reorder their tabs or agent panes."""
from ipc import call
from runtime import PLUGIN_ID


def order_groups(panes, workspaces, mode):
    if mode == "workspace":
        return panes, {}
    activity = {w["workspace_id"]: [False, 0] for w in workspaces}
    for pane in panes:
        if pane.get("agent"):
            fact = activity.setdefault(pane["workspace_id"], [False, 0])
            fact[0] |= pane.get("agent_status") == "working"
            seq = pane.get("state_change_seq") or 0
            fact[1] = max(fact[1], seq)
    # Python's stable sort leaves equal groups in native workspace order.
    ordered = sorted(activity, key=lambda wid: (-activity[wid][0], -activity[wid][1]))
    ranks = {wid: f"{i:012d}" for i, wid in enumerate(ordered)}
    return sorted(panes, key=lambda pane: ranks[pane["workspace_id"]]), ranks


def apply_view(mode):
    source = "plugin:" + PLUGIN_ID
    if mode == "workspace":
        return call("agent.view.clear", {"source": source})
    return call("agent.view.set", {
        "source": source, "label": "activity",
        "sort": [{"field": {"token": "hs_workspace_rank"}, "order": "asc"},
                 {"field": "tab_order", "order": "asc"},
                 {"field": "pane_order", "order": "asc"}],
    })
