"""Saved context uses the platform terminal and never interacts with an agent."""
import io
import os
import unittest
from unittest.mock import patch

import context_ui
import host


class FakeTerminal:
    def __init__(self, keys, size=(8, 80)):
        self.keys = iter(keys)
        self.dimensions = size
        self.frames = []

    def size(self):
        return self.dimensions

    def clear(self):
        self.frame = []

    def draw(self, y, x, text, style=None):
        self.frame.append((y, x, text))

    def refresh(self):
        self.frames.append(self.frame)

    def key(self):
        return next(self.keys)


class ContextPopupTests(unittest.TestCase):
    def test_open_routes_to_each_platforms_context_pane(self):
        for platform in ('linux', 'macos', 'windows'):
            with self.subTest(platform=platform), patch.object(host, 'PLATFORM', platform), \
                 patch('sidebar.refresh') as refresh, \
                 patch('context_ui.herdr_binary', return_value='herdr'), \
                 patch('context_ui.run_herdr', return_value={
                     'result': {'snapshot': {'focused_tab_id': 'w1:t7'}}}) as cli:
                context_ui.open_popup()
                refresh.assert_called_once_with()
                args = cli.call_args.args
                self.assertEqual(args[:5], ('herdr', 'plugin', 'pane', 'open', '--plugin'))
                self.assertEqual(args[args.index('--entrypoint') + 1], host.entry('context'))
                self.assertEqual(args[args.index('--env') + 1], 'HERDR_CONTEXT_TAB_ID=w1:t7')

    def test_viewer_scrolls_pages_and_exits_without_agent_commands(self):
        terminal = FakeTerminal(['down', 'page_down', 'up', 'page_up', 'resize', 'escape'])
        with patch.dict(os.environ, {'HERDR_CONTEXT_TAB_ID': 'w1:t1',
                                    'HERDR_PLUGIN_STATE_DIR': '/demo/state'}), \
             patch('context_ui.herdr_binary', return_value='herdr'), \
             patch('context_ui.read_json', return_value={}), \
             patch('context_ui.lines_for_tab', return_value=[f'Line {i}' for i in range(20)]), \
             patch('context_ui.run_herdr', return_value={'result': {'snapshot': {}}}) as cli:
            context_ui.viewer(terminal)
        self.assertEqual([frame[0][2] for frame in terminal.frames],
                         ['Line 0', 'Line 1', 'Line 5', 'Line 4', 'Line 0', 'Line 0'])
        cli.assert_called_once_with('herdr', 'api', 'snapshot')

    def test_tiny_terminal_can_close(self):
        terminal = FakeTerminal(['escape'], size=(2, 3))
        with patch.dict(os.environ, {'HERDR_CONTEXT_TAB_ID': 'w1:t1',
                                    'HERDR_PLUGIN_STATE_DIR': '/demo/state'}), \
             patch('context_ui.read_json', return_value={}), \
             patch('context_ui.run_herdr', return_value={'result': {'snapshot': {}}}), \
             patch('context_ui.lines_for_tab', return_value=['A long saved title']):
            context_ui.viewer(terminal)
        self.assertEqual(terminal.frames, [[]])

    @unittest.skipUnless(os.name == 'nt', 'Windows console keys')
    def test_windows_page_keys_are_translated(self):
        import host_windows
        terminal = host_windows._Console(io.StringIO())
        with patch('host_windows.msvcrt.kbhit', return_value=True), \
             patch('host_windows.msvcrt.getwch', side_effect=['\xe0', 'I', '\xe0', 'Q']):
            self.assertEqual(terminal.key(), 'page_up')
            self.assertEqual(terminal.key(), 'page_down')
