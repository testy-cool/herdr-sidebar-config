import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from context_ui import lines_for_tab
from sidebar import refresh


class ContextRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('state', 'config', 'codex'):
            (self.root / name).mkdir()
        self.preferences = self.root / 'config/config.toml'
        self.preferences.write_text('icons = "text"\nconversation_titles = true\n')
        (self.root / 'codex/history.jsonl').write_text(json.dumps(
            {'session_id': 'session-1', 'text': 'Repair export handling'}) + '\n')
        env = patch.dict(os.environ, {'HERDR_PLUGIN_STATE_DIR': str(self.root / 'state'),
                         'HERDR_PLUGIN_CONFIG_DIR': str(self.root / 'config'),
                         'HERDR_SIDEBAR_HIBERNATE_STATE': str(self.root / 'hibernate.json'),
                         'CODEX_HOME': str(self.root / 'codex'),
                         'USERPROFILE': str(self.root), 'HOME': str(self.root)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.snapshot = {
            'workspaces': [{'workspace_id': 'w1', 'label': 'Demo', 'tokens': {}}],
            'tabs': [{'tab_id': 'w1:t1', 'workspace_id': 'w1', 'label': 'main'}],
            'panes': [{'pane_id': 'w1:p1', 'workspace_id': 'w1', 'tab_id': 'w1:t1',
                       'cwd': '/demo/project', 'tokens': {}}],
            'agents': [{'pane_id': 'w1:p1', 'workspace_id': 'w1', 'tab_id': 'w1:t1',
                        'agent': 'codex', 'agent_status': 'idle', 'cwd': '/demo/project',
                        'agent_session': {'kind': 'id', 'agent': 'codex', 'value': 'session-1'}}]}
        self.calls = []
        for target, kw in [('sidebar.run_herdr', {'side_effect': self.cli_call}),
                           ('sidebar.apply_view', {}), ('deadline.ensure_timer', {})]:
            mocked = patch(target, **kw)
            mocked.start()
            self.addCleanup(mocked.stop)

    def cli_call(self, binary, *args):
        self.calls.append(args)
        if args[:2] == ('api', 'snapshot'):
            return {'result': {'snapshot': copy.deepcopy(self.snapshot)}}
        if args[:2] == ('tab', 'get'):
            return {'result': {'tab': copy.deepcopy(self.snapshot['tabs'][0])}}
        if args[:2] == ('tab', 'rename'):
            self.snapshot['tabs'][0]['label'] = args[3]
        if args[1] == 'report-metadata':
            items = self.snapshot['workspaces'] if args[0] == 'workspace' else self.snapshot['panes']
            item = next(item for item in items if item[args[0] + '_id'] == args[2])
            for index, value in enumerate(args):
                if value == '--token':
                    key, text = args[index + 1].split('=', 1)
                    item['tokens'][key] = text
                elif value == '--clear-token':
                    item['tokens'].pop(args[index + 1], None)
        return {}

    def context(self):
        return json.loads((self.root / 'state/context.json').read_text())

    def test_refresh_names_tab_and_retains_context_when_agent_is_parked(self):
        refresh()
        self.assertEqual(self.snapshot['tabs'][0]['label'], 'Repair export handling')
        self.assertEqual(self.context()['records']['w1:p1']['request'], 'Repair export handling')
        self.snapshot['agents'] = []
        (self.root / 'hibernate.json').write_text(json.dumps({'w1:p1': {
            'agent': 'codex', 'uuid': 'session-1', 'workspace_id': 'w1',
            'tab_id': 'w1:t1', 'cwd': '/demo/project'}}))
        self.snapshot['tabs'][0]['label'] = '💤 Repair export handling'
        self.snapshot['workspaces'][0]['tokens']['hs_parked'] = '1 sleeping agent · Repair export handling'
        self.calls.clear()
        refresh()
        self.assertNotIn('hs_parked', self.snapshot['workspaces'][0]['tokens'])
        self.assertTrue(self.context()['records']['w1:p1']['sleeping'])
        self.assertTrue(all(call[:2] in [('api', 'snapshot'), ('pane', 'report-metadata'),
                                         ('workspace', 'report-metadata')] for call in self.calls))
        self.assertIn('codex | sleeping', lines_for_tab(self.snapshot, self.context(), 'w1:t1'))

    def test_manual_rename_and_clear_preserve_user_values(self):
        self.snapshot['panes'][0]['tokens'] = {'hs_title': 'My objective', 'other_plugin': 'keep'}
        refresh()
        self.snapshot['tabs'][0]['label'] = 'My manual tab name'
        self.calls.clear()
        refresh()
        self.assertFalse(any(call[:2] == ('tab', 'rename') for call in self.calls))
        before = self.context()
        refresh(clear=True)
        self.assertEqual(self.context(), before)
        self.assertEqual(self.snapshot['panes'][0]['tokens'], {'hs_title': 'My objective', 'other_plugin': 'keep'})

    def test_refresh_uses_individual_deadline_with_a_working_peer(self):
        pane = dict(self.snapshot['panes'][0], pane_id='w1:p2', tokens={})
        worker = dict(self.snapshot['agents'][0], pane_id='w1:p2', agent_status='working',
                      agent_session={'kind': 'id', 'agent': 'codex', 'value': 'session-2'})
        self.snapshot['panes'].append(pane)
        self.snapshot['agents'].append(worker)
        with patch('sidebar.time.time', return_value=1000):
            refresh()
        activity = json.loads((self.root / 'state/activity.json').read_text())
        self.assertEqual(activity['next_deadline'], 1600)
        with patch('sidebar.time.time', return_value=1600):
            refresh()
        idle_tokens = self.snapshot['panes'][0]['tokens']
        self.assertIn('hs_idle_dim', idle_tokens)
        self.assertNotIn('hs_idle', idle_tokens)
        self.assertEqual(idle_tokens['hs_group'], 'Demo')
        self.assertIn('hs_working', self.snapshot['panes'][1]['tokens'])
        self.assertEqual(self.snapshot['workspaces'][0]['tokens']['hs_space'], 'Demo')
        self.assertIsNone(json.loads((self.root / 'state/activity.json').read_text())['next_deadline'])
        self.snapshot['agents'][0]['agent_status'] = 'working'
        with patch('sidebar.time.time', return_value=1601):
            refresh()
        self.assertNotIn('hs_idle_dim', idle_tokens)
        self.assertIn('hs_working', idle_tokens)

    def test_opt_in_and_tab_rename_race_are_respected(self):
        self.preferences.write_text('icons = "text"\n')
        refresh()
        self.assertEqual(self.snapshot['tabs'][0]['label'], 'main')
        self.preferences.write_text('icons = "text"\nconversation_titles = true\n')
        original = self.cli_call
        def raced(binary, *args):
            if args[:2] == ('tab', 'get'):
                self.snapshot['tabs'][0]['label'] = 'Renamed by user'
            return original(binary, *args)
        with patch('sidebar.run_herdr', side_effect=raced):
            refresh()
        self.assertEqual(self.snapshot['tabs'][0]['label'], 'Renamed by user')
        self.assertEqual(self.context()['owned_tabs'], {})
