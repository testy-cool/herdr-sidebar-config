import tempfile
import unittest
from pathlib import Path

from sidebar import IDENTITY_FILE, desired_rows, folder_identity


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

    def test_icon_and_name_go_before_the_task(self):
        dag = self.folder('dag', 'name = "dag"\nicon = "🔀"\n')
        self.assertEqual(self.rows(agent('p1', dag))['p1']['hs_idle'],
                         '○ 🔀 dag · Fix the nightly flow')

    def test_name_defaults_to_the_folder_and_icon_is_optional(self):
        teo = self.folder('teo', '')
        self.assertEqual(self.rows(agent('p1', teo))['p1']['hs_idle'],
                         '○ teo · Fix the nightly flow')

    def test_folders_without_the_file_are_unchanged(self):
        plain = self.folder('project')
        self.assertEqual(self.rows(agent('p1', plain))['p1']['hs_idle'],
                         '○ Fix the nightly flow')

    def test_only_the_agent_process_folder_counts(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        plain = self.folder('project')
        # The shell started in dag's folder; the agent itself runs elsewhere.
        pane = agent('p1', plain, cwd=dag)
        self.assertEqual(self.rows(pane)['p1']['hs_idle'], '○ Fix the nightly flow')
        self.assertIsNone(folder_identity({'cwd': dag}))

    def test_a_label_that_is_the_name_is_not_repeated(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        pane = agent('p1', dag, terminal_title_stripped='', label='Dag')
        self.assertEqual(self.rows(pane)['p1']['hs_idle'], '○ 🔀 dag')

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

    def test_dimmed_and_working_rows_keep_the_identity(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        rows = self.rows(agent('p1', dag, agent_status='working'), inactive_ids={'w1'})
        self.assertEqual(rows['p1']['hs_working_dim'], '◔ 🔀 dag · Fix the nightly flow')

    def test_identity_wraps_the_pane_name(self):
        dag = self.folder('dag', 'icon = "🔀"\n')
        rows = self.rows(agent('p1', dag, label='review'), pane_names=True)
        self.assertEqual(rows['p1']['hs_idle'], '○ 🔀 dag · review - Fix the nightly flow')


if __name__ == '__main__':
    unittest.main()
