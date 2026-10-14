"""Offline bound-selector regressions; execute in the isolated repository copy."""
import copy
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import editorial.create_briefs as briefing
import model_adapter
from model_evidence import (QUOTE_CONTRACT, evidence_view, passage_id,
                            resolve_brief_quotes, validate_catalogue, written_catalogue)
from pipeline_common import ROOT, Invalid, briefs_valid, canonical, digest, jsonl, load


class QuoteResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if Path(os.environ.get('PS04_TEST_MIRROR_ROOT', '')).resolve() != ROOT:
            raise RuntimeError('Quotation tests must run in the authorized isolated repository copy')
        run = ROOT / 'runs/editorial-live-91e0687de82c4ff081f75ebd3b498a0c'
        cls.items = {i['item_id']: i for i in jsonl(run / 'eligible.jsonl')}
        cls.decisions = {d['item_id']: d for d in jsonl(run / 'decisions.jsonl')}
        cls.briefs = jsonl(ROOT / 'editorial/human_review_m22/briefs_v1/consolidated_briefs_v1.jsonl')
        cls.request = dict(stage='create_briefs', written_quote_contract=QUOTE_CONTRACT,
            evidence_by_piece={p: sorted(k for k, d in cls.decisions.items()
                                        if d['decision'] == 'accept' and p in d['piece_ids'])
                               for p in ['01', '02', '03']},
            evidence=[evidence_view(i) for k, i in cls.items.items()
                      if cls.decisions[k]['decision'] == 'accept'])
        cls.selectors = copy.deepcopy(cls.briefs)
        for b in cls.selectors:
            for c in b['claims']:
                for ref in c['evidence']:
                    if cls.items[ref['item_id']]['kind'] == 'feed':
                        ref['locator'] = cls.selector(ref['item_id'], ref['locator']['quote'])

    @classmethod
    def selector(cls, key, quote):
        text, rows = written_catalogue(cls.items[key])
        start = text.index(quote)
        end = start + len(quote)
        first = next(r for r in rows if r[1] <= start < r[2])
        last = next(r for r in rows if r[1] < end <= r[2])
        return dict(type='text', start_passage_id=first[0], end_passage_id=last[0])

    def resolve(self, output=None, request=None, decisions=None, request_hash=None):
        request = self.request if request is None else request
        return resolve_brief_quotes(self.selectors if output is None else output,
            self.items, self.decisions if decisions is None else decisions, request,
            digest(canonical(request)) if request_hash is None else request_hash,
            'a' * 64, 'unit/raw-model-response.json')

    def first_ref(self, output):
        return output[0]['claims'][0]['evidence'][0]

    def test_single_line_mit_and_multiline_world_bank(self):
        result = self.resolve()
        self.assertEqual(briefs_valid(result, self.items, self.decisions), result)
        mit = result[1]['claims'][0]['evidence'][1]
        self.assertIn('contextual reasoning.', mit['locator']['quote'])
        self.assertEqual(mit['quotation_resolution']['original_selector']['start_passage_id'],
                         mit['quotation_resolution']['original_selector']['end_passage_id'])
        wb = result[2]['claims'][1]['evidence'][0]['locator']['quote']
        self.assertIn('Contracts should also require:\nData portability\n—', wb)
        self.assertIn('\nInteroperability\n—', wb)
        self.assertIn('\nAuditability\n—', wb)

    def test_raw_input_and_media_references_unchanged(self):
        before = canonical(self.selectors)
        result = self.resolve()
        self.assertEqual(canonical(self.selectors), before)
        for a, b in zip(self.selectors, result):
            for ca, cb in zip(a['claims'], b['claims']):
                for ra, rb in zip(ca['evidence'], cb['evidence']):
                    if self.items[ra['item_id']]['kind'] != 'feed':
                        self.assertEqual(ra, rb)

    def test_quote_provenance_and_determinism(self):
        a = self.resolve(); b = self.resolve()
        self.assertEqual(a, b)
        ref = self.first_ref(a); p = ref['quotation_resolution']
        text, _ = written_catalogue(self.items[ref['item_id']])
        self.assertEqual(text[p['start_char']:p['end_char']], ref['locator']['quote'])
        self.assertEqual(p['quote_utf8_sha256'], digest(ref['locator']['quote'].encode('utf-8')))
        self.assertEqual(p['version_id'], ref['version_id'])
        self.assertEqual(p['request_sha256'], digest(canonical(self.request)))
        self.assertEqual(p['raw_response_sha256'], 'a' * 64)

    def test_missing_unknown_bare_and_quote_or_offset_locators(self):
        for mutation in ['missing', 'unknown', 'bare', 'quote', 'offset']:
            with self.subTest(mutation=mutation):
                out = copy.deepcopy(self.selectors); loc = self.first_ref(out)['locator']
                if mutation == 'missing': del loc['end_passage_id']
                elif mutation == 'unknown': loc['start_passage_id'] = 'p9999@unknown'
                elif mutation == 'bare': loc['start_passage_id'] = 'p0001'
                elif mutation == 'quote': loc['quote'] = 'invented model quotation'
                else: loc.update(start_char=-1, end_char=999999)
                with self.assertRaises(Invalid): self.resolve(out)

    def test_reversed_range(self):
        out = copy.deepcopy(self.selectors)
        ref = out[2]['claims'][1]['evidence'][0]; loc = ref['locator']
        loc['start_passage_id'], loc['end_passage_id'] = loc['end_passage_id'], loc['start_passage_id']
        with self.assertRaises(Invalid): self.resolve(out)

    def test_wrong_item_version_and_cross_source_ids(self):
        for mutation in ['unknown_item', 'stale_version', 'cross_source']:
            with self.subTest(mutation=mutation):
                out = copy.deepcopy(self.selectors); ref = self.first_ref(out)
                if mutation == 'unknown_item': ref['item_id'] = 'feed:unknown'
                elif mutation == 'stale_version': ref['version_id'] = '0' * 64
                else:
                    other = out[1]['claims'][0]['evidence'][0]['locator']
                    ref['locator'] = copy.deepcopy(other)
                with self.assertRaises(Invalid): self.resolve(out)

    def test_binding_separates_sources_with_same_local_number(self):
        key = next(k for k, i in self.items.items() if i['kind'] == 'feed')
        item = self.items[key]; other = dict(item, item_id='feed:other')
        self.assertNotEqual(passage_id(item, 1, 0, 5), passage_id(other, 1, 0, 5))
        self.assertNotEqual(passage_id(item, 1, 0, 5), passage_id(dict(item, version_id='0'*64), 1, 0, 5))

    def test_catalogue_rejects_duplicate_ambiguous_and_invalid_boundaries(self):
        item = self.items[self.first_ref(self.selectors)['item_id']]
        text, good = written_catalogue(item)
        for value in [-1, len(text)+1, 0.5, True]:
            with self.subTest(boundary=value):
                rows = copy.deepcopy(good); rows[0][1] = value
                with self.assertRaises(Invalid): validate_catalogue(item, text, rows)
        rows = copy.deepcopy(good); rows[1][0] = rows[0][0]
        with self.assertRaises(Invalid): validate_catalogue(item, text, rows)
        rows = copy.deepcopy(good); rows[0][3] += 'changed'
        with self.assertRaises(Invalid): validate_catalogue(item, text, rows)

    def test_stale_request_and_tampered_request_catalogue(self):
        with self.assertRaises(Invalid): self.resolve(request_hash='0'*64)
        req = copy.deepcopy(self.request)
        entry = next(e for e in req['evidence'] if e['item']['kind'] == 'feed')
        entry['written_passages'][0][2] = 999999999
        with self.assertRaises(Invalid): self.resolve(request=req)

    def test_unaccepted_and_unassigned_sources(self):
        for mutation in ['reject', 'unassigned']:
            ds = copy.deepcopy(self.decisions); key = self.first_ref(self.selectors)['item_id']
            if mutation == 'reject': ds[key]['decision'] = 'reject'
            else: ds[key]['piece_ids'] = []
            with self.assertRaises(Invalid): self.resolve(decisions=ds)

    def test_unchanged_downstream_organization_and_media_validation(self):
        out = self.resolve(); out[1]['claims'] = [c for c in out[1]['claims'] if c['claim_id'] != '02-c5']
        with self.assertRaisesRegex(Invalid, 'three independent organizations'):
            briefs_valid(out, self.items, self.decisions)
        out = self.resolve(); out[1]['claims'][3]['evidence'][0]['locator']['segment_id'] = 'seg-unknown'
        with self.assertRaisesRegex(Invalid, 'Unknown media segment'):
            briefs_valid(out, self.items, self.decisions)

    def synthetic(self, raw, version=None):
        directory = tempfile.TemporaryDirectory(prefix='ps04-quote-fixture-')
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'source.txt'; path.write_bytes(raw)
        item = dict(item_id='feed:unit', version_id=version or digest(raw), kind='feed', text_path='unused')
        return item, path

    def test_unicode_offsets_and_strict_utf8(self):
        raw = 'Café — “ação”\n• São Tomé\n'.encode('utf-8'); item, path = self.synthetic(raw)
        with patch('model_evidence.root_file', return_value=path):
            text, rows = written_catalogue(item)
        self.assertEqual(text.encode('utf-8'), raw)
        self.assertEqual(rows[1][1], len('Café — “ação”\n'))
        self.assertNotEqual(rows[1][1], len('Café — “ação”\n'.encode('utf-8')))
        item, path = self.synthetic(b'bad\xff')
        with patch('model_evidence.root_file', return_value=path), self.assertRaises(UnicodeDecodeError):
            written_catalogue(item)

    def test_modified_bytes_and_incompatible_newlines(self):
        item, path = self.synthetic(b'changed', digest(b'original'))
        with patch('model_evidence.root_file', return_value=path), self.assertRaises(Invalid):
            written_catalogue(item)
        for raw in [b'first\r\nsecond\r\n', b'first\rsecond']:
            item, path = self.synthetic(raw)
            with patch('model_evidence.root_file', return_value=path), self.assertRaisesRegex(Invalid, 'CRLF/CR'):
                written_catalogue(item)

    def test_four_historical_failures_prevented_without_repairing_history(self):
        p = load(ROOT/'editorial/brief_corrections_v1/quote_correction_proposal_v1.json')
        response = ROOT/p['original_response_path']; before = response.read_bytes()
        out = copy.deepcopy(self.selectors)
        for change in p['corrections']:
            claim = next(c for b in out for c in b['claims'] if c['claim_id'] == change['claim_id'])
            ref = claim['evidence'][change['reference_index']-1]
            ref['locator'] = self.selector(ref['item_id'], change['proposed_locator']['quote'])
        result = self.resolve(out)
        briefs_valid(result, self.items, self.decisions)
        self.assertEqual(response.read_bytes(), before)

    def stage_case(self, mode, response_mode, output):
        directory = tempfile.TemporaryDirectory(prefix='ps04-brief-stage-', dir=ROOT/'runs'); self.addCleanup(directory.cleanup)
        folder = Path(directory.name)
        def save(name, value):
            p = folder/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(canonical(value)+b'\n')
        save('run.json', dict(mode=mode))
        (folder/'decisions.jsonl').write_bytes(b''.join(canonical(d)+b'\n' for d in self.decisions.values()))
        (folder/'eligible.jsonl').write_bytes(b''.join(canonical(i)+b'\n' for i in self.items.values()))
        h = digest(canonical(self.request)); raw = '  '+json.dumps({'output':output}, ensure_ascii=False)+'\n'
        save('model_requests/create_briefs-'+h+'.json', self.request)
        save('model_responses/create_briefs.json', dict(mode=response_mode, request_sha256=h, output=output, raw_output_text=raw))
        def generate(*args): args[-1]['request_sha256'] = h; return copy.deepcopy(output)
        return folder, generate

    def invoke_stage(self, mode, response_mode, output):
        folder, generate = self.stage_case(mode, response_mode, output)
        before = (folder/'model_responses/create_briefs.json').read_bytes()
        with patch.object(briefing, 'generate', generate), patch.object(briefing, 'validate_items', return_value=self.items), \
             patch.object(briefing, 'preserved_decisions', return_value=self.decisions), \
             patch.object(briefing, 'relative', return_value='unit/raw-response.json'):
            result = briefing.create(folder, list(self.decisions.values()), {})
        self.assertEqual((folder/'model_responses/create_briefs.json').read_bytes(), before)
        return result

    def test_live_stage_resolves_selectors_without_changing_raw_envelope(self):
        self.assertEqual(len(self.invoke_stage('live', 'model_response', self.selectors)), 3)

    def test_live_stage_has_no_quote_string_or_offline_mode_fallback(self):
        for response_mode in ['model_response', 'offline_replay', 'offline_contract_fixture']:
            with self.subTest(response_mode=response_mode), self.assertRaises(Invalid):
                self.invoke_stage('live', response_mode, self.briefs)

    def test_explicit_legacy_offline_fixture_compatibility_only(self):
        for mode, response_mode in [('editorial_offline_replay','offline_replay'), ('contract_offline_test','offline_contract_fixture')]:
            self.assertEqual(self.invoke_stage(mode, response_mode, self.briefs), self.briefs)

    def test_model_adapter_retains_unmodified_output_text(self):
        folder, _ = self.stage_case('live', 'model_response', self.selectors)
        # Separate output location to exercise a new response, not replay one.
        (folder/'model_responses/create_briefs.json').unlink()
        raw = ' \n'+json.dumps({'output':self.selectors}, ensure_ascii=False)+'\n '
        result = types.SimpleNamespace(output_text=raw, usage=None)
        fake = types.SimpleNamespace(OpenAI=lambda: types.SimpleNamespace(responses=types.SimpleNamespace(create=lambda **kwargs: result)))
        with patch.object(model_adapter, 'request_for', return_value=self.request), \
             patch.dict('sys.modules', {'openai':fake}), \
             patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS':'1','PS04_MODEL':'OFFLINE-MOCK-NO-REQUEST'}):
            model_adapter.generate(folder, 'create_briefs', [], [], {})
        self.assertEqual(load(folder/'model_responses/create_briefs.json')['raw_output_text'], raw)


if __name__ == '__main__':
    unittest.main(verbosity=2)
