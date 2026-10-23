import tempfile
import unittest
from pathlib import Path

from sidebar import BLANK as B, IDENTITY_FILE, desired_rows
from runtime import logo_for

C = logo_for('claude', 'font')
WORKSPACES = [{'workspace_id': 'w1', 'label': 'Demo'}]
ICON = '\U000F0BCA'


def agent(pane_id, folder=None, tab='t1', **extra):
    pane = dict(pane_id=pane_id, workspace_id='w1', tab_id=tab, agent='claude',
                agent_status='idle', terminal_title_stripped='Task ' + pane_id, tokens={})
    if folder:
        pane['foreground_cwd'] = str(folder)
    return {**pane, **extra}


class StatusFirstRowTests(unittest.TestCase):
    def folder(self, name, icon=ICON):
        root = Path(tempfile.mkdtemp()) / name
        root.mkdir()
        (root / IDENTITY_FILE).write_text(f'icon = "{icon}"\n' if icon else '', encoding='utf-8')
        return root

    def test_the_mark_leads_and_the_task_starts_under_the_icon(self):
        rows = desired_rows([agent('p1', self.folder('scraper'))], WORKSPACES, {'t1': 'main'})['p1']
        self.assertEqual(rows['hs_row_idle'], B + '○ ' + ICON + ' scraper')
        self.assertEqual(rows['hs_row_logo'], C)
        # Mark, then a space, then the icon: the task's first letter sits there.
        self.assertEqual(rows['hs_row_task'], B * 3 + 'Task p1')

    def test_a_name_without_an_icon_puts_the_task_under_the_name(self):
        rows = desired_rows([agent('p1', self.folder('dag', icon=''))], WORKSPACES, {'t1': 'main'})['p1']
        self.assertEqual(rows['hs_row_idle'], B + '○ dag')
        self.assertEqual(rows['hs_row_task'], B * 3 + 'Task p1')

    def test_the_pane_name_moves_up_beside_the_agent_name(self):
        scraper = self.folder('scraper')
        panes = [agent('p1', scraper, name='joshua'), agent('p2', scraper, name='scraper')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'}, pane_names=True)
        self.assertEqual(rows['p1']['hs_row_idle'], B + '○ ' + ICON + ' scraper · joshua')
        self.assertEqual(rows['p1']['hs_row_task'], B * 3 + 'Task p1')
        # With no title of its own, the task would only repeat the pane name.
        untitled = desired_rows([agent('p3', scraper, name='joshua', terminal_title_stripped='')],
                                WORKSPACES, {'t1': 'main'}, pane_names=True)['p3']
        self.assertEqual(untitled['hs_row_idle'], B + '○ ' + ICON + ' scraper · joshua')
        self.assertIsNone(untitled['hs_row_task'])
        # A pane name that starts with the agent's name adds only the rest.
        teresa = self.folder('teresa')
        named = desired_rows([agent('p4', teresa, name='teresa · scrapingevals interview')],
                             WORKSPACES, {'t1': 'main'}, pane_names=True)['p4']
        self.assertEqual(named['hs_row_idle'], B + '○ ' + ICON + ' teresa · scrapingevals interview')
        self.assertEqual(named['hs_row_task'], B * 3 + 'Task p4')
        # Unlike a title's session number, a pane name's number tells panes apart.
        numbered = desired_rows([agent('p5', scraper, name='scraper-2')], WORKSPACES, {'t1': 'main'}, pane_names=True)['p5']
        self.assertEqual(numbered['hs_row_idle'], B + '○ ' + ICON + ' scraper · 2')
        # A pane named like its agent says nothing new.
        self.assertEqual(rows['p2']['hs_row_idle'], B * 3 + '○ ' + ICON + ' scraper')
        # The older rows keep the pane name in front of the task.
        self.assertEqual(rows['p1']['hs_task'], B * 9 + 'joshua - Task p1')

    def test_tree_rows_lose_the_blank_before_the_mark(self):
        folder = self.folder('teresa')
        panes = [agent('p1', folder), agent('p2', folder), dict(pane_id='s1', workspace_id='w1', tab_id='t2')]
        for length, branch, rest in (('standard', '─ ', B * 2), ('short', ' ', B)):
            rows = desired_rows(panes, WORKSPACES, {'t1': 'misc', 't2': 'shell'}, branch_length=length)
            self.assertEqual(rows['p1']['hs_row_idle'], '├' + branch + '○ ' + ICON + ' teresa')
            self.assertEqual(rows['p1']['hs_row_task'], '│' + rest + B * 2 + 'Task p1')
            # The last agent in a tab is a first row, so it gets the two-cell offset.
            self.assertEqual(rows['p2']['hs_row_idle'], B * 2 + '└' + branch + '○ ' + ICON + ' teresa')
            self.assertEqual(rows['p2']['hs_row_task'], B + rest + B * 2 + 'Task p2')

    def test_a_child_branches_from_its_openers_mark(self):
        panes = [agent('p1', self.folder('minion-god')),
                 agent('p2', agent='codex', tokens={'hs_parent': 'p1'}, terminal_title_stripped='Review')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'})
        # The opener's mark is one cell in; a line drops from it past the task.
        self.assertEqual(rows['p1']['hs_row_task'], B + '│' + B + 'Task p1')
        self.assertEqual(rows['p2']['hs_row_idle'], B * 2 + B + '└── ○ Review')
        self.assertEqual(rows['p2']['hs_row_logo'], logo_for('codex', 'font'))
        self.assertIsNone(rows['p2']['hs_row_task'])

    def test_an_agent_named_only_by_its_pane_gets_two_lines(self):
        rows = desired_rows([agent('p1', name='joshua')], WORKSPACES, {'t1': 'main'}, pane_names=True)['p1']
        self.assertEqual(rows['hs_row_idle'], B + '○ joshua')
        self.assertEqual(rows['hs_row_task'], B * 3 + 'Task p1')
        # The older rows keep "{pane name} - {task}".
        self.assertEqual(rows['hs_idle'], '○ joshua - Task p1')
        # A title that starts with the pane name gives only the rest.
        review = desired_rows([agent('p2', name='codex review', terminal_title_stripped='codex review · Assess the run')],
                              WORKSPACES, {'t1': 'main'}, pane_names=True)['p2']
        self.assertEqual((review['hs_row_idle'], review['hs_row_task']), (B + '○ codex review', B * 3 + 'Assess the run'))

    def test_unnamed_agents_without_a_pane_name_keep_one_line(self):
        rows = desired_rows([agent('p1')], WORKSPACES, {'t1': 'main'}, pane_names=True)['p1']
        self.assertEqual(rows['hs_row_idle'], B + '○ Task p1')
        self.assertIsNone(rows['hs_row_task'])
        # With nothing described, the stand-in fills the one line.
        bare = desired_rows([agent('p2', terminal_title_stripped='')], WORKSPACES, {'t1': 'main'})['p2']
        self.assertEqual(bare['hs_row_idle'], B + '○ Claude session')

    def test_a_named_agent_shows_no_stand_in_task(self):
        # Pi's fixed title names the agent's own folder, even when its shell
        # started in another agent's folder; the tab's label and "pi session"
        # are stand-ins, so nothing goes on the second line.
        gate = self.folder('gatekeeper')
        pane = agent('p1', gate, agent='pi', cwd='/x/agents/teresa', terminal_title_stripped='π - gatekeeper')
        rows = desired_rows([pane], WORKSPACES, {'t1': '1 · gatekeeper › main › pi'})['p1']
        self.assertEqual(rows['hs_row_idle'], B + '○ ' + ICON + ' gatekeeper')
        self.assertIsNone(rows['hs_row_task'])

    def test_dimmed_and_accented_logos(self):
        panes = [agent('p1', self.folder('dag')), agent('p2', agent='kimchi')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'}, inactive_pane_ids=frozenset({'p1'}))
        self.assertIsNone(rows['p1']['hs_row_idle'])
        self.assertEqual(rows['p1']['hs_row_idle_dim'], B + '○ ' + ICON + ' dag')
        self.assertEqual(rows['p1']['hs_row_task_dim'], B * 3 + 'Task p1')
        self.assertEqual(rows['p1']['hs_row_logo_dim'], C)
        self.assertIsNone(rows['p2']['hs_row_logo'])
        self.assertEqual(rows['p2']['hs_row_logo_kimchi'], logo_for('kimchi', 'font'))


    def test_a_childs_mark_sits_under_its_openers_name(self):
        # Short top-level branches, a long one for each child, the logo before
        # the name: every child's mark lines up with its opener's name.
        scraper = self.folder('scraper')
        panes = [agent('p1', scraper, name='manager'),
                 agent('p2', agent='codex', name='codex review', tokens={'hs_parent': 'p1'},
                       terminal_title_stripped='Assess the run'),
                 agent('p3', agent='codex', tokens={'hs_parent': 'p2'}, terminal_title_stripped='Check it'),
                 agent('p4', agent='codex', tokens={'hs_parent': 'p1'}, terminal_title_stripped='Second look'),
                 agent('p5'), dict(pane_id='s1', workspace_id='w1', tab_id='t2')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'misc', 't2': 'shell'}, branch_length='short',
                            pane_names=True, logo_position='before_name')
        X = logo_for('codex', 'font')
        line = lambda p: rows[p]['hs_row_idle']
        self.assertEqual(line('p1'), '├ ○ ' + C + ' scraper · manager')
        self.assertEqual(line('p2'), B * 2 + '│' + B + '├── ○ ' + X + ' codex review')
        self.assertEqual(rows['p2']['hs_row_task'], '│' + B + '│' + B * 3 + '│' + B + 'Assess the run')
        self.assertEqual(line('p3'), B * 2 + '│' + B + '│' + B * 3 + '└── ○ ' + X + ' Check it')
        self.assertEqual(line('p4'), B * 2 + '│' + B + '└── ○ ' + X + ' Second look')
        self.assertEqual(line('p5'), B * 2 + '└ ○ ' + C + ' Task p5')
        # Herdr adds one cell to a first row and three to the rest, and the
        # opener's line follows a tab heading.
        first = 3 + line('p1').index('scraper')
        for child in ('p2', 'p4'):
            self.assertEqual(1 + line(child).index('○'), first, child)
        # A grandchild's mark sits under its own opener's name the same way.
        self.assertEqual(line('p3').index('○'), line('p2').index('codex review'))


if __name__ == '__main__':
    unittest.main()
