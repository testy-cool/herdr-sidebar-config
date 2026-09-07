import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sidebar import task_label, desired_rows, changed_tokens


class SidebarRowsTests(unittest.TestCase):
    def test_working_agent_uses_latest_meaningful_codex_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = Path(tmp) / ".codex" / "history.jsonl"
            history.parent.mkdir()
            history.write_text("\n".join([
                json.dumps({
                    "session_id": "session-1",
                    "ts": 1,
                    "text": "[Image #1] Integrate the worker commits and run the installed Mac acceptance.",
                }),
                "not valid json",
                json.dumps({
                    "session_id": "session-1",
                    "ts": 2,
                    "text": "How's it going?",
                }),
            ]) + "\n")
            pane = {
                "agent": "codex",
                "agent_status": "working",
                "terminal_title_stripped": "augmented-wolf",
                "agent_session": {"kind": "id", "value": "session-1"},
            }
            with patch("sidebar.Path.home", return_value=Path(tmp)):
                self.assertEqual(
                    task_label(pane, {}),
                    "Integrate the worker commits and run the installed Mac acceptance",
                )

    def test_task_ignores_session_path_and_vague_followup(self):
        pane = {"agent": "codex", "terminal_title_stripped":
                "[33] ~/Work/project | Review the launch flow | are you still on …"}
        self.assertEqual(task_label(pane, {}), "Review the launch flow")

    def test_named_session_beats_notification_markup(self):
        pane = {"agent": "claude", "terminal_title_stripped":
                "sidebar-layout-review | [71] ~/Work/project | <task-notification> stuff"}
        self.assertEqual(task_label(pane, {}), "Sidebar layout review")

    def test_paths_never_become_task_labels(self):
        pane = {"agent": "agy", "terminal_title_stripped": "[3] ~/Work/project"}
        self.assertEqual(task_label(pane, {}), "AGY session")

    def test_rows_keep_live_state_and_add_one_group_gap(self):
        panes = [
            {"pane_id": "w1:p1", "workspace_id": "w1", "agent": "codex", "agent_status": "working"},
            {"pane_id": "w1:p2", "workspace_id": "w1", "agent": "claude", "agent_status": "blocked"},
            {"pane_id": "w2:p1", "workspace_id": "w2", "agent": "codex", "agent_status": "done"},
        ]
        rows = desired_rows(panes, [{"workspace_id": "w1", "label": "one"},
                                    {"workspace_id": "w2", "label": "two"}], {})
        self.assertIsNone(rows["w1:p1"]["hs_gap"])
        self.assertIsNone(rows["w1:p2"]["hs_group"])
        self.assertIsNotNone(rows["w1:p2"]["hs_gap"])
        self.assertIsNone(rows["w2:p1"]["hs_gap"])
        self.assertTrue(rows["w1:p1"]["hs_working"].startswith("◔ "))
        self.assertTrue(rows["w1:p2"]["hs_blocked"].startswith("? "))
        self.assertTrue(rows["w2:p1"]["hs_done"].startswith("✓ "))
        self.assertIsNone(rows["w2:p1"]["hs_working"])

    def test_unchanged_rows_do_not_publish_again(self):
        desired = {"hs_group": "project", "hs_working": "⠿ Review", "hs_done": None}
        existing = {"hs_group": "project", "hs_working": "⠿ Review"}
        self.assertEqual(changed_tokens(existing, desired), {})

    def test_quiet_group_dims_and_terminal_only_tab_is_visible(self):
        panes = [
            {"pane_id": "p1", "workspace_id": "w1", "tab_id": "t1", "agent": "codex", "agent_status": "idle"},
            {"pane_id": "p2", "workspace_id": "w1", "tab_id": "t2"},
        ]
        spaces = [{"workspace_id": "w1", "label": "project"}]
        tabs = {"t1": "main", "t2": "explorer"}
        dim = desired_rows(panes, spaces, tabs, inactive_ids={"w1"})
        self.assertIsNone(dim["p1"]["hs_group"])
        self.assertEqual(dim["p1"]["hs_group_dim"], "project")
        self.assertEqual(dim["p1"]["hs_terminals"], "terminals: explorer")
        self.assertIsNone(dim["p1"]["hs_idle"])
        self.assertTrue(dim["p1"]["hs_idle_dim"].startswith("○ "))
        panes[0]["agent_status"] = "working"
        bright = desired_rows(panes, spaces, tabs)
        self.assertEqual(bright["p1"]["hs_group"], "project")
        self.assertIsNone(bright["p1"]["hs_group_dim"])
        self.assertIsNone(bright["p1"]["hs_idle_dim"])
        panes[1]["agent"] = "claude"
        self.assertIsNone(desired_rows(panes, spaces, tabs)["p1"]["hs_terminals"])

    def test_tab_groups_use_compact_tree_guides(self):
        panes = [
            {"pane_id": "w1:p1", "workspace_id": "w1", "tab_id": "w1:t1", "agent": "codex"},
            {"pane_id": "w1:p2", "workspace_id": "w1", "tab_id": "w1:t1", "agent": "claude"},
            {"pane_id": "w1:p3", "workspace_id": "w1", "tab_id": "w1:t2", "agent": "codex"},
        ]
        workspaces = [{"workspace_id": "w1", "label": "project"}]
        rows = desired_rows(panes, workspaces, {"w1:t1": "main", "w1:t2": "docs"})
        self.assertEqual(rows["w1:p1"]["hs_tab"], "main")
        self.assertIsNone(rows["w1:p2"]["hs_tab"])
        self.assertEqual(rows["w1:p3"]["hs_tab"], "\u2800\u2800docs")
        self.assertEqual(rows["w1:p1"]["hs_logo"], "├─ \ue1a1")
        self.assertEqual(rows["w1:p2"]["hs_logo"], "\u2800\u2800└─ \ue1a0")
        self.assertEqual(rows["w1:p3"]["hs_logo"], "└─ \ue1a1")

        # A close/move clears the former heading and updates the remaining branch.
        panes[0].pop("agent")
        panes[2]["tab_id"] = "w1:t1"
        rows = desired_rows(panes, workspaces, {"w1:t1": "renamed"})
        self.assertIsNone(rows["w1:p1"]["hs_tab"])
        self.assertEqual(rows["w1:p2"]["hs_group"], "project")
        self.assertIsNone(rows["w1:p2"]["hs_tab"])
        self.assertIsNone(rows["w1:p3"]["hs_tab"])

    def test_single_tab_uses_compact_rows_until_a_second_tab_exists(self):
        panes = [
            {"pane_id": "w1:p1", "workspace_id": "w1", "tab_id": "w1:t1", "agent": "codex"},
            {"pane_id": "w1:p2", "workspace_id": "w1", "tab_id": "w1:t1", "agent": "claude"},
        ]
        workspaces = [{"workspace_id": "w1", "label": "project"}]
        tabs = {"w1:t1": "named-tab", "w1:t2": "shell"}
        compact = desired_rows(panes, workspaces, tabs)
        self.assertTrue(all(row["hs_tab"] is None for row in compact.values()))
        self.assertEqual(compact["w1:p1"]["hs_logo"], "\ue1a1")
        self.assertEqual(compact["w1:p2"]["hs_logo"], "\u2800\u2800\ue1a0")

        # Count real tabs, including shell-only tabs, so tab identity stays useful.
        panes.append({"pane_id": "w1:p3", "workspace_id": "w1", "tab_id": "w1:t2"})
        expanded = desired_rows(panes, workspaces, tabs)
        self.assertEqual(expanded["w1:p1"]["hs_tab"], "named-tab")
        self.assertIsNone(expanded["w1:p3"]["hs_tab"])
        self.assertEqual(desired_rows(panes[:-1], workspaces, tabs), compact)
