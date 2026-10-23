import os
import tempfile
import unittest
from pathlib import Path

import deadline
from deadline import CodeWatch, code_stamp, imports_cleanly


class CodeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for name in ('deadline.py', 'sidebar.py', 'animation.py'):
            (self.root / name).write_text('x = 1\n', encoding='utf-8')

    def write(self, name, text, seconds):
        path = self.root / name
        path.write_text(text, encoding='utf-8')
        os.utime(path, ns=(seconds * 10**9, seconds * 10**9))

    def test_only_modules_count(self):
        started = code_stamp(self.root)
        (self.root / 'notes.txt').write_text('not code\n', encoding='utf-8')
        self.assertEqual(code_stamp(self.root), started)
        self.write('sidebar.py', 'x = 2\n', 5)
        self.assertNotEqual(code_stamp(self.root), started)

    def test_a_change_counts_once_it_has_stayed_the_same_for_a_second(self):
        watch = CodeWatch(code_stamp(self.root), 100)
        self.assertFalse(watch.settled(code_stamp(self.root), 101))
        self.write('sidebar.py', 'x = 2\n', 5)
        changed = code_stamp(self.root)
        self.assertFalse(watch.settled(changed, 102))
        self.assertFalse(watch.settled(changed, 102.5))
        self.assertTrue(watch.settled(changed, 103))

    def test_a_module_missing_mid_update_has_to_settle_too(self):
        started = code_stamp(self.root)
        watch = CodeWatch(started, 100)
        (self.root / 'animation.py').unlink()
        self.assertFalse(watch.settled(code_stamp(self.root), 101))
        # Back before a second passed, unchanged: nothing to hand over.
        self.write('animation.py', 'x = 1\n', 0)
        restored = code_stamp(self.root)
        self.assertFalse(watch.settled(restored, 101.5))
        self.assertTrue(watch.settled(restored, 102.5))
        # Back exactly as it was: no update at all.
        quiet = CodeWatch(started, 100)
        self.assertFalse(quiet.settled(started, 105))

    def test_mtimes_are_not_the_clock(self):
        # A module stamped in the future, as after a wall clock correction,
        # does not hold the handover back.
        self.write('sidebar.py', 'x = 1\n', 10**10)
        watch = CodeWatch(code_stamp(self.root), 100)
        self.write('animation.py', 'x = 2\n', 5)
        changed = code_stamp(self.root)
        watch.settled(changed, 101)
        self.assertTrue(watch.settled(changed, 102))

    def test_the_load_check_needs_what_a_scheduler_imports(self):
        # A copy of the real plugin loads; one with a module emptied, broken
        # or missing does not, even where a plain import would succeed.
        plugin = Path(deadline.__file__).resolve().parent
        for change in (None, ('sidebar.py', ''), ('ipc.py', 'def (\n'), ('animation.py', None)):
            root = Path(tempfile.mkdtemp())
            for module in plugin.glob('*.py'):
                (root / module.name).write_text(module.read_text(encoding='utf-8'), encoding='utf-8')
            if change:
                name, text = change
                if text is None:
                    (root / name).unlink()
                else:
                    (root / name).write_text(text, encoding='utf-8')
            self.assertEqual(imports_cleanly(root), change is None, change)

    def test_a_checkout_that_does_not_load_is_skipped_until_it_changes(self):
        watch = CodeWatch([], 100)
        broken = code_stamp(self.root)
        watch.settled(broken, 101)
        watch.rejected = broken
        self.assertFalse(watch.settled(broken, 105))
        self.write('animation.py', 'x = 1\n', 6)
        fixed = code_stamp(self.root)
        watch.settled(fixed, 106)
        self.assertTrue(watch.settled(fixed, 107))

    def test_the_start_stamp_is_only_taken_by_the_scheduler_process(self):
        # Hooks import this module for ensure_timer and need no stamp.
        self.assertIsNone(deadline.STARTED)
        source = Path(deadline.__file__).read_text(encoding='utf-8')
        # The scheduler takes it before importing any other plugin module.
        self.assertLess(source.index('STARTED = code_stamp()'), source.index('from host import'))


if __name__ == '__main__':
    unittest.main()
