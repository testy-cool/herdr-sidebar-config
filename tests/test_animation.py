import unittest
from unittest.mock import patch
from animation import STYLES, cache_rows, glyph, publish_frame
from preferences import validate
from sidebar import desired_rows


class AnimationTests(unittest.TestCase):
    def test_off_by_default_and_smooth_dot_frames(self):
        self.assertIs(validate({})['animated_loaders'], False)
        self.assertEqual(validate({})['loader_style'], 'dots')
        self.assertEqual([glyph(i / 8) for i in range(11)], list('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⠋'))
        with self.assertRaises(ValueError):
            validate({'animated_loaders': 'false'})

    def test_styles_use_one_braille_grid_and_wrap(self):
        for style, frames in STYLES.items():
            self.assertTrue(all(0x2801 <= ord(frame) <= 0x28ff for frame in frames))
            self.assertEqual(glyph(len(frames) / 8, style), frames[0])
        with self.assertRaises(ValueError):
            validate({'loader_style': 'unknown'})

    def test_cache_only_working_native_agents(self):
        panes = [{'pane_id': p, 'agent': 'codex', 'agent_status': s}
                 for p, s in [('p1', 'working'), ('p2', 'idle')]]
        rows = cache_rows(panes, {'p1': {'hs_working': '⠋ Build search'}, 'p2': {}}, 'orbit')
        self.assertEqual(rows, [{'pane_id': 'p1', 'agent': 'codex', 'token': 'hs_working', 'lead': '', 'text': 'Build search', 'style': 'orbit'}])

    @patch('animation.call')
    def test_frames_keep_the_tree_and_label_of_generated_rows(self, call):
        # Both layouts' working tokens, built by the real row generator.
        panes = [dict(pane_id=p, workspace_id='w1', tab_id=t, agent='claude', agent_status='working',
                      terminal_title_stripped='Build search') for p, t in [('p1', 't1'), ('p2', 't1')]]
        panes.append(dict(pane_id='s1', workspace_id='w1', tab_id='t2'))
        for length in ('standard', 'short'):
            desired = desired_rows(panes, [{'workspace_id': 'w1', 'label': 'Demo'}], {'t1': 'One', 't2': 'Two'},
                                   working_glyph=glyph(0), branch_length=length)
            rows = cache_rows(panes, desired)
            self.assertEqual(len(rows), 4)
            call.return_value = {'plugins': [{'plugin_id': 'testy-cool.herdr-sidebar', 'enabled': True}]}
            for row in rows:
                publish_frame([row], .125)
                frame = desired[row['pane_id']][row['token']].replace(glyph(0), glyph(.125), 1)
                self.assertEqual(call.call_args.args[1]['tokens'], {row['token']: frame})
                self.assertNotEqual(frame, desired[row['pane_id']][row['token']])

    @patch('animation.call')
    def test_frames_only_patch_working_token_and_stop_if_disabled(self, call):
        rows = [{'pane_id': 'p1', 'agent': 'codex', 'token': 'hs_working', 'text': 'Build search'}]
        call.return_value = {'plugins': [{'plugin_id': 'testy-cool.herdr-sidebar', 'enabled': True}]}
        self.assertTrue(publish_frame(rows, .5))
        self.assertEqual([c.args[0] for c in call.call_args_list], ['plugin.list', 'pane.report_metadata'])
        self.assertEqual(call.call_args.args[1]['tokens'], {'hs_working': '⠼ Build search'})
        for style in STYLES:
            rows[0]['style'] = style
            publish_frame(rows, 0)
            self.assertEqual(call.call_args.args[1]['tokens'], {'hs_working': STYLES[style][0] + ' Build search'})
        call.reset_mock()
        call.return_value = {'plugins': [{'plugin_id': 'testy-cool.herdr-sidebar', 'enabled': False}]}
        self.assertFalse(publish_frame(rows, 1))
        self.assertEqual(call.call_count, 1)
