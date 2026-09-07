import json
import unittest

from inactivity import update_inactivity


def agent(workspace="w1", status="idle"):
    return {"workspace_id": workspace, "agent": "codex", "agent_status": status}


class InactivityTests(unittest.TestCase):
    def test_ten_minute_boundary_and_no_further_timer_after_dimming(self):
        initial = update_inactivity(["w1"], [agent()], now=1000)
        self.assertEqual(initial.next_deadline, 1600)
        before = update_inactivity(["w1"], [agent()], initial.state, now=1599.9)
        self.assertFalse(before.inactive_ids)
        after = update_inactivity(["w1"], [agent()], before.state, now=1600)
        self.assertEqual(after.inactive_ids, {"w1"})
        self.assertIsNone(after.next_deadline)

    def test_any_working_agent_wakes_workspace_and_next_quiet_period_is_new(self):
        quiet = update_inactivity(["w1"], [agent()], now=1000)
        working = update_inactivity(
            ["w1"], [agent(), agent(status="working")], quiet.state, now=1700
        )
        self.assertFalse(working.inactive_ids)
        self.assertEqual(working.state["quiet_since"], {})
        self.assertIsNone(working.next_deadline)
        stopped = update_inactivity(["w1"], [agent(status="done")], working.state, now=1710)
        self.assertEqual(stopped.next_deadline, 2310)

    def test_focus_title_changes_and_json_restart_preserve_quiet_start(self):
        initial = update_inactivity(["w1"], [agent()], now=1000)
        restarted_state = json.loads(json.dumps(initial.state))
        pane = {**agent(), "focused": True, "terminal_title": "New title"}
        updated = update_inactivity(["w1"], [pane], restarted_state, now=1400)
        self.assertEqual(updated.state["quiet_since"], {"w1": 1000})
        self.assertEqual(updated.next_deadline, 1600)
        self.assertEqual(initial.state["observed_at"], 1000)

    def test_empty_and_blocked_workspaces_are_quiet_and_removed_ones_are_cleared(self):
        initial = update_inactivity(["w1", "w2"], [agent(status="blocked")], now=1000)
        self.assertEqual(initial.state["quiet_since"], {"w1": 1000, "w2": 1000})
        updated = update_inactivity(["w2", "w3"], [], initial.state, now=1200)
        self.assertEqual(updated.state["quiet_since"], {"w2": 1000, "w3": 1200})
        self.assertEqual(updated.next_deadline, 1600)
        next_period = update_inactivity(["w2", "w3"], [], updated.state, now=1600)
        self.assertEqual(next_period.inactive_ids, {"w2"})
        self.assertEqual(next_period.next_deadline, 1800)

    def test_backwards_clock_restarts_quiet_period(self):
        initial = update_inactivity(["w1"], [], now=1000)
        rolled_back = update_inactivity(["w1"], [], initial.state, now=900)
        self.assertEqual(rolled_back.state["quiet_since"], {"w1": 900})
        self.assertEqual(rolled_back.next_deadline, 1500)

    def test_untrusted_or_corrupt_saved_state_starts_fresh(self):
        for previous in [
            None,
            [],
            {"quiet_since": {"w1": 1}},
            {"version": 1, "observed_at": 100, "quiet_since": {"w1": "bad"}},
            {"version": 1, "observed_at": 100, "quiet_since": {"w1": 200}},
            {"version": 1, "observed_at": 100, "quiet_since": {"w1": float("nan")}},
        ]:
            with self.subTest(previous=previous):
                result = update_inactivity(["w1"], [], previous, now=1000)
                self.assertEqual(result.next_deadline, 1600)

    def test_empty_snapshot_needs_no_timer(self):
        result = update_inactivity([], [], now=1000)
        self.assertEqual(result.state["quiet_since"], {})
        self.assertFalse(result.inactive_ids)
        self.assertIsNone(result.next_deadline)
