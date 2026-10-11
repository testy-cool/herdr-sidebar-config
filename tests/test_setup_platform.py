"""Setup's platform contracts: default paths, entry ids, font detection and records."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import subprocess
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

    def _setup_args(self):
        args = plan_args(self.directory.name, text=False)
        args.font_dir = self.font.parent
        args.state_dir = self.font.parent / "backup"
        args.dry_run, args.json = False, True
        return args

    def test_unregister_preserves_a_later_registration(self):
        for prior in (None, str(self.font.parent / "previous.ttf")):
            with self.subTest(prior=prior):
                later = self.font.parent / "later.ttf"
                self.host_windows.register_font(later, FONT_FAMILY)
                self.host_windows.unregister_font(self.font, FONT_FAMILY, prior)
                self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(later)})

    def test_unregister_restores_previous_registration_after_release(self):
        prior = self.font.parent / "previous.ttf"
        self.host_windows.register_font(self.font, FONT_FAMILY)
        self.host_windows.unregister_font(self.font, FONT_FAMILY)
        self.host_windows.unregister_font(self.font, FONT_FAMILY, str(prior))
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(prior)})

    def _setup_api(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(setup_sidebar, "plugin_info", return_value={
            "plugin_root": str(ROOT), "enabled": True}))
        stack.enter_context(patch.object(setup_sidebar, "plugin_config_dir",
                                        return_value=self.font.parent / "plugin"))
        stack.enter_context(patch.object(setup_sidebar, "run_herdr", return_value={
            "result": {"status": "applied"}}))
        stack.enter_context(patch.object(setup_sidebar.subprocess, "run", return_value=
                                        subprocess.CompletedProcess([], 0, "", "")))
        stack.enter_context(patch.object(setup_sidebar, "emit"))
        return stack.enter_context(patch.object(setup_sidebar, "invoke"))

    def test_install_reinstall_uninstall_restores_registration_at_the_same_path(self):
        self.host_windows.register_font(self.font, FONT_FAMILY)
        args = self._setup_args()
        self._setup_api()
        setup_sidebar.install(args, "herdr")
        setup_sidebar.install(args, "herdr")
        setup_sidebar.uninstall(args, "herdr")
        self.assertEqual(self.font.read_bytes(), b"font")
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(self.font)})

    def test_failed_install_backs_up_registration_before_refresh(self):
        prior = self.font.parent / "previous.ttf"
        self.host_windows.register_font(prior, FONT_FAMILY)
        args = self._setup_args()
        invoke = self._setup_api()
        invoke.side_effect = RuntimeError("refresh failed")
        with self.assertRaisesRegex(RuntimeError, "refresh failed"):
            setup_sidebar.install(args, "herdr")
        state = json.loads((args.state_dir / "install.json").read_text(encoding="utf-8"))
        self.assertEqual(state.get("font"), {"prior": str(prior)})
        invoke.side_effect = None
        setup_sidebar.uninstall(args, "herdr")
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(prior)})

    def test_uninstall_preserves_a_later_font_registration(self):
        for original in (None, self.font.parent / "previous.ttf"):
            with self.subTest(original=original):
                if original is not None:
                    self.host_windows.register_font(original, FONT_FAMILY)
                args = self._setup_args()
                self._setup_api()
                setup_sidebar.install(args, "herdr")
                later = self.font.parent / "later.ttf"
                self.host_windows.register_font(later, FONT_FAMILY)
                setup_sidebar.uninstall(args, "herdr")
                self.assertEqual(self.font.read_bytes(), b"font")
                self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(later)})

    def test_registration_failure_then_retry_keeps_the_first_backup(self):
        prior = self.font.parent / "previous.ttf"
        self.host_windows.register_font(prior, FONT_FAMILY)
        args = self._setup_args()
        self._setup_api()
        register = self.host_windows.Fonts.register

        def interrupted(fonts):
            register(fonts)
            raise RuntimeError("registration interrupted")

        with patch.object(self.host_windows.Fonts, "register", interrupted):
            with self.assertRaisesRegex(RuntimeError, "registration interrupted"):
                setup_sidebar.install(args, "herdr")
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(self.font)})
        setup_sidebar.install(args, "herdr")
        state = json.loads((args.state_dir / "install.json").read_text(encoding="utf-8"))
        self.assertEqual(state["font"], {"prior": str(prior)})
        setup_sidebar.uninstall(args, "herdr")
        self.assertEqual(self._values(), {"Herdr Sidebar Logos Regular (TrueType)": str(prior)})

    def test_install_uninstall_removes_a_new_font_and_registration(self):
        self.font.unlink()
        args = self._setup_args()
        self._setup_api()
        setup_sidebar.install(args, "herdr")
        setup_sidebar.uninstall(args, "herdr")
        self.assertFalse(self.font.exists())
        self.assertEqual(self._values(), {})


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
