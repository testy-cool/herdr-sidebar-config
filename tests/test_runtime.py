import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import icon_mode, logo_for, herdr_binary
from sidebar import desired_rows, task_label


class RuntimeTests(unittest.TestCase):
    def test_pi_has_a_visible_row_in_font_and_text_modes(self):
        pane = {"pane_id": "p1", "workspace_id": "w1", "tab_id": "t1",
                "agent": "pi", "agent_status": "idle", "name": "Pi review"}
        for mode, logo in (("font", "\ue1ac"), ("text", "PI")):
            with self.subTest(mode=mode):
                values = desired_rows([pane], [{"workspace_id": "w1", "label": "project"}], {}, mode)["p1"]
                self.assertEqual(values["hs_logo"], "\u2800" + logo)
                self.assertEqual(values["hs_idle"], "○ Pi review")

    def test_text_mode_needs_no_font_and_auto_degrades(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONFIG_DIR": directory}):
                with patch("host.font_available", return_value=False):
                    self.assertEqual(icon_mode(), "text")
                Path(directory, "config.toml").write_text('icons = "text"\n')
                self.assertEqual(icon_mode(), "text")
                self.assertEqual(logo_for("codex", "text"), "AI")
                self.assertEqual(logo_for("hermes", "text"), "HER")
                self.assertEqual(logo_for("hermes", "font"), "\ue1aa")
                self.assertEqual(logo_for("kimchi", "text"), "KCH")
                self.assertEqual(logo_for("kimchi", "font"), "\ue1ab")
                Path(directory, "config.toml").write_text('icons = "typo"\n')
                with self.assertRaises(RuntimeError):
                    icon_mode()

    def test_replaced_binary_suffix_is_removed(self):
        with patch.dict(os.environ, {"HERDR_BIN_PATH": "/bin/herdr (deleted)"}):
            with patch("runtime.shutil.which", side_effect=lambda value: value):
                self.assertEqual(herdr_binary(), "/bin/herdr")

    def test_title_override_is_read_but_never_owned(self):
        pane = {"pane_id": "w1:p1", "workspace_id": "w1", "agent": "codex",
                "tokens": {"hs_title": "User title", "other_plugin": "keep"}}
        self.assertEqual(task_label(pane, {}), "User title")
        values = desired_rows([pane], [{"workspace_id": "w1", "label": "project"}], {}, "text")["w1:p1"]
        self.assertNotIn("hs_title", values)
        self.assertNotIn("other_plugin", values)
        self.assertTrue(all(key.startswith("hs_") for key in values))
