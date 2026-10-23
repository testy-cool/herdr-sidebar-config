import unittest

from preferences import validate, patch
from sidebar import desired_rows


class BranchLengthTests(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(validate({})['branch_length'], 'standard')
        with self.assertRaises(ValueError):
            validate({'branch_length': 'long'})
        self.assertIn('branch_length = "short"', patch('# keep\n', {'branch_length': 'short'}))

    def test_short_saves_one_cell_and_preserves_every_other_token(self):
        panes = [dict(pane_id=p, workspace_id='w1', tab_id=t, agent='codex', agent_status='idle')
                 for p, t in [('p1','t1'), ('p2','t1'), ('p3','t2')]]
        for inactive in (frozenset(), frozenset({'w1'})):
            args = (panes, [{'workspace_id':'w1', 'label':'Demo'}], {'t1':'One','t2':'Two'})
            standard = desired_rows(*args, inactive_ids=inactive)
            short = desired_rows(*args, inactive_ids=inactive, branch_length='short')
            for pane in panes:
                for key, value in standard[pane['pane_id']].items():
                    # The tree sits in the logo, or in front of the mark in the status-first rows.
                    branched = key in ('hs_logo', 'hs_logo_dim') or key.startswith('hs_row_') and 'logo' not in key and 'task' not in key
                    expected = value.replace('─', '') if value and branched else value
                    self.assertEqual(short[pane['pane_id']][key], expected)
            panes_single = [dict(p, tab_id='t1') for p in panes]
            self.assertEqual(desired_rows(panes_single, args[1], args[2]),
                             desired_rows(panes_single, args[1], args[2], branch_length='short'))
