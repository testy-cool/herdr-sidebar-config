import tempfile
import tomllib
import unittest
from pathlib import Path

from preferences import patch, save, validate
from configuration import settings_binding
from setup_sidebar import classify_preferences, edited_files


class PreferenceTests(unittest.TestCase):
    def test_preserves_comments_and_unrelated_tables(self):
        original = '# mine\nicons = "font" # keep\n[extra]\nanswer = 42\n'
        result = patch(original, {"icons": "text", "inactive_after_seconds": 300})
        self.assertIn('icons = "text" # keep', result)
        self.assertTrue(result.startswith('# mine\n'))
        self.assertEqual(tomllib.loads(result)["extra"], {"answer": 42})
        self.assertEqual(patch(result, {"icons": "text"}), result)

    def test_invalid_preferences_and_concurrent_edit_are_kept(self):
        for value in [True, 0, -1, float('inf'), '10']:
            with self.assertRaises(ValueError):
                validate({"inactive_after_seconds": value})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.toml'
            path.write_text('icons = "text"\n')
            with self.assertRaises(ValueError):
                save(path, 'icons = "font"\n', {"icons": "auto"})
            self.assertEqual(path.read_text(), 'icons = "text"\n')

    def test_setup_retains_editable_preferences_and_legacy_backup(self):
        path = Path('/demo/preferences.toml')
        state = {"files": {str(path): {"before": "original", "installed_sha256": "old"}}}
        classify_preferences(state, path)
        self.assertEqual(edited_files(state), [])
        self.assertEqual(state['files'][str(path)]['before'], 'original')

    def test_shortcut_is_idempotent_and_preserves_conflicts(self):
        result = settings_binding('[ui]\nsidebar_width = 40\n')
        self.assertEqual(settings_binding(result), result)
        conflict = '[[keys.command]]\nkey = "prefix+,"\ncommand = "something-else"\n'
        self.assertEqual(settings_binding(conflict), conflict)
