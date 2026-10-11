from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from conversation_context import (collect, latest_request, read_json, save_json,
                                  short_title, sleeping_label, tab_changes)


class ConversationContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        home = patch('conversation_context.Path.home', return_value=self.home)
        home.start()
        self.addCleanup(home.stop)
        self.pane = {'pane_id': 'w1:p1', 'tab_id': 'w1:t1', 'workspace_id': 'w1',
                     'cwd': '/demo/project', 'agent': 'codex',
                     'agent_session': {'kind': 'id', 'agent': 'codex', 'value': 'session-1'}}

    def write(self, path, rows):
        path = self.home / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        return path

    def history(self):
        self.write('.codex/history.jsonl', [
            {'session_id': 'session-1', 'text': 'Verify Dify cleanup plan'},
            {'session_id': 'session-2', 'text': 'Wrong conversation'},
            {'session_id': 'session-1', 'text': 'do it'},
            {'session_id': 'session-1', 'text': '# AGENTS.md instructions\nNever use this as a task'},
        ])

    def test_exact_history_skips_followups_and_injected_instructions(self):
        self.history()
        self.assertEqual(latest_request(self.pane), 'Verify Dify cleanup plan')
        custom = self.home / 'custom-codex'
        custom.mkdir()
        (custom / 'history.jsonl').write_text(json.dumps({'session_id': 'session-1', 'text': 'Read native names'}))
        with patch.dict(os.environ, {'CODEX_HOME': str(custom)}):
            self.assertEqual(latest_request(self.pane), 'Read native names')

    def test_codex_uses_exact_rollout_and_checks_header_identity(self):
        path = self.write('rollout.jsonl', [
            {'type': 'session_meta', 'payload': {'id': 'session-1'}},
            {'type': 'response_item', 'payload': {'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'Repair export handling'}, {'type': 'input_image', 'image_url': 'ignored'}]}},
            {'type': 'response_item', 'payload': {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Not an instruction'}]}},
            {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': 'ok'}},
        ])
        db = self.home / '.codex/state_5.sqlite'
        db.parent.mkdir()
        with closing(sqlite3.connect(db)) as connection:
            connection.execute('CREATE TABLE threads (id TEXT, rollout_path TEXT)')
            connection.execute('INSERT INTO threads VALUES (?,?)', ('session-1', str(path)))
            connection.commit()
        self.assertEqual(latest_request(self.pane), 'Repair export handling')
        path.write_text(path.read_text().replace('session-1', 'session-2'))
        self.assertIsNone(latest_request(self.pane))
        path.write_text(json.dumps({'type': 'session_meta', 'payload': []}) + '\n')
        self.assertIsNone(latest_request(self.pane))

    def test_claude_and_pi_read_user_messages_without_scanning_other_sessions(self):
        claude = dict(self.pane, agent='claude', agent_session={'kind': 'id', 'value': 'session-1'})
        self.write('.claude/projects/-demo-project/session-1.jsonl', [
            {'type': 'user', 'sessionId': 'session-1', 'message': {'role': 'user', 'content': 'Check browser reliability'}},
            {'type': 'user', 'sessionId': 'session-2', 'message': {'role': 'user', 'content': 'Wrong session'}},
        ])
        self.assertEqual(latest_request(claude), 'Check browser reliability')
        path = self.write('pi.jsonl', [
            {'type': 'session', 'id': 'session-1'},
            {'type': 'message', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Reconcile article counts'}]}},
        ])
        pi = dict(self.pane, agent='pi', agent_session={'kind': 'path', 'value': str(path)})
        self.assertEqual(latest_request(pi), 'Reconcile article counts')

    def test_cache_survives_release_park_and_wake_without_inventing_state(self):
        self.history()
        self.pane['agent_session']['source'] = 'herdr:codex'
        active = collect([self.pane], {}, {}, now=1)
        shell = {k: v for k, v in self.pane.items() if k not in ('agent', 'agent_session')}
        gap = collect([shell], active, {}, now=2)
        self.assertTrue(gap['records']['w1:p1']['detached'])
        self.assertIsNone(sleeping_label('w1', gap))
        parked = {'w1:p1': {'agent': 'codex', 'uuid': 'session-1', 'workspace_id': 'w1',
                            'tab_id': 'w1:t1', 'cwd': '/demo/project'}}
        sleeping = collect([shell], gap, parked, now=3)
        self.assertEqual(sleeping_label('w1', sleeping), '1 sleeping agent · Verify Dify cleanup plan')
        self.assertEqual(sleeping['records']['w1:p1']['recorded_at'], 1)
        self.assertNotIn('agent', shell)
        self.assertFalse(collect([self.pane], sleeping, {}, now=4)['records']['w1:p1']['sleeping'])

    def test_pi_path_identity_matches_parked_uuid_without_rereading_history(self):
        path = self.write('pi.jsonl', [{'type': 'session', 'id': 'session-1'},
                                     {'type': 'session_info', 'name': 'Saved Pi objective'}])
        pane = dict(self.pane, agent='pi', agent_session={'kind': 'path', 'agent': 'pi', 'value': str(path)})
        active = collect([pane], {}, {}, now=1)
        shell = {k: v for k, v in pane.items() if k not in ('agent', 'agent_session')}
        parked = {'w1:p1': {'agent': 'pi', 'uuid': 'session-1', 'workspace_id': 'w1',
                            'tab_id': 'w1:t1', 'cwd': '/demo/project'}}
        with patch('conversation_context.latest_request', side_effect=AssertionError('must use saved context')):
            sleeping = collect([shell], active, parked, now=2)
        self.assertEqual(sleeping['records']['w1:p1']['title'], 'Saved Pi objective')

    def test_first_install_recovers_a_sleeping_conversation_from_hibernate(self):
        self.history()
        shell = {k: v for k, v in self.pane.items() if k not in ('agent', 'agent_session')}
        parked = {'w1:p1': {'agent': 'codex', 'uuid': 'session-1', 'workspace_id': 'w1',
                            'tab_id': 'w1:t1', 'cwd': '/demo/project'}}
        context = collect([shell], {}, parked, now=3)
        self.assertEqual(context['records']['w1:p1']['title'], 'Verify Dify cleanup plan')
        parked['w1:p1']['cwd'] = '/other/project'
        self.assertEqual(collect([shell], {}, parked, now=4)['records'], {})

    def test_legacy_hibernate_record_uses_native_workspace_and_checks_record_links(self):
        self.history()
        shell = {k: v for k, v in self.pane.items() if k not in ('agent', 'agent_session')}
        # Hibernate 1.1.1 on macOS records the pane key, tab and cwd, but no workspace.
        record = {'agent': 'codex', 'uuid': 'session-1',
                  'tab_id': 'w1:t1', 'cwd': '/demo/project'}
        context = collect([shell], {}, {'w1:p1': record}, now=1)
        self.assertEqual(sleeping_label('w1', context), '1 sleeping agent · Verify Dify cleanup plan')
        self.assertEqual(context['records']['w1:p1']['workspace_id'], 'w1')
        for key, value in [('workspace_id', 'w2'), ('workspace_id', None),
                           ('tab_id', 'w2:t1'), ('cwd', '/another/project')]:
            with self.subTest(key=key, value=value):
                stale = dict(record, **{key: value})
                self.assertEqual(collect([shell], {}, {'w1:p1': stale}, now=2)['records'], {})
        self.assertEqual(collect([shell], {}, {'w2:p1': record}, now=2)['records'], {})

    def test_sleeping_count_counts_panes_even_when_their_titles_are_shared(self):
        record = {'workspace_id': 'w1', 'tab_id': 'w1:t1', 'sleeping': True,
                  'title': 'Verify Dify cleanup plan'}
        context = {'records': {'w1:p1': record, 'w1:p2': dict(record),
                               'w1:p3': dict(record, sleeping=False),
                               'w2:p1': dict(record, workspace_id='w2', tab_id='w2:t1')}}
        self.assertEqual(sleeping_label('w1', context), '2 sleeping agents · Verify Dify cleanup plan')
        self.assertIsNone(sleeping_label('w3', context))

    def test_reused_and_closed_panes_do_not_inherit_old_context(self):
        self.history()
        old = collect([self.pane], {}, {}, now=1)
        new = dict(self.pane, agent_session={'kind': 'id', 'value': 'new-session'})
        self.assertEqual(collect([new], old, {}, now=2)['records'], {})
        self.assertEqual(collect([], old, {}, now=2)['records'], {})

    def test_unchanged_observation_keeps_saved_time_and_uses_manual_title(self):
        self.history()
        pane = dict(self.pane, tokens={'hs_title': 'project'})
        first = collect([pane], {}, {}, now=1)
        second = collect([pane], first, {}, now=10)
        self.assertEqual(first, second)
        self.assertEqual(second['records']['w1:p1']['title'], 'project')

    def test_only_generic_or_unchanged_owned_tabs_are_renamed(self):
        self.history()
        context = collect([self.pane], {}, {}, now=1)
        tabs = [{'tab_id': 'w1:t1', 'label': 'main'}]
        self.assertEqual(tab_changes(tabs, context), [('w1:t1', 'main', 'Verify Dify cleanup plan')])
        for label in ('Client search', '📌 main', '💤 main'):
            self.assertEqual(tab_changes([dict(tabs[0], label=label)], context), [])
        context['owned_tabs']['w1:t1'] = {'label': 'Old automatic title'}
        self.assertEqual(tab_changes([dict(tabs[0], label='Old automatic title')], context),
                         [('w1:t1', 'Old automatic title', 'Verify Dify cleanup plan')])
        self.assertEqual(tab_changes([dict(tabs[0], label='My manual title')], context), [])
        self.assertEqual(context['owned_tabs'], {})

    def test_distinct_goals_in_one_tab_are_not_mislabeled(self):
        self.history()
        context = collect([self.pane], {}, {}, now=1)
        context['records']['w1:p2'] = dict(context['records']['w1:p1'], title='Another assignment')
        change = tab_changes([{'tab_id': 'w1:t1', 'label': 'main'}], context)[0]
        self.assertIn(' / ', change[2])
        self.assertIn('Another', change[2])
        self.assertLessEqual(len(change[2]), 40)

    def test_context_file_is_private_atomic_and_unchanged_refresh_does_not_write(self):
        path = self.home / 'state/context.json'
        value = {'version': 1, 'records': {'title': '中文会话'}}
        save_json(path, value)
        # Windows inherits user-directory ACLs; chmod has no POSIX mode bits.
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        mtime = path.stat().st_mtime_ns
        save_json(path, value)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        path.write_text('[]')
        self.assertEqual(read_json(path), {})
        path.write_text('x' * 100)
        self.assertEqual(read_json(path, limit=10), {})
        self.assertLessEqual(len(short_title('One useful objective ' * 10)), 40)
        self.assertLessEqual(len(short_title('任務' * 30)), 20)
