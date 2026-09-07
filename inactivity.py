"""Track workspace quiet periods without polling or changing native agent state."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class InactivityResult:
    state: dict
    inactive_ids: frozenset[str]
    next_deadline: float | None


def _timestamp(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def update_inactivity(workspace_ids, panes, previous=None, *, now, timeout=600.0):
    """Return JSON-safe state, dimmed IDs, and the next one-shot wake deadline.

    ``now`` and ``next_deadline`` are Unix wall timestamps so saved state remains
    useful across short-lived refresh processes and restarts. The caller should
    schedule one wake at the deadline, then obtain a fresh snapshot and call this
    function again. Agent-status events call it immediately. No callback is
    needed once every quiet workspace is inactive or every workspace is working.

    With no valid saved state, quiet workspaces start their ten-minute period at
    the first observation. A backwards clock jump restarts the period rather than
    trusting future timestamps. No focus or title field affects the timer.
    """
    if not _timestamp(now):
        raise ValueError("now must be a finite, nonnegative Unix timestamp")
    if not _timestamp(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    now = float(now)
    workspace_ids = set(workspace_ids)
    previous = previous if isinstance(previous, dict) else {}
    observed_at = previous.get("observed_at")
    old_quiet = previous.get("quiet_since")
    if (
        previous.get("version") != 1
        or not _timestamp(observed_at)
        or observed_at > now
        or not isinstance(old_quiet, dict)
    ):
        old_quiet = {}

    working = {
        pane.get("workspace_id")
        for pane in panes
        if pane.get("agent") and pane.get("agent_status") == "working"
    }
    quiet_since = {}
    inactive_ids = set()
    deadlines = []
    for workspace_id in sorted(workspace_ids - working):
        start = old_quiet.get(workspace_id)
        if not _timestamp(start) or start > now or start > observed_at:
            start = now
        quiet_since[workspace_id] = float(start)
        deadline = start + timeout
        if now >= deadline:
            inactive_ids.add(workspace_id)
        else:
            deadlines.append(deadline)

    return InactivityResult(
        state={"version": 1, "observed_at": now, "quiet_since": quiet_since},
        inactive_ids=frozenset(inactive_ids),
        next_deadline=min(deadlines, default=None),
    )
