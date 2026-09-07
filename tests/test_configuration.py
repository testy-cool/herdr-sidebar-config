import tempfile
import tomllib
import unittest
from pathlib import Path

from configuration import ghostty_mapping, merge_layout
from setup_sidebar import digest, edited_files

FRAGMENT = (Path(__file__).resolve().parents[1] / "sidebar-layout.toml").read_text()


class ConfigurationTests(unittest.TestCase):
    def test_merge_preserves_other_settings_and_is_idempotent(self):
        original = '''# personal theme
[theme]
name = "custom"
[ui]
sidebar_width = 42
agent_panel_sort = "priority"
[ui.sidebar.agents]
rows = [["agent"]]
[ui.sidebar.spaces]
rows = [["workspace"]]
[[keys.command]]
key = "prefix+y"
command = "my-action"
'''
        result = merge_layout(original, FRAGMENT)
        parsed = tomllib.loads(result)
        self.assertEqual(parsed["theme"], {"name": "custom"})
        self.assertEqual(parsed["ui"]["sidebar_width"], 42)
        self.assertEqual(parsed["ui"]["sidebar"]["spaces"], {"rows": [[
            {"token": "$hs_space", "dim": False}, {"token": "$hs_space_dim", "dim": True}]]})
        self.assertEqual(parsed["keys"], tomllib.loads(original)["keys"])
        self.assertIn("# personal theme", result)
        self.assertEqual(merge_layout(result, FRAGMENT), result)

    def test_empty_config_is_valid(self):
        result = merge_layout("", FRAGMENT)
        self.assertEqual(tomllib.loads(result)["ui"]["agent_panel_sort"], "spaces")

    def test_unsupported_inline_table_fails_without_changing_input(self):
        original = 'ui = { agent_panel_sort = "priority", sidebar = { agents = { rows = [["agent"]] } } }\n'
        with self.assertRaises(ValueError):
            merge_layout(original, FRAGMENT)

    def test_multiline_string_cannot_silently_lose_data(self):
        original = 'note = """\n[ui.sidebar.agents]\nkeep this text\n"""\n'
        with self.assertRaises(ValueError):
            merge_layout(original, FRAGMENT)

    def test_font_mapping_preserves_existing_settings(self):
        original = "font-size = 16\nkeybind = ctrl+y=copy_to_clipboard\n"
        result = ghostty_mapping(original)
        self.assertTrue(result.startswith(original.rstrip()))
        self.assertEqual(ghostty_mapping(result), result)

    def test_removal_detects_later_edits_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_bytes(b"installed")
            state = {"files": {str(path): {"installed_sha256": digest(b"installed")}}}
            self.assertEqual(edited_files(state), [])
            path.write_bytes(b"user edit")
            self.assertEqual(edited_files(state), [str(path)])
            path.unlink()
            self.assertEqual(edited_files(state), [str(path)])
