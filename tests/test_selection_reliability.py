"""Synthetic selection regressions; run only in the isolated offline test copy."""
import copy
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import editorial.select_items as selection
import model_adapter
from pipeline_common import (APPROVAL_ID, ROOT, Invalid, canonical, decisions_valid,
                             digest, lines, load, save_json)


class SelectionReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Path(os.environ.get('PS04_TEST_MIRROR_ROOT', '')).resolve() != ROOT:
            raise RuntimeError('Selection tests require the authorized isolated repository copy')

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='selection-unit-', dir=ROOT / 'runs')
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.items = [dict(item_id=f'feed:unit-{n:02}', version_id=f'{n:064x}',
                           kind='feed', title=f'Source {n}', publisher_id='synthetic',
                           text_path=f'unit/{n}.txt') for n in range(38)]
        self.by = {x['item_id']: x for x in self.items}
        self.decisions = [dict(item_id=x['item_id'], version_id=x['version_id'],
                               decision='accept' if n < 9 else 'defer' if n < 12 else 'reject',
                               reason='Synthetic editorial rationale.',
                               piece_ids=['02'] if n < 9 else [])
                          for n, x in enumerate(self.items)]
        self.history = [dict(item_id=x['item_id'], version_id=x['version_id'],
                             human_decision=self.decisions[n]['decision'].upper(),
                             v2_approval_id=APPROVAL_ID, human_review_status='confirmed',
                             human_decision_provenance='Synthetic historical constraint',
                             publication_authorized=False)
                        for n, x in enumerate(self.items[:12])]
        save_json(self.folder / 'run.json', dict(mode='live', as_of_date='2026-10-14'))
        save_json(self.folder / 'config/project.json', {'purpose': 'Offline unit fixture'})
        (self.folder / 'config/editorial_policy.md').write_bytes(
            (ROOT / 'config/editorial_policy.md').read_bytes())
        (self.folder / 'config/human_decisions_v2.jsonl').write_bytes(lines(self.history))
        (self.folder / 'eligible.jsonl').write_bytes(lines(self.items))
        (self.folder / 'prompts').mkdir()
        (self.folder / 'prompts/select_items.md').write_bytes(
            (ROOT / 'prompts/select_items.md').read_bytes())

    def request(self, inputs=None, items=None):
        with patch.object(model_adapter, 'evidence_view', side_effect=lambda x:
                          dict(item=copy.deepcopy(x), exact_source_text='Full synthetic source.\n')):
            return model_adapter.request_for(self.folder, 'select_items',
                self.items if inputs is None else inputs, self.items if items is None else items)

    def assert_coverage_failure(self, records, *messages):
        with self.assertRaises(Invalid) as exc:
            decisions_valid(records, self.by)
        for message in messages:
            self.assertIn(message, str(exc.exception))
        return str(exc.exception)

    def select(self, output):
        with patch.object(selection, 'validate_items', return_value=self.by), \
             patch.object(selection, 'generate', return_value=copy.deepcopy(output)):
            return selection.select(self.folder, self.items, {})

    def provider(self, raw):
        create = Mock(return_value=types.SimpleNamespace(output_text=raw, usage=None))
        fake = types.SimpleNamespace(OpenAI=lambda: types.SimpleNamespace(
            responses=types.SimpleNamespace(create=create)))
        return create, fake

    def generate_raw(self, raw, metadata=None):
        create, fake = self.provider(raw)
        with patch.object(model_adapter, 'request_for', return_value=self.request()), \
             patch.dict('sys.modules', {'openai': fake}), \
             patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS': '1', 'PS04_MODEL': 'OFFLINE-MOCK'}):
            result = model_adapter.generate(self.folder, 'select_items', self.items, self.items,
                                            {} if metadata is None else metadata)
        create.assert_called_once()
        return result

    def diagnostic(self):
        paths = list((self.folder / 'logs/diagnostics').glob('select_items-raw-*.json'))
        self.assertEqual(len(paths), 1)
        # Reporting reads top-level stage receipts; diagnostic evidence stays separate.
        self.assertEqual(list((self.folder / 'logs').glob('*.json')), [])
        return paths[0], load(paths[0])

    def test_38_exact_decisions_pass(self):
        self.assertEqual(set(decisions_valid(self.decisions, self.by)), set(self.by))

    def test_reordered_complete_decisions_pass(self):
        self.assertEqual(decisions_valid(list(reversed(self.decisions)), self.by),
                         decisions_valid(self.decisions, self.by))

    def test_mission29a_reports_two_missing_and_one_unexpected(self):
        records = copy.deepcopy(self.decisions[:-2])
        records.append(dict(item_id='feed:2898a53d04394efa', version_id='f' * 64,
                            decision='reject', reason='Out of scope', piece_ids=[]))
        message = self.assert_coverage_failure(records, 'expected_count=38 returned_count=37',
            self.items[-2]['item_id'], self.items[-1]['item_id'], 'feed:2898a53d04394efa')
        self.assertIn('duplicate_pairs=[]', message)
        self.assertEqual(message, self.assert_coverage_failure(records))

    def test_equal_count_ineligible_substitution_fails(self):
        records = copy.deepcopy(self.decisions)
        records[-1]['item_id'] = 'feed:ineligible'
        self.assert_coverage_failure(records, 'returned_count=38', 'feed:ineligible',
                                     self.items[-1]['item_id'])

    def test_duplicate_pair_fails(self):
        records = copy.deepcopy(self.decisions)
        records[-1] = copy.deepcopy(records[0])
        self.assert_coverage_failure(records, 'duplicate_pairs=[', self.items[-1]['item_id'])

    def test_conflicting_item_versions_fail(self):
        records = copy.deepcopy(self.decisions)
        records[-1]['item_id'] = records[0]['item_id']
        self.assert_coverage_failure(records, "conflicting_item_versions=[('feed:unit-00'",
                                     'unexpected=[', 'missing=[')

    def test_wrong_and_stale_versions_fail(self):
        for version in ['f' * 64, '0' * 64]:
            records = copy.deepcopy(self.decisions)
            records[-1]['version_id'] = version
            self.assert_coverage_failure(records, self.items[-1]['version_id'], version)

    def test_invalid_records_and_identifiers_reported_together(self):
        records = copy.deepcopy(self.decisions)
        records[0] = None
        records[1]['item_id'] = []
        records[2]['version_id'] = {'invalid': 'identifier'}
        records[3]['decision'] = []
        records[4]['version_id'] = ' '
        self.assert_coverage_failure(records, '0: Decision records must be objects',
            '1: Invalid decision identifiers', '2: Invalid decision identifiers',
            '3: Invalid editorial decision', '4: Invalid decision identifiers', 'missing=[')

    def test_request_has_only_ordered_pairs_and_full_metadata(self):
        request = self.request()
        self.assertEqual(request['inputs'], [dict(item_id=x['item_id'], version_id=x['version_id'])
                                            for x in self.items])
        self.assertEqual([e['item'] for e in request['evidence']], self.items)
        self.assertTrue(all(e['exact_source_text'] == 'Full synthetic source.\n'
                            for e in request['evidence']))

    def test_roster_size_is_dynamic(self):
        for count in [1, 5, 38]:
            request = self.request(self.items[:count], self.items[:count])
            self.assertEqual(len(request['inputs']), count)

    def test_evidence_must_match_exact_roster(self):
        wrong_version = copy.deepcopy(self.items)
        wrong_version[0]['version_id'] = 'f' * 64
        for evidence in [self.items[:-1], self.items + [self.items[0]], wrong_version]:
            with self.assertRaisesRegex(Invalid, 'Selection evidence roster mismatch'):
                self.request(items=evidence)
        with self.assertRaisesRegex(Invalid, 'Duplicate selection roster item'):
            self.request(inputs=self.items + [self.items[0]])
        with self.assertRaisesRegex(Invalid, 'roster requires'):
            self.request(inputs=[dict(item_id=[], version_id='v')])
        self.assertEqual(self.request(items=list(reversed(self.items)))['inputs'],
                         self.request()['inputs'])

    def test_human_context_cannot_expand_eligibility_or_change_records(self):
        excluded = dict(item_id='feed:historical-ineligible', version_id='f' * 64,
                        human_decision='ACCEPT')
        stale = dict(self.history[0], version_id='e' * 64)
        original_history = self.history + [excluded, stale]
        history_path = self.folder / 'config/human_decisions_v2.jsonl'
        history_path.write_bytes(lines(original_history))
        event = dict(event_id='original-event', payload_sha256='original-payload',
                     scope='Article 2', publication_authorized=False,
                     selections=[dict(item_id=self.items[0]['item_id'],
                                      version_id=self.items[0]['version_id'], source_selection='ACCEPT'),
                                 excluded, stale])
        event_path = self.folder / 'config/rss_source_selection.json'
        save_json(event_path, event)
        before = (history_path.read_bytes(), event_path.read_bytes())
        request = self.request()
        self.assertEqual(request['archived_human_selection'], self.history)
        projection = request['additional_human_source_selection']
        self.assertEqual(projection['context_type'], 'eligible_selection_projection')
        self.assertEqual(projection['original_event_id'], event['event_id'])
        self.assertEqual(projection['original_payload_sha256'], event['payload_sha256'])
        self.assertNotIn('payload_sha256', projection)
        self.assertEqual(projection['selections'], event['selections'][:1])
        self.assertEqual(before, (history_path.read_bytes(), event_path.read_bytes()))
        self.assertNotIn(excluded['item_id'], canonical(request).decode())

    def test_archived_constraints_remain_effective(self):
        accepted = self.select(self.decisions)
        self.assertTrue(all(x['human_review_status'] == 'confirmed' for x in accepted[:12]))
        self.assertTrue(all(x['human_review_status'] == 'pending' for x in accepted[12:]))
        changed = copy.deepcopy(self.decisions)
        changed[9].update(decision='accept', piece_ids=['02'])
        with self.assertRaisesRegex(Invalid, 'Model would change archived human decision'):
            self.select(changed)

    def test_new_versions_cannot_claim_archived_confirmation(self):
        self.items[0]['version_id'] = 'f' * 64
        self.decisions[0]['version_id'] = 'f' * 64
        (self.folder / 'eligible.jsonl').write_bytes(lines(self.items))
        result = self.select(self.decisions)
        self.assertEqual(result[0]['human_review_status'], 'pending')
        self.assertNotIn('source_approval_id', result[0])

    def test_human_metadata_and_publication_forbidden(self):
        for field in ['human_decision', 'human_review_status', 'approval_id', 'v2_approval_id']:
            records = copy.deepcopy(self.decisions)
            records[-1][field] = 'manufactured'
            with self.assertRaisesRegex(Invalid, 'manufacture human metadata'):
                self.select(records)
        records = copy.deepcopy(self.decisions)
        records[-1]['publication_authorized'] = True
        with self.assertRaisesRegex(Invalid, 'Decision permits publication'):
            decisions_valid(records, self.by)

    def test_invalid_piece_assignments_and_reasons_rejected(self):
        for changes in [dict(piece_ids=['04']), dict(piece_ids=['02', '02']),
                        dict(piece_ids='02'), dict(piece_ids=[]), dict(reason=' ')]:
            records = copy.deepcopy(self.decisions)
            records[0].update(changes)
            with self.assertRaises(Invalid):
                decisions_valid(records, self.by)
        records = copy.deepcopy(self.decisions)
        records[-1]['piece_ids'] = ['02']
        with self.assertRaisesRegex(Invalid, 'Only accepted items'):
            decisions_valid(records, self.by)

    def test_eligible_additional_source_constraint_is_enforced(self):
        key = self.items[-1]
        save_json(self.folder / 'config/rss_source_selection.json', dict(event_id='unit-event',
            selections=[dict(item_id=key['item_id'], version_id=key['version_id'])]))
        with self.assertRaisesRegex(Invalid, 'Existing human RSS selection'):
            self.select(self.decisions)
        records = copy.deepcopy(self.decisions)
        records[-1].update(decision='accept', piece_ids=['02'])
        with patch('pipeline_common.confirmed_new_sources', return_value=set()):
            accepted = self.select(records)
        self.assertEqual(accepted[-1]['source_selection_event_id'], 'unit-event')
        self.assertFalse(accepted[-1]['publication_authorized'])

    def test_invalid_coverage_returns_no_downstream_mapping(self):
        output = copy.deepcopy(self.decisions[:-1])
        with self.assertRaisesRegex(Invalid, 'One decision required'):
            self.select(output)
        self.assertTrue(all('human_review_status' not in x for x in output))
        self.assertFalse((self.folder / 'decisions.jsonl').exists())

    def test_malformed_json_preserved_before_parsing(self):
        raw = ' \n {"output": [ broken JSON\t\r\n'
        with self.assertRaisesRegex(RuntimeError, 'payload suppressed'):
            self.generate_raw(raw)
        path, diagnostic = self.diagnostic()
        self.assertEqual(diagnostic['raw_output_text'], raw)
        self.assertEqual(diagnostic['mode'], 'diagnostic_only')
        self.assertEqual(diagnostic['request_sha256'], digest(canonical(self.request())))
        self.assertEqual(diagnostic['raw_output_sha256'], digest(raw.encode('utf-8')))
        self.assertIn(diagnostic['request_sha256'], path.name)
        self.assertFalse((self.folder / 'model_responses/select_items.json').exists())

    def test_raw_whitespace_exact_and_diagnostic_not_replayable(self):
        raw = ' \r\n' + json.dumps({'output': self.decisions}, ensure_ascii=False) + '\t\n '
        metadata = {}
        self.assertEqual(self.generate_raw(raw, metadata), self.decisions)
        path, diagnostic = self.diagnostic()
        self.assertEqual(diagnostic['raw_output_text'], raw)
        self.assertEqual(metadata['raw_response_path'], path.relative_to(self.folder).as_posix())
        self.assertNotIn('output', diagnostic)
        self.assertEqual(load(self.folder / 'model_responses/select_items.json')['output'], self.decisions)

    def test_existing_diagnostics_never_overwritten(self):
        raw = 'invalid JSON'
        for attempt in range(2):
            with self.assertRaises(RuntimeError):
                self.generate_raw(raw)
            path, diagnostic = self.diagnostic()
            if attempt == 0:
                before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(diagnostic['raw_output_text'], raw)

    def test_stale_response_binding_rejected_without_provider(self):
        save_json(self.folder / 'model_responses/select_items.json', dict(
            request_sha256='stale', mode='model_response', output=self.decisions))
        with patch.object(model_adapter, 'request_for', return_value=self.request()), \
             patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS': '0'}):
            with self.assertRaisesRegex(Invalid, 'Saved response is stale'):
                model_adapter.generate(self.folder, 'select_items', self.items, self.items, {})

    def test_diagnostic_alone_cannot_enable_generation(self):
        raw = 'bad JSON'
        with self.assertRaises(RuntimeError):
            self.generate_raw(raw)
        with patch.object(model_adapter, 'request_for', return_value=self.request()), \
             patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS': '0'}):
            with self.assertRaisesRegex(RuntimeError, 'No API call made'):
                model_adapter.generate(self.folder, 'select_items', self.items, self.items, {})

    def test_valid_selection_makes_exactly_one_generation_and_provider_call(self):
        raw = json.dumps({'output': self.decisions})
        create, fake = self.provider(raw)
        with patch.object(selection, 'validate_items', return_value=self.by), \
             patch.object(selection, 'generate', wraps=model_adapter.generate) as generate, \
             patch.object(model_adapter, 'request_for', return_value=self.request()), \
             patch.dict('sys.modules', {'openai': fake}), \
             patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS': '1', 'PS04_MODEL': 'OFFLINE-MOCK'}):
            accepted = selection.select(self.folder, self.items, {})
        generate.assert_called_once()
        create.assert_called_once()
        self.assertEqual(len(accepted), len(self.items))
        self.assertTrue(all(x['publication_authorized'] is False for x in accepted))


if __name__ == '__main__':
    unittest.main(verbosity=2)
