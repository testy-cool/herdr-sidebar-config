import unittest
from unittest.mock import patch
from animation import cache_rows, glyph, publish_frame
from preferences import validate


class AnimationTests(unittest.TestCase):
    def test_off_by_default_and_four_single_cell_frames(self):
        self.assertIs(validate({})['animated_loaders'], False)
        self.assertEqual([glyph(t) for t in (0, .25, .5, .75, 1)], list('◴◷◶◵◴'))
        with self.assertRaises(ValueError):
            validate({'animated_loaders': 'false'})

    def test_cache_only_working_native_agents(self):
        panes = [{'pane_id': p, 'agent': 'codex', 'agent_status': s}
                 for p, s in [('p1', 'working'), ('p2', 'idle')]]
        rows = cache_rows(panes, {'p1': {'hs_working': '◴ Build search'}, 'p2': {}})
        self.assertEqual(rows, [{'pane_id': 'p1', 'agent': 'codex', 'token': 'hs_working', 'text': 'Build search'}])

    @patch('animation.call')
    def test_frames_only_patch_working_token_and_stop_if_disabled(self, call):
        rows = [{'pane_id': 'p1', 'agent': 'codex', 'token': 'hs_working', 'text': 'Build search'}]
        call.return_value = {'plugins': [{'plugin_id': 'testy-cool.herdr-sidebar', 'enabled': True}]}
        self.assertTrue(publish_frame(rows, .5))
        self.assertEqual([c.args[0] for c in call.call_args_list], ['plugin.list', 'pane.report_metadata'])
        self.assertEqual(call.call_args.args[1]['tokens'], {'hs_working': '◶ Build search'})
        call.reset_mock()
        call.return_value = {'plugins': [{'plugin_id': 'testy-cool.herdr-sidebar', 'enabled': False}]}
        self.assertFalse(publish_frame(rows, 1))
        self.assertEqual(call.call_count, 1)
