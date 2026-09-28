"""The manifest declares every hook once per platform and entry ids per the map."""
from pathlib import Path
import tomllib
import unittest

import host

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = tomllib.loads((ROOT / "herdr-plugin.toml").read_text(encoding="utf-8"))
POSIX = ["linux", "macos"]
WINDOWS = ["windows"]


def hooks(kind, platforms):
    return [tuple(entry["command"][len(launcher(platforms)):]) + ((entry.get("on"),))
            for entry in MANIFEST[kind] if entry.get("platforms") == platforms]


def launcher(platforms):
    return ["sh", "run.sh"] if platforms == POSIX else ["cmd", "/c", ".\\run.cmd"]


class ManifestTests(unittest.TestCase):
    def test_supports_every_platform(self):
        self.assertEqual(sorted(MANIFEST["platforms"]), ["linux", "macos", "windows"])

    def test_every_hook_is_limited_to_one_platform_family(self):
        for kind in ("events", "startup", "actions", "panes"):
            for entry in MANIFEST[kind]:
                self.assertIn(entry.get("platforms"), (POSIX, WINDOWS), entry)
                self.assertEqual(entry["command"][:len(launcher(entry["platforms"]))],
                                 launcher(entry["platforms"]), entry)

    def test_windows_mirrors_posix_events_and_startup(self):
        for kind in ("events", "startup"):
            self.assertTrue(hooks(kind, POSIX))
            self.assertEqual(sorted(hooks(kind, WINDOWS)), sorted(hooks(kind, POSIX)))

    def test_entry_ids_follow_the_platform_map(self):
        for kind in ("actions", "panes"):
            for platforms in (POSIX, WINDOWS):
                declared = {entry["id"]: entry["command"][len(launcher(platforms)):]
                            for entry in MANIFEST[kind] if entry["platforms"] == platforms}
                for platform in platforms:
                    ids = host.ENTRIES[platform]
                    expected = {"panes": ["settings"], "actions": ["settings", "refresh", "clear"]}[kind]
                    self.assertEqual(sorted(declared), sorted(ids[name] for name in expected))
                # The same logical entry runs the same arguments everywhere.
                posix = {e["id"]: e["command"][2:] for e in MANIFEST[kind] if e["platforms"] == POSIX}
                for name in declared:
                    logical = next(k for k, v in host.ENTRIES[platforms[0]].items() if v == name)
                    self.assertEqual(declared[name], posix[host.ENTRIES["linux"][logical]])

    def test_posix_ids_are_unchanged(self):
        self.assertEqual(host.ENTRIES["linux"], {"settings": "settings", "refresh": "refresh", "clear": "clear"})
        self.assertEqual(host.ENTRIES["macos"], host.ENTRIES["linux"])

    def test_current_platform_entry(self):
        self.assertEqual(host.entry("refresh"), host.ENTRIES[host.PLATFORM]["refresh"])


if __name__ == "__main__":
    unittest.main()
