import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from activity_titles import activity_title


class ActivityTitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.home_patch = patch("activity_titles.Path.home", return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def pane(self, agent="codex", session_id="session-1"):
        return {"agent": agent, "cwd": "/work/project", "agent_session": {"kind": "id", "agent": agent, "value": session_id}}

    def write(self, relative, records):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return path

    def database(self, title, name=None, mode="legacy", first="First prompt"):
        path = self.home / ".codex/state_5.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, name TEXT, history_mode TEXT, first_user_message TEXT)")
            db.execute("INSERT INTO threads VALUES (?,?,?,?,?)", ("session-1", title, name, mode, first))

    def test_codex_paginated_uses_native_name_not_first_prompt(self):
        self.database("First prompt", name="Repair remote restore", mode="paginated")
        self.assertEqual(activity_title(self.pane()), "Repair remote restore")

    def test_codex_legacy_distinct_title_precedes_index(self):
        self.database("Repair remote restore")
        self.write(".codex/session_index.jsonl", [{"id": "session-1", "thread_name": "Old title"}])
        self.assertEqual(activity_title(self.pane()), "Repair remote restore")

    def test_codex_derived_first_prompt_falls_back_to_latest_exact_index(self):
        self.database("First prompt")
        self.write(".codex/session_index.jsonl", [
            {"id": "session-1", "thread_name": "Old title"},
            {"id": "session-1", "thread_name": "Repair remote restore"},
            {"id": "session-2", "thread_name": "Wrong agent"}, [],
        ])
        self.assertEqual(activity_title(self.pane()), "Repair remote restore")

    def test_codex_missing_metadata_does_not_create_database(self):
        self.assertIsNone(activity_title(self.pane()))
        self.assertFalse((self.home / ".codex").exists())

    def test_project_name_and_acknowledgement_are_rejected(self):
        for title in ("Project", "project-3f", "yes", "continue"):
            self.write(".codex/session_index.jsonl", [{"id": "session-1", "thread_name": title}])
            self.assertIsNone(activity_title(self.pane()))

    def test_claude_explicit_title_precedes_summary_and_other_sessions(self):
        self.write(".claude/projects/-work-project/session-1.jsonl", [
            {"type": "custom-title", "customTitle": "Repair remote restore", "sessionId": "session-1"},
            {"type": "summary", "summary": "Earlier investigation"},
            {"type": "custom-title", "customTitle": "Wrong agent", "sessionId": "session-2"},
        ])
        self.assertEqual(activity_title(self.pane("claude")), "Repair remote restore")

    def test_claude_native_agent_name(self):
        self.write(".claude/projects/-work-project/session-1.jsonl", [
            {"type": "agent-name", "agentName": "Repair remote restore", "sessionId": "session-1"},
        ])
        self.assertEqual(activity_title(self.pane("claude")), "Repair remote restore")

    def test_claude_generated_title_precedes_default_agent_name(self):
        self.write(".claude/projects/-work-project/session-1.jsonl", [
            {"type": "ai-title", "aiTitle": "Repair remote restore", "sessionId": "session-1"},
            {"type": "agent-name", "agentName": "project-3f", "sessionId": "session-1"},
        ])
        self.assertEqual(activity_title(self.pane("claude")), "Repair remote restore")

    def test_pi_native_name_and_explicit_clear(self):
        records = [{"type": "session", "id": "session-1"}, {"type": "session_info", "name": "Repair remote restore"}]
        self.write(".pi/agent/sessions/--work-project--/2026-09-08_session-1.jsonl", records)
        self.assertEqual(activity_title(self.pane("pi")), "Repair remote restore")
        self.write(".pi/agent/sessions/--work-project--/2026-09-08_session-1.jsonl", records + [{"type": "session_info", "name": ""}])
        self.assertIsNone(activity_title(self.pane("pi")))

    def test_pi_mismatched_session_header_is_rejected(self):
        self.write(".pi/agent/sessions/--work-project--/2026-09-08_session-1.jsonl", [
            {"type": "session", "id": "session-2"}, {"type": "session_info", "name": "Wrong agent"}])
        self.assertIsNone(activity_title(self.pane("pi")))

    def test_bad_input_and_corrupt_storage_are_harmless(self):
        for pane in (None, {}, {"agent_session": "bad"}, self.pane(session_id="../../other")):
            self.assertIsNone(activity_title(pane))
        path = self.write(".codex/session_index.jsonl", [])
        path.write_text("malformed\nnull\n[]\n")
        self.assertIsNone(activity_title(self.pane()))


if __name__ == "__main__":
    unittest.main()
