import tempfile
import unittest
from pathlib import Path

from sidebar import BLANK as B, IDENTITY_FILE, child_parents, desired_rows
from runtime import logo_for

C = logo_for('claude', 'font')
X = logo_for('codex', 'font')
WORKSPACES = [{'workspace_id': 'w1', 'label': 'Demo'}]


def agent(pane_id, parent=None, tab='t1', kind='claude', **extra):
    tokens = {'hs_parent': parent} if parent else {}
    return {**dict(pane_id=pane_id, workspace_id='w1', tab_id=tab, agent=kind,
                   agent_status='idle', terminal_title_stripped='Task ' + pane_id,
                   tokens=tokens), **extra}


class ChildRowTests(unittest.TestCase):
    def test_a_child_right_after_its_opener_is_drawn_under_its_logo(self):
        rows = desired_rows([agent('p1'), agent('p2', 'p1', kind='codex')], WORKSPACES, {'t1': 'main'})
        self.assertEqual(rows['p1']['hs_logo'], B + C)
        # First-row offset, then the branch under the parent's logo.
        self.assertEqual(rows['p2']['hs_logo'], B * 2 + B + '└─ ' + B + X)

    def test_siblings_and_grandchildren_get_their_own_branches(self):
        panes = [agent('p1'), agent('p2', 'p1'), agent('p3', 'p2'), agent('p4', 'p1')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'})
        self.assertEqual(rows['p2']['hs_logo'], B * 2 + B + '├─ ' + B + C)
        # p2 is not the last child, so its line carries on beside p3.
        self.assertEqual(rows['p3']['hs_logo'], B * 2 + B + '│' + B * 2 + B + '└─ ' + B + C)
        self.assertEqual(rows['p4']['hs_logo'], B * 2 + B + '└─ ' + B + C)

    def test_children_sit_inside_the_tab_tree(self):
        panes = [agent('p1'), agent('p2', 'p1'), agent('p3'),
                 dict(pane_id='s1', workspace_id='w1', tab_id='t2')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main', 't2': 'shell'})
        self.assertEqual(rows['p1']['hs_logo'], '├─ ' + B + C)
        # The tab's line carries on past the child to p3.
        self.assertEqual(rows['p2']['hs_logo'], B * 2 + '│' + B * 2 + B + '└─ ' + B + C)
        self.assertEqual(rows['p3']['hs_logo'], B * 2 + '└─ ' + B + C)
        short = desired_rows(panes, WORKSPACES, {'t1': 'main', 't2': 'shell'}, branch_length='short')
        self.assertEqual(short['p2']['hs_logo'], B * 2 + '│' + B + B + '└ ' + B + C)

    def test_a_tag_is_ignored_unless_the_child_follows_its_opener(self):
        # Another top-level agent between them, a closed opener, an opener in
        # another tab, and an opener that comes after the child.
        panes = [agent('p1'), agent('p3'), agent('p2', 'p1'), agent('p4', 'gone'),
                 agent('p5', 'p6'), agent('p6'), agent('p7', 'p1', tab='t2')]
        parents = child_parents(panes, {'w1': {'t1': ['p1', 'p3', 'p2', 'p4', 'p5', 'p6'], 't2': ['p7']}})
        self.assertEqual(parents, dict.fromkeys(['p1', 'p3', 'p2', 'p4', 'p5', 'p6', 'p7']))

    def test_an_opener_in_the_tab_before_is_not_a_parent(self):
        # The opener is the last agent of t1, right before the tab boundary.
        panes = [agent('p1'), agent('p2', 'p1', tab='t2')]
        self.assertEqual(child_parents(panes, {'w1': {'t1': ['p1'], 't2': ['p2']}}),
                         {'p1': None, 'p2': None})

    def test_the_opener_task_line_drops_a_line_to_its_children(self):
        folder = Path(tempfile.mkdtemp()) / 'dag'
        folder.mkdir()
        (folder / IDENTITY_FILE).write_text('icon = "🔀"\n', encoding='utf-8')
        panes = [agent('p1', foreground_cwd=str(folder)), agent('p2', 'p1')]
        rows = desired_rows(panes, WORKSPACES, {'t1': 'main'})
        self.assertEqual(rows['p1']['hs_task'], B + '│' + B * 8 + 'Task p1')
        alone = desired_rows(panes[:1], WORKSPACES, {'t1': 'main'})
        self.assertEqual(alone['p1']['hs_task'], B * 10 + 'Task p1')


if __name__ == '__main__':
    unittest.main()
