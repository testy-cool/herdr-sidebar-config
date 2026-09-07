import unittest
from unittest.mock import patch
from ordering import order_groups, apply_view
from sidebar import desired_rows


class OrderingTests(unittest.TestCase):
    def setUp(self):
        self.spaces = [{"workspace_id": w, "label": w} for w in ('w1', 'w2', 'w3')]
        self.panes = [dict(workspace_id=w, pane_id=w + p, tab_id=w + t, agent='codex',
                           agent_status=status, state_change_seq=seq, terminal_title='Implement search')
                      for w, p, t, status, seq in [
                          ('w1', ':p1', ':t1', 'idle', 50),
                          ('w1', ':p2', ':t2', 'idle', 40),
                          ('w2', ':p1', ':t1', 'working', 10),
                          ('w2', ':p2', ':t1', 'idle', 90),
                          ('w3', ':p1', ':t1', 'working', 100)]]

    def test_moves_groups_without_reordering_members(self):
        ordered, ranks = order_groups(self.panes, self.spaces, 'activity')
        self.assertEqual([p['pane_id'] for p in ordered], ['w3:p1', 'w2:p1', 'w2:p2', 'w1:p1', 'w1:p2'])
        rows = desired_rows(ordered, self.spaces, {'w1:t1': 'First', 'w1:t2': 'Second'})
        self.assertEqual(rows['w2:p1']['hs_group'], 'w2')
        self.assertIsNone(rows['w2:p2']['hs_group'])
        self.assertEqual(rows['w1:p1']['hs_tab'], 'First')
        self.assertEqual(list(sorted(ranks, key=ranks.get)), ['w3', 'w2', 'w1'])

    def test_default_and_ties_keep_native_order(self):
        self.assertEqual(order_groups(self.panes, self.spaces, 'workspace'), (self.panes, {}))
        for pane in self.panes:
            pane.update(agent_status='working', state_change_seq=1, focused=True)
        self.assertEqual(order_groups(self.panes, self.spaces, 'activity')[0], self.panes)

    @patch('ordering.call')
    def test_clear_is_owned_and_activity_preserves_tab_pane_order(self, call):
        apply_view('workspace')
        self.assertEqual(call.call_args.args, ('agent.view.clear', {'source': 'plugin:testy-cool.herdr-sidebar'}))
        apply_view('activity')
        self.assertEqual(call.call_args.args[1]['sort'][1:], [
            {'field': 'tab_order', 'order': 'asc'}, {'field': 'pane_order', 'order': 'asc'}])
