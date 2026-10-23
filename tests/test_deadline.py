import os
import tempfile
import unittest
from pathlib import Path

from deadline import code_stamp, code_updated


class CodeUpdateTests(unittest.TestCase):
    def test_a_changed_module_counts_once_it_has_settled(self):
        root = Path(tempfile.mkdtemp())
        (root / 'sidebar.py').write_text('a = 1\n', encoding='utf-8')
        (root / 'notes.txt').write_text('not code\n', encoding='utf-8')
        started = code_stamp(root)
        self.assertEqual([name for name, _, _ in started], ['sidebar.py'])
        self.assertFalse(code_updated(started, code_stamp(root), 2e9))
        # Other files do not count.
        (root / 'notes.txt').write_text('changed\n', encoding='utf-8')
        self.assertFalse(code_updated(started, code_stamp(root), 2e9))
        (root / 'sidebar.py').write_text('a = 2\n', encoding='utf-8')
        os.utime(root / 'sidebar.py', ns=(10**18, 10**18))
        stamp = code_stamp(root)
        # Still being written: wait until it has not changed for a second.
        self.assertFalse(code_updated(started, stamp, 1e9 + 0.5))
        self.assertTrue(code_updated(started, stamp, 1e9 + 1))
        # A module added or removed by the update counts too.
        (root / 'host.py').write_text('', encoding='utf-8')
        os.utime(root / 'host.py', ns=(10**18, 10**18))
        self.assertTrue(code_updated(code_stamp(root)[:1], code_stamp(root), 1e9 + 1))


if __name__ == '__main__':
    unittest.main()
