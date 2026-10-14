"""Mission 9: normal orchestration with explicitly offline transports and data.

No fixture is a live run, no paid provider is enabled, and no human final-content
approval is written. Test artifacts stay inspectable in new directories.
"""
import ast
import copy
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from pipeline_common import ROOT, Invalid, canonical, digest, jsonl, load, policy, relative, save_json, validate_items, write_new
from workflows.editorial_run import initialize
from processing.evidence_contract import finalize, version_hash, verify_version, check_media
from collectors.contracts import collect, rss_records
from processing.contract_extract import extract_one
from review.check_content import assessment
from publishing.prepare_package import prepare

BASH=os.environ.get('PS04_TEST_BASH','C:/Program Files/Git/bin/bash.exe')


def create_case(store=None,collector_failure=False,missing_evidence=False):
    store=store or 'data/evidence/contract_v2/test-'+uuid.uuid4().hex+'/evidence.db'
    with patch.dict(os.environ,{'PS04_EVIDENCE_DB':store},clear=False):
        folder=initialize('contract_offline_test','2026-10-11')
    cache=jsonl(folder/'config/evidence_cache.jsonl')
    for kind in ['feed','youtube','podcast']:
        output=[dict(x) for x in cache if x['kind']==kind and not x['source_id'].endswith('-institutional')]
        for item in output:
            item['retrieved_at']=load(folder/'run.json')['started_at']
        save_json(folder/'fixtures'/('collector_'+kind+'.json'),dict(output=output,
            errors=['deliberate offline source failure'] if collector_failure and kind=='feed' else []))
    media=folder/'fixtures/media.offline';write_new(media,b'EXPLICIT OFFLINE MEDIA FIXTURE; NOT A RECORDING\n'*32)
    extractions={x['url']:dict(text_path=x['text_path'],segments_path=x.get('segments_path'),media_path=relative(media))
                 for x in cache if x['kind'] in {'youtube','feed'} and not x['source_id'].endswith('-institutional')}
    if missing_evidence:
        extractions[next(x['url'] for x in cache if x['kind']=='youtube')]['media_path']='runs/nonexistent-mission9-media'
    save_json(folder/'fixtures/extractions.json',extractions)
    decisions=[{k:x[k] for k in ['item_id','version_id','decision','reason','piece_ids','publication_authorized']}
               for x in jsonl(ROOT/'editorial/rss_integration_v3/expanded_source_decisions_v3.jsonl')]
    briefs=jsonl(ROOT/'editorial/rss_integration_v3/briefs/substantive_briefs_v3.jsonl')
    outputs={'select_items':decisions,'create_briefs':briefs}
    for stage,kind,stem in [('write_articles','articles','article'),('write_video_scripts','video_scripts','video_script')]:
        outputs[stage]=[]
        for brief in briefs:
            p=brief['piece_id']
            body=(ROOT/f'editorial/release_candidates_v4/public/{kind}/{p}_{stem}_v4.md').read_text(encoding='utf-8')
            markers='\n'.join('['+c['claim_id']+'] '+c['statement'] for c in brief['claims'])
            outputs[stage].append(dict(piece_id=p,markdown='EXPLICIT OFFLINE CONTRACT FIXTURE; not a new editorial release.\n\n'+body+'\n\n'+markers))
    save_json(folder/'fixtures/model_outputs.json',outputs)
    return folder


def invoke(folder,args=None):
    env=dict(os.environ,PS04_OFFLINE_CONTRACT_RUN=relative(folder),PS04_ALLOW_COLLECTION='0',
             PS04_ENABLE_MODEL_CALLS='0',PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([BASH,'--noprofile','--norc','run.sh',*(args or [])],cwd=ROOT,env=env,capture_output=True)


class ContractRepairsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=create_case();cls.result=invoke(cls.folder)
        if cls.result.returncode:
            raise AssertionError('Offline complete flow failed: '+cls.result.stderr.decode('utf-8',errors='replace'))
        cls.summary=json.loads(cls.result.stdout)

    def test_01_full_normal_entry_outputs_and_saved_summary(self):
        self.assertEqual(self.summary['status'],'awaiting_review')
        self.assertEqual(self.summary['mode'],'contract_offline_test')
        for name in ['candidates.jsonl','items.jsonl','changes.jsonl','corpus.jsonl','eligible.jsonl','exclusions.jsonl',
                     'decisions.jsonl','briefs.jsonl','articles.jsonl','video_scripts.jsonl','review.json','summary.json','source_selection_binding.json']:
            self.assertTrue((self.folder/name).is_file(),name)
        self.assertEqual(self.summary,load(self.folder/'summary.json'))
        self.assertEqual(self.summary['counts']['articles'],3);self.assertEqual(self.summary['counts']['video_scripts'],3)
        self.assertEqual(self.summary['counts']['discovered'],14);self.assertEqual(self.summary['cached_candidate_count'],5)

    def test_02_stage_order_unique_receipts_counts_and_offline_labels(self):
        receipts=[load(p) for p in (self.folder/'logs').glob('*.json')]
        stages={r['stage']:r for r in receipts}
        expected=['store_init','fetch_feeds','fetch_youtube','fetch_podcasts','extract_content','store_upsert','filter_items',
                  'collect_sources','select_items','create_briefs','write_articles','write_video_scripts','check_content','create_series','summarize_run']
        self.assertTrue(all(s in stages for s in expected))
        order=['extract_content','store_upsert','filter_items','select_items','create_briefs','write_articles','write_video_scripts','check_content']
        self.assertEqual(order,sorted(order,key=lambda s:stages[s]['started_at']))
        self.assertTrue(all('cost_usd' in r and 'errors' in r and 'finished_at' in r for r in receipts))
        self.assertTrue(all(r.get('api_calls_performed') is not True for r in receipts))
        self.assertIn('EXPLICIT OFFLINE',str(self.summary))

    def test_03_streams_snapshots_and_portable_store(self):
        for name,kind in [('feeds','feed'),('youtube','youtube'),('podcasts','podcast')]:
            records=jsonl(self.folder/f'candidates/{name}.jsonl');self.assertTrue(records)
            self.assertTrue(all(x['kind']==kind for x in records))
        policy(self.folder)
        for item in jsonl(self.folder/'eligible.jsonl'):
            self.assertFalse(Path(item['text_path']).is_absolute())
            self.assertTrue((ROOT/item['text_path']).is_file())
        self.assertTrue(load(self.folder/'run.json')['evidence_db'].startswith('data/evidence/contract_v2/'))

    def test_04_real_required_collectors_accept_run_directory_offline(self):
        env=dict(os.environ,PS04_ALLOW_COLLECTION='0',PS04_ENABLE_MODEL_CALLS='0',PYTHONDONTWRITEBYTECODE='1')
        for name in ['feeds','youtube','podcasts']:
            result=subprocess.run([BASH,'--noprofile','--norc',f'collectors/fetch_{name}.sh',relative(self.folder)],cwd=ROOT,env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(result.stdout)

    def test_05_source_approvals_retained_only_for_exact_versions(self):
        records=jsonl(self.folder/'decisions.jsonl')
        self.assertEqual(sum(x['decision']=='accept' for x in records),11)
        self.assertEqual(sum(x['decision']=='defer' for x in records),3)
        binding=load(self.folder/'source_selection_binding.json')
        self.assertEqual(len(binding['bound_items']),2)
        self.assertEqual(binding['event_id'],'da6884883a48d1c0')
        self.assertFalse(binding['final_content_human_approved'])
        from pipeline_common import confirmed_new_sources
        changed={x['item_id']:copy.deepcopy(x) for x in records}
        for x in binding['bound_items']:changed[x['item_id']]['version_id']='0'*64
        self.assertEqual(confirmed_new_sources(self.folder,changed),set())

    def test_06_changed_publication_and_segments_create_new_versions_retrieval_does_not(self):
        item=dict(item_id='unit:version',kind='youtube',source_id='unit',publisher_id='unit',title='Test',url='https://example.invalid/test',
                  published_at='2026-10-01T00:00:00Z',media_url='https://example.invalid/test',text_sha256='a'*64,segments_sha256='b'*64,source_media_sha256='c'*64)
        original=version_hash(item)
        item['retrieved_at']='2026-10-12T00:00:00Z';self.assertEqual(version_hash(item),original)
        for field in ['published_at','title','segments_sha256','source_media_sha256']:
            changed=dict(item);changed[field]='changed';self.assertNotEqual(version_hash(changed),original)

    def test_07_integrity_and_media_absence_reject_without_collection(self):
        items=jsonl(self.folder/'eligible.jsonl');broken=copy.deepcopy(items);broken[0]['version_id']='0'*64
        with self.assertRaises(Invalid):validate_items(broken,self.folder)
        media=copy.deepcopy(next(x for x in items if x['kind']=='youtube'))
        media['source_media_path']='runs/nonexistent-mission9-media'
        with self.assertRaises(Invalid):check_media(media)
        self.assertTrue(all(x.get('media_is_fixture') for x in items if x['kind']=='youtube'))

    def test_08_partial_failure_retains_valid_items_and_reports_failure(self):
        folder=create_case(collector_failure=True);result=invoke(folder)
        self.assertEqual(result.returncode,1,result.stderr)
        summary=json.loads(result.stdout);self.assertEqual(summary['status'],'failed')
        self.assertTrue(jsonl(folder/'items.jsonl'));self.assertIn('fetch_feeds',summary['failed_stages'])
        self.assertIn('select_items',summary['incomplete_stages']);self.assertIsNone(summary['counts']['articles'])
        self.assertTrue((folder/'summary.json').exists());self.assertFalse((folder/'decisions.jsonl').exists())

    def test_09_recovery_and_duplicate_reuse_on_same_prospective_store(self):
        store='data/evidence/contract_v2/test-'+uuid.uuid4().hex+'/evidence.db'
        first=create_case(store,collector_failure=True);self.assertEqual(invoke(first).returncode,1)
        recovered=create_case(store);result=invoke(recovered)
        self.assertEqual(result.returncode,0,result.stderr)
        summary=json.loads(result.stdout);self.assertEqual(summary['status'],'awaiting_review')
        self.assertEqual(summary['counts']['new'],0);self.assertEqual(summary['counts']['unchanged'],14)
        self.assertEqual(load(recovered/'run.json')['mode'],'contract_offline_test')

    def test_10_missing_media_explicitly_stops_complete_flow(self):
        folder=create_case(missing_evidence=True);result=invoke(folder)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['status'],'failed')
        self.assertFalse((folder/'articles.jsonl').exists())

    def test_11_review_final_human_gate_and_real_packager_refusal(self):
        review=assessment(self.folder);self.assertTrue(review['passed'],review['issues'])
        self.assertTrue(review['human_final_review_required']);self.assertFalse((self.folder/'approval.json').exists())
        with self.assertRaisesRegex(RuntimeError,'source approval is insufficient'):prepare(self.folder,None,{})
        result=invoke(self.folder,['--package',relative(self.folder)])
        self.assertEqual(result.returncode,1);self.assertFalse((self.folder/'package').exists())

    def test_12_snapshot_tamper_blocks_network_before_a_request(self):
        folder=create_case();(folder/'config/sources.json').write_bytes(b'[]')
        with patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            output,code=collect(folder,'feed')
        self.assertEqual(code,2);self.assertEqual(output,[])

    def test_13_future_live_mode_rejects_offline_fixture_and_never_calls_network(self):
        folder=create_case();run=load(folder/'run.json');run['mode']='live'
        def fake_load(path):return run if Path(path)==folder/'run.json' else load(path)
        with patch('collectors.contracts.load',side_effect=fake_load),patch('processing.evidence_contract.load',side_effect=fake_load),patch('urllib.request.urlopen',side_effect=AssertionError('network forbidden')):
            output,code=collect(folder,'feed')
        self.assertEqual(code,2);self.assertEqual(output,[])
        from workflows.editorial_run import main
        with patch.dict(os.environ,{'PS04_OFFLINE_CONTRACT_RUN':relative(folder),'PS04_ALLOW_COLLECTION':'0','PS04_ENABLE_MODEL_CALLS':'0'}):
            with patch('workflows.editorial_run.load',side_effect=fake_load),patch('sys.argv',['editorial_run','init-live']):
                with self.assertRaises(Invalid):main()
        self.assertEqual(load(folder/'run.json')['mode'],'contract_offline_test')

    def test_14_xml_timezone_dates_and_missing_timezone_failure(self):
        source=dict(source_id='mit',publisher_id='mit',kind='feed')
        raw=b'<rss><channel><item><title>Test</title><link>https://example.invalid/a</link><pubDate>Mon, 12 Oct 2026 12:00:00 -0400</pubDate></item></channel></rss>'
        from datetime import date
        record=rss_records(source,raw,date(2026,10,12))[0]
        self.assertEqual(record['published_at'],'2026-10-12T16:00:00Z')
        with self.assertRaises(Invalid):rss_records(source,raw.replace(b' -0400',b''),date(2026,10,12))

    def test_15_legacy_run_branches_unchanged_and_index_preserved(self):
        old=(ROOT/'docs/mission9_contract_repairs/before/run.sh').read_text(encoding='utf-8')
        current=(ROOT/'run.sh').read_text(encoding='utf-8')
        marker='if [[ "${1:-}" == "collect" ]]; then'
        self.assertEqual(old[old.index(marker):],current[current.index(marker):])
        b=load(ROOT/'docs/mission9_contract_repairs/preservation_baseline.json')
        self.assertEqual(digest(subprocess.check_output(['git','diff','--cached','--binary'],cwd=ROOT)),b['index_diff_sha256'])

    def test_16_code_syntax_without_bytecode(self):
        for p in [ROOT/'collectors/contracts.py',ROOT/'processing/contract_extract.py',ROOT/'processing/evidence_contract.py',
                  ROOT/'pipeline_common.py',ROOT/'data/store.py',ROOT/'reporting/summarize_run.py']:
            ast.parse(p.read_text(encoding='utf-8'))

    def test_17_filter_all_mandatory_exclusion_reasons(self):
        folder=create_case();base=jsonl(folder/'config/evidence_cache.jsonl')[0];records=[]
        for n,value in enumerate(['2026-10-11T00:00:00Z','2026-10-12T00:00:00Z','2026-09-11T00:00:00Z',None,'invalid']):
            item=dict(base,item_id='unit:filter'+str(n),published_at=value);records.append(item)
        result=subprocess.run([os.sys.executable,'-B','processing/filter_items.py',relative(folder)],cwd=ROOT,
                              input=b''.join(canonical(x)+b'\n' for x in records),capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(result.stdout.splitlines()),1)
        self.assertEqual({x['reason'] for x in jsonl(folder/'exclusions.jsonl')},
                         {'future_date','outside_window','unknown_date','invalid_date'})

    def test_18_prospective_version_text_integrity_and_metadata_tamper(self):
        folder=create_case();item=dict(item_id='feed:unit-version',kind='feed',source_id='unit',publisher_id='unit',title='Test',
            url='https://example.invalid/a',published_at='2026-10-01T00:00:00Z',retrieved_at='2026-10-12T00:00:00Z',media_url=None)
        text=b'Offline source-version unit fixture.\n';first=finalize(item,text,None,folder)
        self.assertEqual(first['version_scheme'],'evidence-v2');verify_version(first,text)
        second=finalize(dict(item,published_at='2026-10-02T00:00:00Z'),text,None,create_case())
        self.assertNotEqual(first['version_id'],second['version_id']);self.assertEqual(first['text_sha256'],second['text_sha256'])
        tampered=dict(first,title='Different title')
        with self.assertRaises(Invalid):verify_version(tampered,text)

    def test_19_changed_historical_version_requires_pending_new_authority(self):
        from pipeline_common import preserved_decisions
        records=copy.deepcopy(jsonl(self.folder/'decisions.jsonl'));items={x['item_id']:copy.deepcopy(x) for x in jsonl(self.folder/'eligible.jsonl')}
        chosen=next(x for x in records if x.get('source_approval_id'))
        chosen['version_id']='1'*64;items[chosen['item_id']]['version_id']='1'*64
        with self.assertRaises(Invalid):preserved_decisions(self.folder,records,items)
        chosen['human_review_status']='pending';chosen.pop('source_approval_id')
        preserved_decisions(self.folder,records,items)

    def test_20_mocked_provider_failure_records_attempt_and_unknown_cost(self):
        from model_adapter import generate
        import types
        folder=initialize('editorial_offline_replay','2026-10-11',jsonl(ROOT/'runs/editorial-prep/corpus_verified.jsonl'))
        class Client:
            def __init__(self):self.responses=self
            def create(self,**kwargs):raise RuntimeError('SIMULATED PROVIDER FAILURE; NO REQUEST MADE')
        fake=types.SimpleNamespace(OpenAI=Client);metadata={};items=jsonl(folder/'eligible.jsonl')
        with patch.dict('sys.modules',{'openai':fake}),patch.dict(os.environ,{'PS04_ENABLE_MODEL_CALLS':'1','PS04_MODEL':'offline-mocked-provider'}):
            with self.assertRaisesRegex(RuntimeError,'payload suppressed'):generate(folder,'select_items',items,items,metadata)
        self.assertTrue(metadata['provider_request_attempted']);self.assertIsNone(metadata['cost_usd'])

    def test_21_legacy_metadata_cannot_silently_inherit_source_approval(self):
        items=copy.deepcopy(jsonl(self.folder/'eligible.jsonl'))
        next(x for x in items if x['kind']=='feed')['title']='Changed claim context'
        with self.assertRaisesRegex(Invalid,'Legacy source metadata changed'):validate_items(items,self.folder)

    def test_22_prospective_store_cannot_target_historical_database(self):
        path=ROOT/'runs/live_evidence.db';before=digest(path.read_bytes())
        with patch.dict(os.environ,{'PS04_EVIDENCE_DB':'runs/live_evidence.db'}):
            with self.assertRaisesRegex(Invalid,'preserve historical databases'):initialize('contract_offline_test','2026-10-11')
        self.assertEqual(digest(path.read_bytes()),before)

    def test_23_selected_rss_missing_from_current_feed_remains_truthful_cached_evidence(self):
        folder=create_case();path=folder/'fixtures/collector_feed.json';fixture=load(path)
        selected={'feed:17f635e65de87807','feed:2898a53d04394efa'}
        fixture['output']=[x for x in fixture['output'] if x['item_id'] not in selected]
        path.write_bytes(canonical(fixture)+b'\n')
        result=invoke(folder);self.assertEqual(result.returncode,0,result.stderr)
        summary=json.loads(result.stdout);self.assertEqual(summary['status'],'awaiting_review')
        self.assertEqual(summary['cached_candidate_count'],7)
        reused={x['item_id']:x for x in jsonl(folder/'items.jsonl') if x['item_id'] in selected}
        self.assertEqual(len(reused),2)
        self.assertTrue(all(x['discovery_method']=='rss' and 'not a fresh page' in x['reuse_method'] for x in reused.values()))

    def test_24_malformed_extraction_writes_failure_receipt_and_exit_two(self):
        folder=create_case()
        result=subprocess.run([os.sys.executable,'-B','-m','processing.contract_extract',relative(folder)],
                              cwd=ROOT,input=b'not JSON\n',capture_output=True)
        self.assertEqual(result.returncode,2);self.assertFalse(result.stdout)
        self.assertEqual(load(next((folder/'logs').glob('extract_content-*.json')))['status'],'failure')

    def test_25_unauthorized_default_start_reports_failure_without_live_execution(self):
        env=dict(os.environ,PS04_ALLOW_COLLECTION='0',PS04_ENABLE_MODEL_CALLS='0',PYTHONDONTWRITEBYTECODE='1')
        env.pop('PS04_OFFLINE_CONTRACT_RUN',None)
        result=subprocess.run([BASH,'--noprofile','--norc','run.sh'],cwd=ROOT,env=env,capture_output=True)
        self.assertEqual(result.returncode,2)
        summary=json.loads(result.stdout);self.assertEqual(summary['failed_stages'],['initialize'])
        self.assertIsNone(summary['run_id']);self.assertFalse(summary['publication_authorized'])

    def test_26_actual_archived_rss_metadata_matches_podcasts_without_transcribing_other_episodes(self):
        folder=create_case()
        candidates=jsonl(ROOT/'runs/collect-20261011T164724Z-2629/podcast_candidates.jsonl')
        (folder/'fixtures/collector_podcast.json').write_bytes(canonical(dict(output=candidates,errors=[]))+b'\n')
        result=invoke(folder);self.assertEqual(result.returncode,0,result.stderr)
        summary=json.loads(result.stdout);self.assertEqual(summary['status'],'awaiting_review')
        self.assertGreater(summary['unprocessed_candidate_count'],0)
        self.assertTrue(all(not x['transcription_performed'] for x in jsonl(folder/'processing_exclusions.jsonl')))
        self.assertEqual(sum(x['kind']=='podcast' for x in jsonl(folder/'items.jsonl')),2)

    def test_27_undated_rss_is_not_given_an_invented_date(self):
        from datetime import date
        raw=b'<rss><channel><item><title>Undated</title><link>https://example.invalid/undated</link></item></channel></rss>'
        record=rss_records(dict(source_id='unit',publisher_id='unit',kind='feed'),raw,date(2026,10,12))[0]
        self.assertIsNone(record['published_at'])

    def test_28_podcast_reference_uses_episode_media_not_general_index(self):
        from content.render_common import source_notes
        brief=jsonl(self.folder/'briefs.jsonl')[2];items={x['item_id']:x for x in jsonl(self.folder/'eligible.jsonl')}
        podcast=next(x for x in items.values() if x['publisher_id']=='imf')
        notes=source_notes(brief,items)
        self.assertIn(']('+podcast['media_url']+')',notes)
        self.assertNotIn(']('+podcast['url']+')',notes)

class VerifiedYouTubeReuseTests(unittest.TestCase):
    """Small archive-contract fixtures and one unchanged historical SIGMA bundle."""
    @classmethod
    def setUpClass(cls):
        if Path(os.environ.get('PS04_TEST_MIRROR_ROOT','')).resolve()!=ROOT:
            raise RuntimeError('Media reuse tests require the authorized isolated repository copy')

    def setUp(self):
        run=tempfile.TemporaryDirectory(prefix='youtube-reuse-unit-',dir=ROOT/'runs')
        media=tempfile.TemporaryDirectory(prefix='youtube-reuse-unit-',dir=ROOT/'data/media/contract_v2')
        self.addCleanup(run.cleanup);self.addCleanup(media.cleanup)
        self.folder=Path(run.name);self.media=Path(media.name)/'recording.webm'
        self.text=self.folder/'assets/transcript.txt';self.text.parent.mkdir()
        self.segments=self.folder/'assets/segments.json'
        # Synthetic bytes test the existing hash/binding contract, not audio decoding.
        self.media.write_bytes(b'SYNTHETIC OFFLINE UNIT MEDIA; NEVER LIVE EVIDENCE')
        rows=[dict(segment_id='s1',start_seconds=0,end_seconds=1,text='First cue.'),
              dict(segment_id='s2',start_seconds=1,end_seconds=2,text='Second cue.')]
        self.text.write_bytes(b'First cue.\nSecond cue.');save_json(self.segments,rows)
        self.archive=dict(item_id='youtube:1FeLhg9HqfE',kind='youtube',source_id='sigma-civil-servants',
            publisher_id='sigma',title='Synthetic SIGMA unit source',url='https://www.youtube.com/watch?v=1FeLhg9HqfE',
            media_url='https://www.youtube.com/watch?v=1FeLhg9HqfE',published_at='2026-09-23T00:00:00Z',
            retrieved_at='2026-10-13T01:25:28.480364Z',text_path=relative(self.text),
            text_sha256=digest(self.text.read_bytes()),segments_path=relative(self.segments),
            segments_sha256=digest(self.segments.read_bytes()),source_media_path=relative(self.media),
            source_media_sha256=digest(self.media.read_bytes()),media_is_fixture=False,
            version_scheme='evidence-v2',discovery_method='youtube',discovery_provenance='Synthetic offline unit binding')
        self.archive['version_id']=version_hash(self.archive)
        self.candidate={k:self.archive[k] for k in ['item_id','kind','source_id','publisher_id','title','url','media_url','published_at']}
        self.candidate['retrieved_at']='2026-10-14T21:01:56.675634Z'
        save_json(self.folder/'run.json',dict(mode='live',contract_version=2,as_of_date='2026-10-14'))
        p=self.folder/'config/evidence_cache.jsonl';p.parent.mkdir();p.write_bytes(canonical(self.archive)+b'\n')

    def attempt(self,archive=None,candidate=None):
        archive=self.archive if archive is None else archive
        candidate=self.candidate if candidate is None else candidate
        with ExitStack() as stack:
            downloads=[stack.enter_context(patch(name,side_effect=AssertionError('External retrieval forbidden'))) for name in
                ['processing.extract_youtube.extract_youtube','processing.contract_extract.source_media',
                 'processing.contract_extract.subprocess.run','processing.contract_extract.urllib.request.urlopen']]
            try:return extract_one(self.folder,candidate,[archive],None)
            finally:
                for download in downloads:download.assert_not_called()

    def rejected(self,archive=None,candidate=None,message=None):
        with self.assertRaises(Invalid) as caught:self.attempt(archive,candidate)
        if message:self.assertIn(message,str(caught.exception))
        return str(caught.exception)

    def test_exact_verified_reuse_preserves_provenance_without_downloads(self):
        before=copy.deepcopy(self.archive)
        with patch.dict(os.environ,{'PS04_ALLOW_COLLECTION':'0','PS04_ENABLE_MODEL_CALLS':'0'}):
            result=self.attempt()
        for key,value in self.archive.items():self.assertEqual(result[key],value,key)
        self.assertIn('no caption or media download',result['reuse_method'])
        self.assertIn('reused_at_utc',result);self.assertNotEqual(result['reused_at_utc'],result['retrieved_at'])
        self.assertEqual(self.archive,before);self.assertEqual(list(validate_items([result],self.folder)),[result['item_id']])
        self.assertFalse((ROOT/'data/media/contract_v2'/self.folder.name).exists())

    def test_historical_sigma_bundle_and_all_4788_boundaries_unchanged(self):
        previous=ROOT/'runs/editorial-live-064ea894fd3d49a981b19dca77a0729b'
        archive=next(x for x in jsonl(previous/'items.jsonl') if x['item_id']=='youtube:1FeLhg9HqfE')
        candidate=next(x for x in jsonl(ROOT/'runs/editorial-live-d1a0697d39204523a726bac648b59491/candidates/youtube.jsonl')
                       if x['item_id']==archive['item_id'])
        (self.folder/'config/evidence_cache.jsonl').write_bytes((previous/'config/evidence_cache.jsonl').read_bytes())
        segments=jsonl(previous/'items.jsonl')  # All source records remain read-only.
        before=load(ROOT/archive['segments_path'])
        result=self.attempt(archive,candidate)
        self.assertEqual(result['source_media_path'],archive['source_media_path'])
        self.assertEqual(result['source_media_sha256'],'eb69c59f2468d18123fdeeb31d1246b1a29c0f903c4ac1304d7a493766c2bcf5')
        self.assertEqual((ROOT/result['source_media_path']).stat().st_size,91628767)
        self.assertEqual(result['version_id'],archive['version_id']);self.assertEqual(result['retrieved_at'],archive['retrieved_at'])
        self.assertEqual(len(before),4788);self.assertEqual(load(ROOT/result['segments_path']),before)
        self.assertEqual(jsonl(previous/'items.jsonl'),segments)

    def test_missing_media_rejected_without_fallback(self):
        archive=dict(self.archive,source_media_path=relative(self.media.parent/'absent.webm'))
        self.rejected(archive,message='Required original source media unavailable')

    def test_corrupt_media_hash_rejected_without_fallback(self):
        archive=dict(self.archive,source_media_sha256='0'*64);archive['version_id']=version_hash(archive)
        self.rejected(archive,message='Source media integrity failure')

    def test_source_and_metadata_mismatches_rejected(self):
        for key,value in [('source_id','wrong-source'),('publisher_id','wrong-publisher'),('title','Changed title'),
                          ('url','https://www.youtube.com/watch?v=anotherVideo'),('published_at','2026-09-24T00:00:00Z'),
                          ('media_url','https://www.youtube.com/watch?v=anotherVideo')]:
            with self.subTest(key=key):self.rejected(candidate=dict(self.candidate,**{key:value}),message='identity/metadata mismatch')

    def test_item_and_video_id_mismatches_rejected(self):
        self.rejected(candidate=dict(self.candidate,item_id='youtube:anotherVideo'),message='identity/metadata mismatch')
        archive=dict(self.archive,item_id='youtube:anotherVideo');archive['version_id']=version_hash(archive)
        self.rejected(archive,message='identity/metadata mismatch')
        candidate=dict(self.candidate,item_id='youtube:anotherVideo')
        self.rejected(archive,candidate,message='video ID mismatch')

    def test_related_archive_wrong_kind_is_not_treated_as_new(self):
        self.rejected(dict(self.archive,kind='feed'),message='identity/metadata mismatch')

    def test_wrong_or_stale_evidence_version_rejected(self):
        self.rejected(dict(self.archive,version_id='0'*64),message='Evidence version/text integrity failure')
        self.rejected(candidate=dict(self.candidate,version_id='0'*64),message='evidence version mismatch')

    def test_altered_transcript_and_recorded_text_hash_rejected(self):
        self.text.write_bytes(b'Altered transcript')
        self.rejected(message='Evidence version/text integrity failure')
        self.text.write_bytes(b'First cue.\nSecond cue.')
        archive=dict(self.archive,text_sha256='0'*64);archive['version_id']=version_hash(archive)
        self.rejected(archive,message='Evidence version/text integrity failure')

    def test_legacy_text_hash_binding_is_also_required(self):
        archive=dict(self.archive,version_scheme='legacy-text-sha256',version_id=digest(self.text.read_bytes()),text_sha256='0'*64)
        (self.folder/'config/evidence_cache.jsonl').write_bytes(canonical(archive)+b'\n')
        self.rejected(archive,message='text hash mismatch')

    def test_altered_segments_and_recorded_segment_hash_rejected(self):
        rows=load(self.segments);rows[0]['end_seconds']=0.5
        self.segments.write_bytes(canonical(rows))
        self.rejected(message='Segments integrity failure')
        archive=dict(self.archive,segments_sha256=digest(self.segments.read_bytes()));archive['version_id']=version_hash(archive)
        rows[0]['end_seconds']=-1;self.segments.write_bytes(canonical(rows))
        archive['segments_sha256']=digest(self.segments.read_bytes());archive['version_id']=version_hash(archive)
        self.rejected(archive,message='Invalid segment interval')

    def test_consistent_hashes_cannot_hide_text_segment_disagreement(self):
        rows=load(self.segments);rows[0]['text']='Different speech.';self.segments.write_bytes(canonical(rows))
        archive=dict(self.archive,segments_sha256=digest(self.segments.read_bytes()));archive['version_id']=version_hash(archive)
        self.rejected(archive,message='transcript/segments mismatch')

    def test_fixtures_rejected_even_in_an_offline_test_run(self):
        self.rejected(dict(self.archive,media_is_fixture=True),message='fixtures or unbound media forbidden')
        (self.folder/'run.json').write_bytes(canonical(dict(mode='contract_offline_test',contract_version=2,as_of_date='2026-10-14')))
        self.rejected(dict(self.archive,media_is_fixture=True),message='fixtures or unbound media forbidden')

    def test_unbound_filename_cache_and_missing_hashes_rejected(self):
        partial={k:self.archive[k] for k in ['item_id','kind','url','source_media_path']}
        self.rejected(partial,message='identity/metadata mismatch')
        for key in ['text_sha256','segments_sha256','source_media_sha256','version_id']:
            archive=copy.deepcopy(self.archive);archive.pop(key)
            with self.subTest(key=key):self.rejected(archive,message='evidence hashes missing')
        self.rejected(dict(self.archive,media_is_fixture=None),message='unbound media forbidden')

    def test_untrusted_paths_rejected_before_media_reads(self):
        for key in ['text_path','segments_path','source_media_path']:
            archive=dict(self.archive,**{key:str(ROOT.parent/'outside-evidence.bin')})
            with self.subTest(key=key):self.rejected(archive,message='escapes project evidence area')
        self.rejected(dict(self.archive,source_media_path='config/editorial_policy.md'),message='escapes project evidence area')

    def test_missing_transcript_or_segments_rejected(self):
        for key in ['text_path','segments_path']:
            archive=dict(self.archive,**{key:relative(self.folder/'assets/absent')})
            with self.subTest(key=key):self.rejected(archive,message='Missing required file')

    def test_unc_paths_rejected_without_filesystem_resolution(self):
        archive=dict(self.archive,source_media_path=chr(92)*2+'untrusted.invalid'+chr(92)+'share'+chr(92)+'recording.webm')
        with patch.object(Path,'resolve',side_effect=AssertionError('Untrusted path must not be resolved')):
            self.rejected(archive,message='escapes project evidence area')

    def test_linked_assets_rejected_before_following_them(self):
        with patch.object(Path,'is_symlink',return_value=True), \
             patch.object(Path,'resolve',side_effect=AssertionError('Link must not be followed')):
            self.rejected(message='linked asset forbidden')

    def test_new_video_retains_normal_caption_and_media_processing(self):
        candidate=dict(self.candidate,item_id='youtube:newVideo123',url='https://www.youtube.com/watch?v=newVideo123',
                       media_url='https://www.youtube.com/watch?v=newVideo123')
        extracted=dict(text_path=relative(self.text),segments_path=relative(self.segments))
        media={k:self.archive[k] for k in ['source_media_path','source_media_sha256','media_is_fixture']}
        with patch.dict(os.environ,{'PS04_ALLOW_COLLECTION':'1'}), \
             patch('processing.extract_youtube.extract_youtube',return_value=extracted) as captions, \
             patch('processing.contract_extract.source_media',return_value=media) as audio:
            result=extract_one(self.folder,candidate,[self.archive],None)
        captions.assert_called_once();audio.assert_called_once();self.assertEqual(result['item_id'],candidate['item_id'])
        self.assertNotIn('reuse_method',result);validate_items([result],self.folder)

    def test_no_archive_or_authorization_does_not_adopt_a_local_filename(self):
        # A file without a source record cannot become a verified archive.
        with patch.dict(os.environ,{'PS04_ALLOW_COLLECTION':'0'}), \
             patch('processing.extract_youtube.extract_youtube',side_effect=AssertionError('No download')) as captions:
            with self.assertRaisesRegex(Invalid,'Caption retrieval requires authorization'):
                extract_one(self.folder,self.candidate,[],None)
        captions.assert_not_called()

    def test_rss_and_podcast_paths_remain_unchanged(self):
        feed=dict(self.candidate,item_id='feed:unit',kind='feed',url='https://news.mit.edu/unit-test',media_url=None)
        result=extract_one(self.folder,feed,[],{feed['url']:dict(text_path=relative(self.text))})
        self.assertEqual(result['kind'],'feed');self.assertIsNone(result['segments_path']);self.assertNotIn('reuse_method',result)
        archive=next(x for x in jsonl(ROOT/'editorial/rss_integration_v3/corpus_expanded_v3.jsonl')
                     if x['kind']=='podcast' and x['publisher_id']=='imf')
        candidate=dict(archive,retrieved_at=self.candidate['retrieved_at'])
        result=extract_one(self.folder,candidate,[archive],None)
        self.assertEqual(result['retrieved_at'],archive['retrieved_at']);self.assertEqual(result['kind'],'podcast')
        self.assertEqual(result['fresh_rss_candidate'],candidate);check_media(result)

    def test_invalid_archive_is_reported_as_extraction_failure(self):
        import processing.contract_extract as extraction
        archive=dict(self.archive,source_media_path=relative(self.media.parent/'absent.webm'))
        with patch.object(extraction,'policy'),patch.object(extraction,'fixture',return_value=None), \
             patch.object(extraction,'cached_items',return_value=[archive]),patch.object(extraction,'receipt') as receipt, \
             patch.object(extraction,'source_media',side_effect=AssertionError('No fallback download')) as audio:
            items,code=extraction.extract(self.folder,[self.candidate])
        self.assertEqual(items,[]);self.assertEqual(code,1);audio.assert_not_called()
        errors=receipt.call_args.args[6]
        self.assertTrue(any('Required original source media unavailable' in e['error'] for e in errors))


if __name__=='__main__':unittest.main(verbosity=2)
