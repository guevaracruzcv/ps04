"""Offline prompt fidelity and quote regressions against preserved Mission 12."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from model_adapter import request_for
from model_evidence import evidence_view
from pipeline_common import ROOT, Invalid, briefs_valid, canonical, digest, load, root_file
from processing.evidence_contract import version_hash


RUN = ROOT / 'runs/editorial-live-91e0687de82c4ff081f75ebd3b498a0c'
PROPOSAL = ROOT / 'editorial/brief_corrections_v1/quote_correction_proposal_v1.json'


class ModelEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = {stage: load(next((RUN / 'model_requests').glob(stage + '-*.json')))
                   for stage in ['select_items', 'create_briefs']}
        cls.new = {stage: request_for(RUN, stage, old['inputs'],
                                     [e['item'] for e in old['evidence']])
                   for stage, old in cls.old.items()}

    def test_selection_retains_all_34_item_versions_and_metadata(self):
        old = self.old['select_items']
        new = self.new['select_items']
        self.assertEqual(len(new['evidence']), 34)
        self.assertEqual(new['inputs'], [dict(item_id=x['item_id'], version_id=x['version_id'])
                                         for x in old['inputs']])
        self.assertEqual([e['item'] for e in new['evidence']],
                         [e['item'] for e in old['evidence']])
        self.assertFalse(new['publication_authorized'])

    def test_all_media_cues_reconstruct_exactly_with_ids_and_timestamps(self):
        originals = {e['item']['item_id']: e for e in self.old['select_items']['evidence']}
        for view in self.new['select_items']['evidence']:
            if 'media_rows' not in view:
                continue
            previous = ''
            restored = []
            for identifier, start, end, count, suffix in view['media_rows']:
                text = (previous[-count:] if count else '') + suffix
                restored.append(dict(segment_id=identifier, start_seconds=start,
                                     end_seconds=end, text=text))
                previous = text
            original = originals[view['item']['item_id']]
            self.assertEqual(restored, original['segments'])
            self.assertEqual('\n'.join(s['text'] for s in restored), original['text'])
            self.assertNotIn('text', view)
            self.assertNotIn('supplemental_text', view)

    def test_written_passages_preserve_every_character_and_offset(self):
        originals = {e['item']['item_id']: e for e in self.old['select_items']['evidence']}
        for view in self.new['select_items']['evidence']:
            if 'written_passages' not in view:
                continue
            text = originals[view['item']['item_id']]['text']
            self.assertEqual(''.join(row[3] for row in view['written_passages']), text)
            for identifier, start, end, passage in view['written_passages']:
                self.assertEqual(text[start:end], passage)
                self.assertTrue(identifier.startswith('p'))

    def test_brief_wire_input_contains_only_16_accepted_assigned_items(self):
        expected = [x for x in self.old['create_briefs']['inputs'] if x['decision'] == 'accept']
        new = self.new['create_briefs']
        self.assertEqual(new['inputs'], expected)
        self.assertEqual(len(new['evidence']), 16)
        self.assertEqual({e['item']['item_id'] for e in new['evidence']},
                         {d['item_id'] for d in expected})
        for piece in ['01', '02', '03']:
            self.assertEqual(new['evidence_by_piece'][piece],
                             sorted(d['item_id'] for d in expected if piece in d['piece_ids']))

    def test_four_corrections_are_exact_pending_and_retain_coverage_blocker(self):
        proposal = load(PROPOSAL)
        response_path = root_file(proposal['original_response_path'])
        self.assertEqual(digest(response_path.read_bytes()), proposal['original_response_sha256'])
        self.assertEqual(len(proposal['corrections']), 4)
        briefs = copy.deepcopy(load(response_path)['output'])
        items = {x['item_id']: x for x in self.old['select_items']['inputs']}
        decisions = {x['item_id']: x for x in self.old['create_briefs']['inputs']}
        with self.assertRaisesRegex(Invalid, 'Quote not found in exact source version'):
            briefs_valid(briefs, items, decisions)
        for change in proposal['corrections']:
            text = root_file(change['text_path']).read_text(encoding='utf-8')
            quote = change['proposed_locator']['quote']
            self.assertEqual(text[change['source_start_char']:change['source_end_char']], quote)
            self.assertNotIn(change['original_generated_quote'], text)
            self.assertEqual(digest(root_file(change['text_path']).read_bytes()), change['source_text_sha256'])
            self.assertEqual(change['human_review_status'], 'pending')
            claim = next(c for b in briefs for c in b['claims'] if c['claim_id'] == change['claim_id'])
            claim['evidence'][change['reference_index'] - 1]['locator'] = change['proposed_locator']
        with self.assertRaisesRegex(Invalid, 'three independent organizations'):
            briefs_valid(briefs, items, decisions)
        self.assertFalse(proposal['final_content_human_approved'])
        self.assertFalse(proposal['publication_authorized'])

    def test_smaller_packets_change_request_binding_without_api_calls(self):
        for stage in self.old:
            self.assertLess(len(canonical(self.new[stage])), len(canonical(self.old[stage])) * 0.5)
            self.assertNotEqual(digest(canonical(self.new[stage])),
                                load(RUN / 'model_responses' / (stage + '.json'))['request_sha256'])

    def test_missing_or_changed_accepted_version_rejected_before_generation(self):
        old = self.old['create_briefs']
        items = [e['item'] for e in old['evidence']]
        accepted = next(x for x in old['inputs'] if x['decision'] == 'accept')
        with self.assertRaisesRegex(Invalid, 'unavailable'):
            request_for(RUN, 'create_briefs', old['inputs'],
                        [x for x in items if x['item_id'] != accepted['item_id']])
        changed = copy.deepcopy(old['inputs'])
        next(x for x in changed if x['item_id'] == accepted['item_id'])['version_id'] = '0' * 64
        with self.assertRaisesRegex(Invalid, 'version mismatch'):
            request_for(RUN, 'create_briefs', changed, items)

    def test_corrupt_segment_hash_rejected(self):
        item = copy.deepcopy(next(e['item'] for e in self.old['select_items']['evidence']
                                  if e['item']['kind'] == 'youtube'))
        item.update(version_scheme='evidence-v2', segments_sha256='0' * 64)
        item['version_id'] = version_hash(item)
        with self.assertRaisesRegex(Invalid, 'segments integrity'):
            evidence_view(item)

    def test_unique_untimed_media_context_is_retained(self):
        item = copy.deepcopy(next(e['item'] for e in self.old['select_items']['evidence']
                                  if e['item']['kind'] == 'youtube'))
        original_resolver = root_file
        text = 'OFFLINE UNIQUE UNTIMED CONTEXT'
        path = SimpleNamespace(read_text=lambda **kwargs: text,
                               read_bytes=lambda: text.encode('utf-8'))
        item.update(text_path='unit:context', version_scheme='legacy-text-sha256',
                    version_id=digest(path.read_bytes()))
        with patch('model_evidence.root_file', side_effect=lambda value:
                   path if value == 'unit:context' else original_resolver(value)):
            view = evidence_view(item)
        self.assertEqual(view['supplemental_text'], text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
