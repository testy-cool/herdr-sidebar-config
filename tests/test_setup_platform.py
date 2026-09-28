"""Setup's platform contracts: default paths, entry ids, font detection and records."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
import uuid
from unittest.mock import patch

import host
from configuration import settings_binding
from runtime import FONT_FAMILY, icon_mode
import setup_sidebar
from setup_sidebar import ROOT, digest, edited_files, plan, restorations

WINDOWS = os.name == "nt"


def plan_args(directory, text):
    root = Path(directory)
    return argparse.Namespace(config=root / "herdr" / "config.toml", text=text,
                              ghostty_config=root / "ghostty" / "config",
                              font_dir=root / "fonts")


class ShortcutTests(unittest.TestCase):
    def test_shortcut_names_this_platforms_settings_entry(self):
        for platform, command in [("linux", "testy-cool.herdr-sidebar.settings"),
                                  ("windows", "testy-cool.herdr-sidebar.settings-windows")]:
            with patch.object(host, "PLATFORM", platform):
                keys = tomllib.loads(settings_binding(""))["keys"]["command"]
            self.assertEqual(keys, [{"key": "prefix+comma", "type": "plugin_action",
                                     "command": command, "description": "Sidebar settings"}])


class PlanTests(unittest.TestCase):
    def test_text_install_plans_no_font_or_terminal_file(self):
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(directory, text=True)
            files = plan(args, Path(directory) / "plugin")
            self.assertNotIn(args.font_dir / setup_sidebar.FONT, files)
            self.assertNotIn(args.ghostty_config, files)

    def test_font_install_plans_the_font(self):
        with tempfile.TemporaryDirectory() as directory:
            args = plan_args(directory, text=False)
            files = plan(args, Path(directory) / "plugin")
            self.assertIn(args.font_dir / setup_sidebar.FONT, files)

    def test_interpreter_record_follows_the_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            config_dir = Path(directory) / "plugin"
            files = plan(plan_args(directory, text=True), config_dir)
            record = config_dir / "python-path.txt"
            if WINDOWS:
                self.assertEqual(files[record], sys.executable.encode("utf-8"))
            else:
                self.assertNotIn(record, files)


class RestoreTests(unittest.TestCase):
    def test_file_already_back_to_its_original_is_not_an_edit(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_bytes(b"original\n")
            state = {"files": {str(path): {"before": base64.b64encode(b"original\n").decode(),
                                           "installed_sha256": "installed"}}}
            self.assertEqual(edited_files(state), [])
            path.write_bytes(b"edited\n")
            self.assertEqual(edited_files(state), [str(path)])

    def test_empty_original_restored_is_not_an_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_bytes(b"")
            state = {"files": {str(path): {"before": "", "installed_sha256": "installed"}}}
            self.assertEqual(edited_files(state, restoring=True), [])

    def test_removal_keeps_edits_a_repeat_install_merged(self):
        # install, switch theme, repeat install (records the merged file), uninstall.
        import base64
        from configuration import merge_layout, settings_binding
        fragment = (ROOT / "sidebar-layout.toml").read_text(encoding="utf-8")
        before = '[theme]\nname = "tokyo-night"\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            merged = settings_binding(merge_layout(before.replace("tokyo-night", "dracula"), fragment))
            path.write_bytes(merged.encode())
            state = {"files": {str(path): {"before": base64.b64encode(before.encode()).decode(),
                                           "installed_sha256": digest(merged.encode())}}}
            restored = restorations(state, path)[str(path)]
            self.assertEqual(tomllib.loads(restored.decode()), {"theme": {"name": "dracula"}})

    def test_unchanged_config_is_restored_byte_for_byte(self):
        import base64
        from configuration import merge_layout, settings_binding
        fragment = (ROOT / "sidebar-layout.toml").read_text(encoding="utf-8")
        before = b'# mine\n[theme]\nname = "a"\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            installed = settings_binding(merge_layout(before.decode(), fragment)).encode()
            path.write_bytes(installed)
            state = {"files": {str(path): {"before": base64.b64encode(before).decode(),
                                           "installed_sha256": digest(installed)}}}
            self.assertEqual(restorations(state, path)[str(path)], before)

    def test_retried_removal_accepts_a_created_file_already_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "python-path.txt"
            state = {"files": {str(path): {"before": None, "installed_sha256": "installed"}}}
            self.assertEqual(edited_files(state, restoring=True), [])
            self.assertEqual(edited_files(state), [str(path)])


@unittest.skipUnless(WINDOWS, "Windows defaults")
class WindowsDefaultTests(unittest.TestCase):
    def test_herdr_config_lives_in_appdata(self):
        environment = {k: v for k, v in os.environ.items() if k != "HERDR_CONFIG_PATH"}
        environment.update(APPDATA=r"C:\Demo\Roaming", LOCALAPPDATA=r"C:\Demo\Local")
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(setup_sidebar.default_config(), Path(r"C:\Demo\Roaming\herdr\config.toml"))
            self.assertEqual(host.font_dir(), Path(r"C:\Demo\Local\Microsoft\Windows\Fonts"))
            os.environ["HERDR_CONFIG_PATH"] = r"C:\Other\config.toml"
            self.assertEqual(setup_sidebar.default_config(), Path(r"C:\Other\config.toml"))


@unittest.skipUnless(WINDOWS, "Windows font registry")
class WindowsFontTests(unittest.TestCase):
    def setUp(self):
        import winreg
        import host_windows
        self.winreg, self.host_windows = winreg, host_windows
        self.key = rf"Software\herdr-sidebar-test\{uuid.uuid4().hex}\Fonts"
        winreg.CreateKey(winreg.HKEY_CURRENT_USER, self.key).Close()
        self.addCleanup(self._remove_test_key)
        patcher = patch.object(host_windows, "FONTS_KEY", self.key)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.font = Path(self.directory.name) / "HerdrSidebarLogos-Regular.ttf"
        self.font.write_bytes(b"font")

    def _remove_test_key(self):
        parts = self.key.split("\\")
        for depth in range(len(parts), 1, -1):
            try:
                self.winreg.DeleteKey(self.winreg.HKEY_CURRENT_USER, "\\".join(parts[:depth]))
            except OSError:
                break

    def _values(self):
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, self.key) as key:
            count = self.winreg.QueryInfoKey(key)[1]
            return dict(self.winreg.EnumValue(key, i)[:2] for i in range(count))

    def test_auto_icons_follow_the_registry(self):
        with tempfile.TemporaryDirectory() as config_dir:
            with patch.dict(os.environ, {"HERDR_PLUGIN_CONFIG_DIR": config_dir}):
                self.assertEqual(icon_mode(), "text")
                self.host_windows.register_font(self.font, FONT_FAMILY)
                self.assertEqual(icon_mode(), "font")

    def test_register_and_unregister_round_trip(self):
        prior = self.host_windows.register_font(self.font, FONT_FAMILY)
        self.assertIsNone(prior)
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(self.font)})
        self.assertTrue(self.host_windows.font_registered(self.font, FONT_FAMILY))
        self.font.unlink()
        self.host_windows.unregister_font(self.font, FONT_FAMILY, prior)
        self.assertEqual(self._values(), {})
        self.assertFalse(self.host_windows.font_registered(self.font, FONT_FAMILY))

    def test_unregister_restores_a_previous_registration(self):
        self.host_windows.register_font(self.font, FONT_FAMILY)
        prior = self.host_windows.register_font(Path(self.directory.name) / "other.ttf", FONT_FAMILY)
        self.assertEqual(prior, str(self.font))
        self.host_windows.unregister_font(Path(self.directory.name) / "other.ttf", FONT_FAMILY, prior)
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(self.font)})


@unittest.skipUnless(WINDOWS, "Windows Terminal settings")
class WindowsTerminalTests(unittest.TestCase):
    def test_fallback_is_read_from_font_face(self):
        import host_windows
        with tempfile.TemporaryDirectory() as directory:
            settings = Path(directory) / "Microsoft" / "Windows Terminal" / "settings.json"
            settings.parent.mkdir(parents=True)
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                self.assertFalse(host_windows.terminal_fallback(FONT_FAMILY))
                settings.write_text('{"profiles": {"defaults": {"font": {"face": "Cascadia Mono"}}}}',
                                    encoding="utf-8")
                self.assertFalse(host_windows.terminal_fallback(FONT_FAMILY))
                settings.write_text('// mine\n{"profiles": {"defaults": {"font": '
                                    '{"face": "Cascadia Mono, Herdr Sidebar Logos"}}}}',
                                    encoding="utf-8")
                self.assertTrue(host_windows.terminal_fallback(FONT_FAMILY))


if __name__ == "__main__":
    unittest.main()
