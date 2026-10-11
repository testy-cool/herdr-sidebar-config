import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import host

from configuration import dimmable_spaces, ghostty_mapping, merge_layout, restore_layout, settings_binding
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

    def test_machine_label_stays_on_agent_line_without_extra_heading_rows(self):
        layout = tomllib.loads(FRAGMENT)["ui"]["sidebar"]["agents"]
        for rows in [layout["rows"], *layout["rows_by_agent"].values()]:
            names = [[token if isinstance(token, str) else token["token"] for token in row]
                     for row in rows]
            self.assertEqual(len(names), 5)
            self.assertNotIn("machine", names[0])
            self.assertEqual(sum(row.count("machine") for row in names), 1)
            agent_row = names[3]
            self.assertEqual(agent_row.index("machine"), agent_row.index("$hs_logo_dim") + 1)
            self.assertLess(agent_row.index("machine"), agent_row.index("$hs_working"))

    def test_machine_token_requires_herdr_090(self):
        manifest = Path(__file__).resolve().parents[1] / "herdr-plugin.toml"
        version = tomllib.loads(manifest.read_text())["min_herdr_version"]
        self.assertGreaterEqual(tuple(map(int, version.split("."))), (0, 9, 0))

    def test_empty_config_is_valid(self):
        result = merge_layout("", FRAGMENT)
        self.assertEqual(tomllib.loads(result)["ui"]["agent_panel_sort"], "spaces")

    def test_retired_sleeping_rows_are_removed_without_changing_user_rows(self):
        spaces = {"rows": [["state_icon", "workspace"], [],
                           [{"token": "$hs_parked", "dim": False}],
                           ["$hs_parked", {"token": "branch", "dim": True}],
                           ["git_status"]], "separator": " | "}
        result = dimmable_spaces(spaces)
        self.assertEqual(result, {"rows": [["state_icon",
            {"token": "$hs_space", "dim": False}, {"token": "$hs_space_dim", "dim": True}],
            [], [{"token": "branch", "dim": True}], ["git_status"]], "separator": " | "})
        self.assertEqual(dimmable_spaces(result), result)
        self.assertEqual(spaces["rows"][2], [{"token": "$hs_parked", "dim": False}])

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

    def test_font_mapping_upgrades_to_include_pi(self):
        original = "font-size = 16\nfont-codepoint-map = U+E1A0-U+E1AB=Herdr Sidebar Logos\n"
        expected = original.replace("U+E1AB", "U+E1AC")
        self.assertEqual(ghostty_mapping(original), expected)

    def test_font_mapping_does_not_downgrade_pi(self):
        original = "font-size = 16\nfont-codepoint-map = U+E1A0-U+E1AC=Herdr Sidebar Logos\n"
        self.assertEqual(ghostty_mapping(original), original)

    def test_restore_keeps_later_edits_and_undoes_only_the_sidebar(self):
        original = '''# personal theme
[theme]
name = "tokyo-night"
[ui]
sidebar_width = 42
agent_panel_sort = "priority"
[ui.sidebar.agents]
rows = [["agent"]]
[[keys.command]]
key = "prefix+y"
command = "my-action"
'''
        installed = settings_binding(merge_layout(original, FRAGMENT))
        edited = installed.replace('"tokyo-night"', '"dracula"') + '\n[terminal]\nscrollback = 5000\n'
        result = restore_layout(edited, original, FRAGMENT)
        expected = tomllib.loads(original.replace('"tokyo-night"', '"dracula"'))
        expected["terminal"] = {"scrollback": 5000}
        self.assertEqual(tomllib.loads(result), expected)
        self.assertIn("# personal theme", result)
        self.assertNotIn("hs_", result)

    def test_restore_removes_tables_setup_created(self):
        installed = settings_binding(merge_layout("", FRAGMENT))
        result = restore_layout(installed + '\n[theme]\nname = "dracula"\n', "", FRAGMENT)
        self.assertEqual(tomllib.loads(result), {"theme": {"name": "dracula"}})

    def test_restore_leaves_the_users_own_shortcut(self):
        original = '[[keys.command]]\nkey = "prefix+comma"\ncommand = "mine"\n'
        installed = settings_binding(merge_layout(original, FRAGMENT))
        result = restore_layout(installed + '\n[theme]\nname = "dracula"\n', original, FRAGMENT)
        self.assertEqual(tomllib.loads(result)["keys"], tomllib.loads(original)["keys"])

    def test_restore_preserves_other_plugin_actions_before_and_after_install(self):
        original = ('[[keys.command]]\nkey = "prefix+r"\ntype = "plugin_action"\n'
                    'command = "testy-cool.herdr-sidebar.refresh"\n')
        later = ('\n[[keys.command]]\nkey = "prefix+x"\ntype = "plugin_action"\n'
                 'command = "testy-cool.herdr-sidebar.clear-windows"\n')
        for before in ("", original):
            with self.subTest(original=before):
                installed = settings_binding(merge_layout(before, FRAGMENT))
                restored = restore_layout(installed + later, before, FRAGMENT)
                self.assertEqual(tomllib.loads(restored), tomllib.loads(before + later))

    def test_restore_preserves_a_settings_shortcut_the_user_modified(self):
        installed = settings_binding(merge_layout("", FRAGMENT))
        for old, new in [('key = "prefix+comma"', 'key = "prefix+s"'),
                         ('description = "Sidebar settings"', 'description = "My settings"')]:
            with self.subTest(change=new):
                edited = installed.replace(old, new)
                restored = restore_layout(edited, "", FRAGMENT)
                self.assertEqual(tomllib.loads(restored).get("keys"), tomllib.loads(edited)["keys"])

    def test_restore_matches_parsed_shortcut_on_both_platforms(self):
        later = ('\n[[keys.command]]\nkey = "prefix+x"\ncommand = "mine"\n'
                 '# command = "testy-cool.herdr-sidebar.settings"\n')
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), patch.object(host, "PLATFORM", platform):
                installed = settings_binding(merge_layout("", FRAGMENT))
                # Equivalent TOML syntax is still the setup-owned binding.
                edited = (installed + later).replace('key = "prefix+comma"', "key='prefix+comma'")
                restored = restore_layout(edited, "", FRAGMENT)
                self.assertEqual(tomllib.loads(restored), tomllib.loads(later))

    def test_restore_handles_crlf(self):
        original = '[theme]\r\nname = "tokyo-night"\r\n'
        installed = settings_binding(merge_layout(original, FRAGMENT)).replace("\r\n", "\n").replace("\n", "\r\n")
        result = restore_layout(installed.replace("tokyo-night", "dracula"), original, FRAGMENT)
        self.assertEqual(tomllib.loads(result), {"theme": {"name": "dracula"}})

    def test_restore_after_the_user_deleted_the_shortcut(self):
        installed = settings_binding(merge_layout('[theme]\nname = "a"\n', FRAGMENT))
        # settings_binding appends the shortcut last.
        edited = installed[:installed.index("[[keys.command]]")]
        self.assertEqual(tomllib.loads(restore_layout(edited, '[theme]\nname = "a"\n', FRAGMENT)),
                         {"theme": {"name": "a"}})

    def test_restore_leaves_no_bare_ui_header(self):
        original = '[ui.sidebar]\nwidth = 3\n'
        installed = settings_binding(merge_layout(original, FRAGMENT))
        result = restore_layout(installed + '[theme]\nname = "b"\n', original, FRAGMENT)
        self.assertEqual(tomllib.loads(result), {"ui": {"sidebar": {"width": 3}}, "theme": {"name": "b"}})
        self.assertNotIn("[ui]\n", result)

    def test_restore_brings_back_a_custom_sidebar_and_sort(self):
        original = '[ui]\nagent_panel_sort = "priority"\n[ui.sidebar.agents]\nrows = [["agent"]]\n'
        installed = settings_binding(merge_layout(original, FRAGMENT))
        result = restore_layout(installed + '\n[theme]\nname = "b"\n', original, FRAGMENT)
        expected = tomllib.loads(original)
        expected["theme"] = {"name": "b"}
        self.assertEqual(tomllib.loads(result), expected)

    def test_merge_over_later_edits_keeps_them(self):
        installed = settings_binding(merge_layout('[theme]\nname = "tokyo-night"\n', FRAGMENT))
        edited = installed.replace('"tokyo-night"', '"dracula"')
        self.assertEqual(tomllib.loads(merge_layout(edited, FRAGMENT))["theme"], {"name": "dracula"})

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
