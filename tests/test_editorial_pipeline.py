"""Offline contract tests. No human approval is created and no provider called."""
import ast
import hashlib
import json
import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from pipeline_common import (APPROVAL_ID, ROOT, Invalid, canonical, digest, jsonl, load,
                             relative, save_json, validate_items, write_new)
from workflows.editorial_run import initialize
from workflows.offline_replay import prepare as replay_inputs
from review.check_content import assessment
from publishing.prepare_package import approval_valid, package_payload, existing_package
from model_adapter import generate

BASH = os.environ.get('PS04_TEST_BASH', 'C:/Program Files/Git/bin/bash.exe')


def invoke(script, args=(), data=None):
    env = dict(os.environ, PS04_ENABLE_MODEL_CALLS='0', PS04_ALLOW_COLLECTION='0', PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([BASH, '--noprofile', '--norc', script, *args], cwd=ROOT,
                          input=data, capture_output=True, env=env)


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = invoke('run.sh', ['--editorial-replay', '2026-10-11'])
        if result.returncode != 1:
            raise AssertionError('Expected completed but blocked assessment: ' + result.stderr.decode('utf-8', errors='replace'))
        cls.summary = json.loads(result.stdout)
        cls.folder = ROOT / 'runs' / cls.summary['run_id']
        cls.stderr = result.stderr.decode('utf-8', errors='replace')
        cls.test_artifacts = ROOT / 'tests/artifacts' / uuid.uuid4().hex
        cls.test_artifacts.mkdir(parents=True)
        save_json(cls.test_artifacts / 'end_to_end_result.json', dict(run_dir=relative(cls.folder), exit_code=result.returncode,
                   summary=cls.summary, expected_blockers=True, human_approval_created=False))

    def new_run(self):
        return initialize('editorial_offline_replay', '2026-10-11', jsonl(ROOT / 'runs/editorial-prep/corpus_verified.jsonl'))

    def test_end_to_end_stage_order_and_real_outputs(self):
        stages = ['select_items', 'create_briefs', 'write_articles', 'write_video_scripts', 'check_content']
        receipts = [load(p) for p in (self.folder / 'logs').glob('*.json')]
        selected = sorted([r for r in receipts if r['stage'] in stages], key=lambda x: x['started_at'])
        self.assertEqual([x['stage'] for x in selected], stages)
        self.assertTrue(all(x['status'] == 'success' for x in selected))
        for name in ['decisions', 'briefs', 'articles', 'video_scripts']:
            self.assertTrue(jsonl(self.folder / (name + '.jsonl')))
        self.assertEqual(self.summary['counts']['articles'], 3)
        self.assertEqual(self.summary['counts']['video_scripts'], 3)

    def test_decisions_and_provenance_preserved(self):
        from collections import Counter
        decisions = jsonl(self.folder / 'decisions.jsonl')
        self.assertEqual(Counter(x['decision'] for x in decisions), {'accept': 9, 'defer': 3})
        self.assertTrue(all(x['source_approval_id'] == APPROVAL_ID and not x['publication_authorized'] for x in decisions))
        counts = Counter(x['discovery_method'] for x in jsonl(self.folder / 'eligible.jsonl'))
        self.assertEqual(counts, {'rss': 3, 'direct_webpage': 5, 'podcast_rss': 2, 'youtube': 2})
        self.assertEqual(self.summary['corpus_scope'], 'curated_12')

    def test_review_reports_honest_blockers(self):
        review = load(self.folder / 'review.json')
        self.assertFalse(review['passed'])
        text = ' '.join(x['message'] for x in review['issues'])
        self.assertIn('RSS', text)
        self.assertIn('scaffold', text)
        self.assertIn('Imported draft', text)
        self.assertEqual(self.summary['status'], 'failed')
        self.assertIsNone(self.summary['counts']['discovered'])
        self.assertIsNone(self.summary['counts']['new'])
        self.assertFalse((self.folder / 'approval.json').exists())

    def test_packaging_refuses_no_human_approval(self):
        result = invoke('publishing/prepare_package.sh', [relative(self.folder)])
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.folder / 'package').exists())
        self.assertFalse(result.stdout)

    def test_package_command_preserves_drafts_and_snapshot(self):
        files = list((self.folder / 'articles').glob('*')) + list((self.folder / 'config').glob('*'))
        before = {str(f): digest(f.read_bytes()) for f in files}
        result = invoke('run.sh', ['--package', relative(self.folder)])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, {str(f): digest(f.read_bytes()) for f in files})
        self.assertFalse((self.folder / 'package').exists())

    def test_package_payload_without_fabricating_approval(self):
        assets, manifest = package_payload(self.folder, assessment(self.folder))
        self.assertEqual(len(manifest['assets']), 9)
        self.assertFalse(manifest['publication_authorized'])
        self.assertTrue(all(digest(assets[x['path']]) == x['sha256'] for x in manifest['assets']))
        # Inspect the pure payload; do not materialize an ungated production package.
        self.assertIn('source_notes/01.md', assets)
        self.assertTrue(any(name.startswith('evidence/') for name in assets))

    def test_source_approval_cannot_approve_final_content(self):
        approval = load(ROOT / 'runs/editorial-prep/human_approval_v2.json')
        with self.assertRaises(RuntimeError):
            approval_valid(approval, {'passed': True, 'review_id': 'a-new-final-content-fingerprint'})
        with self.assertRaises(RuntimeError):
            approval_valid({}, {'passed': True, 'review_id': 'a-new-final-content-fingerprint'})
        with self.assertRaises(RuntimeError):
            approval_valid({}, {'passed': False, 'review_id': 'a-new-final-content-fingerprint'})

    def test_package_reuse_preserves_links_and_detects_asset_tamper(self):
        # Unit fixture only: no production package, approval or published URL.
        directory = self.test_artifacts / 'package-verifier-fixture'
        assets = {'article.md': b'TEST FIXTURE ONLY; NOT A PUBLICATION\n'}
        manifest = {'unit_fixture_only': True, 'publication_authorized': False}
        write_new(directory / 'article.md', assets['article.md'])
        save_json(directory / 'manifest.json', manifest)
        links = [dict(piece_id=x, substack_url=None, youtube_url=None, notes='TEST ONLY; preserve formatting') for x in ['01', '02', '03']]
        save_json(directory / 'publication_links.json', links)
        before = (directory / 'publication_links.json').read_bytes()
        self.assertEqual(existing_package(directory, assets, manifest), manifest)
        self.assertEqual(before, (directory / 'publication_links.json').read_bytes())
        (directory / 'article.md').write_bytes(b'TAMPERED UNIT FIXTURE')
        with self.assertRaisesRegex(Invalid, 'integrity'):
            existing_package(directory, assets, manifest)

    def test_snapshot_change_is_blocked(self):
        from pipeline_common import policy
        folder = self.new_run()
        (folder / 'prompts/create_briefs.md').write_bytes(b'Changed negative-test prompt only')
        with self.assertRaisesRegex(Invalid, 'snapshot changed'):
            policy(folder)

    def test_feed_label_does_not_establish_rss_discovery(self):
        from workflows.editorial_run import discovery_annotations
        item = dict(jsonl(self.folder / 'eligible.jsonl')[0])
        item.update(item_id='feed:unit-test-undiscovered', source_id='mit-ai-news', publisher_id='mit', kind='feed', url='https://example.invalid/uncollected')
        self.assertEqual(discovery_annotations([item])[0]['discovery_method'], 'unknown')

    def test_downstream_cannot_promote_archived_defer(self):
        from pipeline_common import preserved_decisions
        folder = self.new_run()
        items = validate_items(jsonl(folder / 'eligible.jsonl'), folder)
        decisions = jsonl(self.folder / 'decisions.jsonl')
        next(x for x in decisions if x['decision'] == 'defer').update(decision='accept', piece_ids=['01'])
        with self.assertRaisesRegex(Invalid, 'Archived human decision'):
            preserved_decisions(folder, decisions, items)

    def test_review_ties_approval_to_current_inputs(self):
        # Actual source approval deliberately cannot authorize any assessed draft.
        current = assessment(self.folder)
        self.assertNotEqual(current['review_id'], APPROVAL_ID)
        self.assertFalse(current['publication_authorized'])
        self.assertTrue(current['human_final_review_required'])

    def test_content_rejects_wrong_claim_markers(self):
        from pipeline_common import manifest_valid
        records = jsonl(self.folder / 'articles.jsonl')
        records[0]['claim_ids'] = ['01-not-a-real-claim']
        with self.assertRaisesRegex(Invalid, 'claim IDs differ'):
            manifest_valid(records, jsonl(self.folder / 'briefs.jsonl'), self.folder, 'articles')

    def test_input_malformed_and_empty_fail(self):
        folder = self.new_run()
        for stream in [b'not-json\n', b'[]\n', b'']:
            result = invoke('editorial/select_items.sh', [relative(folder)], stream)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(result.stdout)

    def test_missing_evidence_fails_explicitly(self):
        folder = self.new_run()
        items = jsonl(folder / 'eligible.jsonl')
        items[0]['text_path'] = 'tests/required-evidence-not-present.txt'
        with self.assertRaisesRegex(Invalid, 'Missing required file'):
            validate_items(items, folder)

    def test_hash_tamper_detected(self):
        folder = self.new_run()
        items = jsonl(folder / 'eligible.jsonl')
        items[0]['version_id'] = '0' * 64
        with self.assertRaisesRegex(Invalid, 'integrity'):
            validate_items(items, folder)

    def test_stale_model_response_and_no_model_call(self):
        folder = self.new_run()
        items = jsonl(folder / 'eligible.jsonl')
        save_json(folder / 'model_responses/select_items.json', dict(request_sha256='wrong', mode='offline_replay', output=[]))
        result = invoke('editorial/select_items.sh', [relative(folder)], b''.join(canonical(x) + b'\n' for x in items))
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'stale', result.stderr)
        empty = self.new_run()
        with patch.dict(os.environ, {'PS04_ENABLE_MODEL_CALLS': '0'}):
            with self.assertRaisesRegex(RuntimeError, 'No API call made'):
                generate(empty, 'select_items', items, items, {})

    def test_archived_defer_cannot_be_promoted(self):
        folder = self.new_run()
        replay_inputs(folder)
        path = folder / 'model_responses/select_items.json'
        response = load(path)
        deferred = next(x for x in response['output'] if x['decision'] == 'defer')
        deferred.update(decision='accept', piece_ids=['01'])
        # Mutate only this fresh negative-test response, never archived decisions.
        path.write_bytes(canonical(response))
        items = jsonl(folder / 'eligible.jsonl')
        result = invoke('editorial/select_items.sh', [relative(folder)], b''.join(canonical(x) + b'\n' for x in items))
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'archived human decision', result.stderr)

    def test_output_validation_exact_locators_and_source_counts(self):
        from pipeline_common import briefs_valid, decisions_valid
        folder = self.new_run()
        items = validate_items(jsonl(folder / 'eligible.jsonl'), folder)
        decisions = decisions_valid(jsonl(self.folder / 'decisions.jsonl'), items)
        briefs = jsonl(self.folder / 'briefs.jsonl')
        self.assertEqual(len(briefs_valid(briefs, items, decisions)), 3)
        briefs[0]['claims'][0]['evidence'][0]['locator']['quote'] = 'THIS TEXT DOES NOT APPEAR IN THE ARCHIVED SOURCE'
        with self.assertRaisesRegex(Invalid, 'Quote not found'):
            briefs_valid(briefs, items, decisions)
        with self.assertRaisesRegex(Invalid, 'three briefs'):
            briefs_valid(briefs[:1], items, decisions)

    def test_missing_stage_order_dependency(self):
        folder = self.new_run()
        result = invoke('editorial/create_briefs.sh', [relative(folder)], b'{}\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn(b'decisions.jsonl', result.stderr)
        self.assertFalse(result.stdout)

    def test_review_fingerprint_changes_for_draft_or_evidence(self):
        folder = self.new_run()
        first = assessment(folder)['review_id']
        write_new(folder / 'articles/01.md', b'Changed test draft; not a real editorial deliverable\n')
        second = assessment(folder)['review_id']
        self.assertNotEqual(first, second)
        # Verify evidence hashes themselves are included in the completed fingerprint.
        hashes = assessment(self.folder)['assessed_sha256']
        self.assertTrue(any(name.startswith('evidence:') for name in hashes))

    def test_historical_runs_are_read_only(self):
        result = invoke('workflows/create_series.sh', ['runs/collect-20261011T163942Z-2489'])
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'Historical/unmanaged', result.stderr)

    def test_repeat_series_refuses_overwrite(self):
        before = digest((self.folder / 'decisions.jsonl').read_bytes())
        result = invoke('workflows/create_series.sh', [relative(self.folder)])
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, digest((self.folder / 'decisions.jsonl').read_bytes()))

    def test_default_live_is_guarded(self):
        result = invoke('run.sh')
        self.assertEqual(result.returncode, 2)
        self.assertIn(b'no network request made', result.stderr)

    def test_syntax_and_legacy_behavior_preserved(self):
        for directory in ['editorial', 'content', 'review', 'publishing', 'reporting', 'workflows']:
            for path in (ROOT / directory).glob('*.py'):
                ast.parse(path.read_bytes(), filename=str(path))
        for path in ROOT.rglob('*.sh'):
            if 'runs' in path.relative_to(ROOT).parts:
                continue
            result = subprocess.run([BASH, '--noprofile', '--norc', '-n', str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, str(path))
        original = subprocess.check_output(['git', 'show', ':run.sh'], cwd=ROOT).decode('utf-8')
        current = (ROOT / 'run.sh').read_text(encoding='utf-8')
        marker = 'if [[ "${1:-}" == "collect" ]]; then'
        self.assertEqual(original[original.index(marker):], current[current.index(marker):])

    def test_z_preservation(self):
        baseline = load(ROOT / 'tests/mission2_preservation_baseline.json')
        # Mission 9 explicitly authorizes contract repairs to these implementation
        # files. Historical evidence/policy/index still use the original baseline.
        # The Mission 9 audit separately checks every pre-existing file against
        # its current baseline and the exact authorized code-change allowlist.
        authorized_repairs = {'collectors/fetch_feeds.sh','collectors/fetch_youtube.sh','collectors/fetch_podcasts.sh',
                              'workflows/collect_sources.sh','processing/extract_content.sh','processing/extract_content.py',
                              'processing/extract_youtube.py','processing/filter_items.py','data/store.py'}
        for name, expected in baseline.items():
            if name in authorized_repairs:
                continue
            if name == 'index_diff':
                actual = digest(subprocess.check_output(['git', 'diff', '--cached', '--binary'], cwd=ROOT))
            else:
                actual = digest((ROOT / name).read_bytes())
            self.assertEqual(actual, expected, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
