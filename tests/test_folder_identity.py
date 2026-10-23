import os
import tempfile
import unittest
from pathlib import Path

from sidebar import BLANK as B, IDENTITY_FILE, desired_rows, folder_identity


def agent(pane_id, folder, **extra):
    return {**dict(pane_id=pane_id, workspace_id='w1', tab_id='t1', agent='claude',
                   agent_status='idle', terminal_title_stripped='Fix the nightly flow',
                   foreground_cwd=folder), **extra}


class FolderIdentityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def folder(self, name, identity=None):
        path = self.root / name
        path.mkdir()
        if identity is not None:
            (path / IDENTITY_FILE).write_text(identity, encoding='utf-8')
        return str(path)

    def rows(self, *panes, **options):
        return desired_rows(list(panes), [{'workspace_id': 'w1', 'label': 'Demo'}],
                            {'t1': 'main'}, **options)

    def test_icon_and_name_fill_the_row_and_the_task_goes_below(self):
        dag = self.folder('dag', 'name = "dag"\nicon = "🔀"\n')
        row = self.rows(agent('p1', dag))['p1']
        self.assertEqual(row['hs_idle'], '○ 🔀 dag')
        # Under the name: logo, Herdr's " · ", the mark and the icon come first.
        self.assertEqual(row['hs_task'], B * 10 + 'Fix the nightly flow')

    def test_name_defaults_to_the_folder_and_icon_is_optional(self):
        teo = self.folder('teo', '')
        row = self.rows(agent('p1', teo))['p1']
        self.assertEqual(row['hs_idle'], '○ teo')
        self.assertEqual(row['hs_task'], B * 7 + 'Fix the nightly flow')

    def test_folders_without_the_file_are_unchanged(self):
        plain = self.folder('project')
        row = self.rows(agent('p1', plain))['p1']
        self.assertEqual(row['hs_idle'], '○ Fix the nightly flow')
        self.assertIsNone(row['hs_task'])

    def test_only_the_agent_process_folder_counts(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        plain = self.folder('project')
        # The shell started in dag's folder; the agent itself runs elsewhere.
        pane = agent('p1', plain, cwd=dag)
        self.assertEqual(self.rows(pane)['p1']['hs_idle'], '○ Fix the nightly flow')
        self.assertIsNone(folder_identity({'cwd': dag}))

    def test_a_label_that_is_the_name_gets_no_task_line(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        row = self.rows(agent('p1', dag, terminal_title_stripped='', label='Dag'))['p1']
        self.assertEqual(row['hs_idle'], '○ 🔀 dag')
        self.assertIsNone(row['hs_task'])

    def test_a_title_that_starts_with_the_name_drops_it_from_the_task(self):
        teresa = self.folder('teresa', 'icon = "🧭"\n')
        named = self.rows(agent('p1', teresa, terminal_title_stripped='teresa · scrapingevals interview'))['p1']
        self.assertEqual(named['hs_idle'], '○ 🧭 teresa')
        self.assertEqual(named['hs_task'], B * 10 + 'scrapingevals interview')
        # Session titles often spell a hyphenated name with spaces, and what
        # is left of "Minion god 12" says nothing.
        hyphenated = self.folder('minion-god', 'icon = "👑"\n')
        spaced = self.rows(agent('p3', hyphenated, terminal_title_stripped='minion-god-12'))['p3']
        self.assertEqual(spaced['hs_idle'], '○ 👑 minion-god')
        self.assertIsNone(spaced['hs_task'])
        # A word that only begins with the name is still a different word.
        dag = self.folder('dag', 'icon = "🔀"\n')
        other = self.rows(agent('p2', dag, terminal_title_stripped='Dagger refactor'))['p2']
        self.assertEqual(other['hs_task'], B * 10 + 'Dagger refactor')

    def test_the_tree_line_carries_on_beside_the_task(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        teo = self.folder('teo', '')
        panes = [agent('p1', dag), agent('p2', teo),
                 dict(pane_id='p3', workspace_id='w1', tab_id='t2')]
        tabs = {'t1': 'main', 't2': 'shell'}
        rows = desired_rows(panes, [{'workspace_id': 'w1', 'label': 'Demo'}], tabs)
        self.assertTrue(rows['p1']['hs_logo'].startswith('├─ '))
        self.assertEqual(rows['p1']['hs_task'], '│' + B * 2 + B * 10 + 'Fix the nightly flow')
        self.assertEqual(rows['p2']['hs_task'], B * 3 + B * 7 + 'Fix the nightly flow')
        short = desired_rows(panes, [{'workspace_id': 'w1', 'label': 'Demo'}], tabs, branch_length='short')
        self.assertEqual(short['p1']['hs_task'], '│' + B + B * 10 + 'Fix the nightly flow')

    def test_broken_or_hostile_files_are_contained(self):
        broken = self.folder('broken', 'icon = "unclosed\n')
        self.assertEqual(self.rows(agent('p1', broken))['p1']['hs_idle'],
                         '○ Fix the nightly flow')
        noisy = self.folder('noisy', 'name = "a\\u001b[31mred\\nname' + 'x' * 60 + '"\nicon = 5\n')
        icon, name = folder_identity({'foreground_cwd': noisy})
        self.assertEqual(icon, '')
        self.assertNotIn('\x1b', name)
        self.assertNotIn('\n', name)
        self.assertLessEqual(len(name), 32)

    def test_files_that_could_stall_or_crash_a_refresh_are_skipped(self):
        if hasattr(os, 'mkfifo'):  # Windows has no named pipes in the filesystem.
            # Opening the pipe itself must not wait for a writer, so a file
            # swapped for a pipe after any path check cannot block either.
            piped = self.folder('piped')
            os.mkfifo(Path(piped) / IDENTITY_FILE)
            self.assertIsNone(folder_identity({'foreground_cwd': piped}))
        folder = self.folder('folder')
        (Path(folder) / IDENTITY_FILE).mkdir()
        self.assertIsNone(folder_identity({'foreground_cwd': folder}))
        nested = self.folder('nested', 'x = ' + '[' * 2000 + ']' * 2000 + '\n')
        self.assertIsNone(folder_identity({'foreground_cwd': nested}))
        large = self.folder('large', 'icon = "🔀"\n# ' + 'x' * 5000 + '\n')
        self.assertIsNone(folder_identity({'foreground_cwd': large}))

    def test_folder_name_fallback_is_cleaned_too(self):
        odd = self.folder('a\x9b31m' + 'b' * 60, '')
        _, name = folder_identity({'foreground_cwd': odd})
        self.assertNotIn('\x9b', name)
        self.assertLessEqual(len(name), 32)

    def test_dimmed_and_working_rows_keep_both_lines(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        row = self.rows(agent('p1', dag, agent_status='working'), inactive_ids={'w1'})['p1']
        self.assertEqual(row['hs_working_dim'], '◔ 🔀 dag')
        self.assertEqual(row['hs_task_dim'], B * 10 + 'Fix the nightly flow')
        self.assertIsNone(row['hs_task'])

    def test_the_pane_name_stays_with_the_task(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        row = self.rows(agent('p1', dag, label='review'), pane_names=True)['p1']
        self.assertEqual(row['hs_idle'], '○ 🔀 dag')
        self.assertEqual(row['hs_task'], B * 10 + 'review - Fix the nightly flow')

    def test_text_logos_shift_the_task_by_their_width(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        row = self.rows(agent('p1', dag, agent='codex'), icons='text')['p1']
        self.assertEqual(row['hs_task'], B * 11 + 'Fix the nightly flow')


if __name__ == '__main__':
    unittest.main()
