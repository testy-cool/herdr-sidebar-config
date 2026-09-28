"""Popup behavior against a fake terminal: normalized keys in, preferences out."""
from pathlib import Path
import tempfile
import tomllib
import unittest

import settings_ui


class FakeTerminal:
    def __init__(self, keys, size=(18, 68)):
        self.keys = list(keys)
        self.height, self.width = size
        self.frames, self.rows = [], {}

    def size(self):
        return self.height, self.width

    def clear(self):
        self.rows = {}

    def draw(self, y, x, text, style=None):
        self.rows[y] = (x, text, style)

    def refresh(self):
        self.frames.append(dict(self.rows))

    def key(self):
        return self.keys.pop(0)


class EditorTests(unittest.TestCase):
    def run_editor(self, keys, original=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name, "config.toml")
        if original is not None:
            path.write_text(original, encoding="utf-8")
        applied = []
        terminal = FakeTerminal(keys)
        settings_ui.editor(terminal, path=path, apply=lambda: applied.append(True))
        return path, applied, terminal

    def test_down_right_enter_saves_and_applies(self):
        path, applied, terminal = self.run_editor(["down", "right", "enter"])
        self.assertEqual(tomllib.loads(path.read_text(encoding="utf-8")), {"icons": "font"})
        self.assertEqual(applied, [True])
        self.assertEqual(terminal.frames[0][1][1], "Sidebar settings")

    def test_escape_writes_nothing(self):
        path, applied, _ = self.run_editor(["down", "right", "escape"], original="# mine\n")
        self.assertEqual(path.read_text(encoding="utf-8"), "# mine\n")
        self.assertEqual(applied, [])

    def test_typed_minutes_and_backspace(self):
        keys = ["down", "down", "4", "5", "backspace", "enter"]
        path, _, _ = self.run_editor(keys)
        self.assertEqual(tomllib.loads(path.read_text(encoding="utf-8")), {"inactive_after_seconds": 240.0})

    def test_resize_redraws_without_changes(self):
        path, applied, terminal = self.run_editor(["resize", "escape"])
        self.assertEqual(len(terminal.frames), 2)
        self.assertFalse(path.exists())
        self.assertEqual(applied, [])

    def test_rows_fit_a_narrow_terminal(self):
        terminal = FakeTerminal(["escape"], size=(18, 20))
        with tempfile.TemporaryDirectory() as directory:
            settings_ui.editor(terminal, path=Path(directory, "config.toml"), apply=lambda: None)
        self.assertTrue(all(len(text) <= 16 for _, text, _ in terminal.frames[0].values()))


if __name__ == "__main__":
    unittest.main()
