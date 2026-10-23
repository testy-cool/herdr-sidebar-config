import tempfile
import unittest
from pathlib import Path

from preferences import validate
from sidebar import BLANK as B, IDENTITY_FILE, desired_rows
from runtime import logo_for

C = logo_for('claude', 'font')
WORKSPACES = [{'workspace_id': 'w1', 'label': 'Demo'}]
ICON = '\U000F0BCA'


def agent(pane_id, folder=None, **extra):
    pane = dict(pane_id=pane_id, workspace_id='w1', tab_id='t1', agent='claude',
                agent_status='idle', terminal_title_stripped='Task ' + pane_id, tokens={})
    if folder:
        pane['foreground_cwd'] = str(folder)
    return {**pane, **extra}


class LogoPositionTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp()) / 'scraper'
        self.folder.mkdir()
        (self.folder / IDENTITY_FILE).write_text(f'icon = "{ICON}"\n', encoding='utf-8')

    def test_default_and_validation(self):
        self.assertEqual(validate({})['logo_position'], 'end')
        with self.assertRaises(ValueError):
            validate({'logo_position': 'start'})

    def test_before_the_name_replaces_the_folder_icon(self):
        panes = [agent('p1', self.folder, name='joshua'), agent('p2', agent='kimchi')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'}, pane_names=True, logo_position='before_name')
        self.assertEqual(rows['p1']['hs_row_idle'], B + '○ ' + C + ' scraper · joshua')
        # The task still starts where the icon was, now under the logo.
        self.assertEqual(rows['p1']['hs_row_task'], B * 3 + 'Task p1')
        self.assertIsNone(rows['p1']['hs_row_logo'])
        # An agent without a folder name gets the logo before its task.
        self.assertEqual(rows['p2']['hs_row_idle'], B * 3 + '○ ' + logo_for('kimchi', 'font') + ' Task p2')
        self.assertIsNone(rows['p2']['hs_row_logo_kimchi'])

    def test_dimmed_rows_follow_the_same_order(self):
        rows = desired_rows([agent('p1', self.folder)], WORKSPACES, {'t1': 'main'},
                            inactive_pane_ids=frozenset({'p1'}), logo_position='before_name')['p1']
        self.assertEqual(rows['hs_row_idle_dim'], B + '○ ' + C + ' scraper')
        self.assertIsNone(rows['hs_row_logo_dim'])

    def test_the_older_rows_do_not_change(self):
        panes = [agent('p1', self.folder, name='joshua')]
        end = desired_rows(panes, WORKSPACES, {'t1': 'main'}, pane_names=True)['p1']
        before = desired_rows(panes, WORKSPACES, {'t1': 'main'}, pane_names=True, logo_position='before_name')['p1']
        for key in end:
            if not key.startswith('hs_row_'):
                self.assertEqual(before[key], end[key], key)


if __name__ == '__main__':
    unittest.main()
