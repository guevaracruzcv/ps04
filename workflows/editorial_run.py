"""Initialize isolated editorial runs and snapshot inputs; never edits archives."""
import os
import sys
import uuid
from pathlib import Path
from datetime import date
from pipeline_common import (APPROVAL_ID, MANAGED, POLICY_HASH, ROOT, canonical, digest,
                             jsonl, load, nonempty, policy, relative, require, run_folder,
                             save_json, utc, validate_items, write_new)


def initialize(mode, as_of, corpus=None):
    date.fromisoformat(as_of)
    active = load(ROOT / 'config/active_editorial_policy.json')
    require(active['approval_id'] == APPROVAL_ID and digest((ROOT / 'config/editorial_policy.md').read_bytes()) == POLICY_HASH, 'Active approved policy invalid')
    project = load(ROOT / 'config/project.json')
    for key in ['publication_name', 'topic', 'audience', 'central_question']:
        nonempty(project.get(key), key)
    folder = ROOT / 'runs' / ('editorial-' + mode + '-' + uuid.uuid4().hex)
    folder.mkdir(parents=True, exist_ok=False)
    run = dict(run_id=folder.name, managed_by=MANAGED, started_at=utc(), as_of_date=as_of, mode=mode,
               previous_run_id=None, publication_authorized=False, api_calls_performed=False,
               corpus_scope='curated_12' if mode == 'editorial_offline_replay' else 'live_collection')
    snapshot = {
        'config/project.json': ROOT / 'config/project.json',
        'config/sources.json': ROOT / 'config/active_sources.json',
        'config/rss_sources.json': ROOT / 'config/sources.json',
        'config/podcast_sources.json': ROOT / 'config/podcast_sources.json',
        'config/editorial_policy.md': ROOT / 'config/editorial_policy.md',
        'config/active_editorial_policy.json': ROOT / 'config/active_editorial_policy.json',
        'config/source_approval.json': ROOT / active['approval_event'],
        'config/human_decisions_v2.jsonl': ROOT / 'runs/editorial-prep/human_decisions_v2.jsonl',
    }
    for name in ['select_items', 'create_briefs', 'write_articles', 'write_video_scripts']:
        snapshot['prompts/' + name + '.md'] = ROOT / 'prompts' / (name + '.md')
    run['snapshot_sha256'] = {}
    for name, source in snapshot.items():
        data = source.read_bytes()
        require(bool(data.strip()), 'Empty required snapshot: ' + name)
        write_new(folder / name, data)
        run['snapshot_sha256'][name] = digest(data)
    if mode in {'live', 'contract_offline_test'}:
        run.update(contract_version=2, corpus_scope='fresh_collection_and_verified_reuse')
        if mode=='live':run['api_calls_performed']=None  # Final receipts/summary record actual attempts.
        previous = [load(p) for p in sorted((ROOT/'runs').glob('editorial-*/run.json'))
                    if load(p).get('contract_version') == 2 and load(p).get('mode') == mode]
        run['previous_run_id'] = previous[-1]['run_id'] if previous else None
        db = (ROOT / os.environ.get('PS04_EVIDENCE_DB', 'data/evidence/contract_v2/evidence.db')).resolve()
        require(db.is_relative_to(ROOT/'data/evidence/contract_v2'), 'Prospective store must preserve historical databases')
        run['evidence_db'] = relative(db)
        for name, source in {
            'config/evidence_cache.jsonl': ROOT/'editorial/rss_integration_v3/corpus_expanded_v3.jsonl',
            'config/rss_source_selection.json': ROOT/'editorial/rss_integration_v3/human_source_selection_event.json',
        }.items():
            data=source.read_bytes();write_new(folder/name,data);run['snapshot_sha256'][name]=digest(data)
    save_json(folder / 'run.json', run)
    policy(folder)
    if corpus is not None:
        normalized = discovery_annotations(corpus)
        validate_items(normalized, folder)
        require(len(normalized) == 12, 'Offline curated corpus must have 12 items')
        write_new(folder / 'eligible.jsonl', b''.join(canonical(x) + b'\n' for x in normalized))
        # Do not fabricate collection/change/exclusion records for an editorial replay.
    return folder


def discovery_annotations(items, current_folder=None):
    # Labels alone do not prove RSS discovery: retain a matching candidate path.
    candidates = {}
    folders = sorted((ROOT / 'runs').glob('collect-*'))
    if current_folder is not None:
        folders.append(current_folder)
    for folder in folders:
        path = folder / 'candidates.jsonl'
        if path.is_file():
            for record in jsonl(path):
                if record.get('kind') == 'feed' and record.get('source_id') == 'mit-ai-news':
                    candidates[(record['item_id'], record['url'])] = relative(path)
    normalized = []
    for item in items:
        value = dict(item)
        if item['kind'] == 'youtube':
            method, basis = 'youtube', 'native YouTube URL and archived captions'
        elif item['kind'] == 'podcast':
            method, basis = 'podcast_rss', 'archived RSS enclosure matching evidence'
        elif item['source_id'] == 'mit-ai-news' and item['publisher_id'] == 'mit' and (item['item_id'], item['url']) in candidates:
            method, basis = 'rss', 'matching MIT RSS candidate in ' + candidates[(item['item_id'], item['url'])]
        elif item['source_id'].endswith('-institutional'):
            method, basis = 'direct_webpage', 'institutional extraction directly from publisher URL; no RSS claim'
        else:
            method, basis = 'unknown', 'discovery evidence needs inspection'
        value.update(discovery_method=method, discovery_provenance=basis)
        normalized.append(value)
    return normalized


def main():
    require(len(sys.argv) >= 2, 'Missing initialization action')
    if sys.argv[1] == 'init-offline':
        require(len(sys.argv) == 3, 'Usage: init-offline YYYY-MM-DD')
        folder = initialize('editorial_offline_replay', sys.argv[2], jsonl(ROOT / 'runs/editorial-prep/corpus_verified.jsonl'))
        print(relative(folder))
    elif sys.argv[1] == 'init-live':
        require(len(sys.argv) == 2, 'Unexpected live arguments')
        if os.environ.get('PS04_OFFLINE_CONTRACT_RUN'):
            folder=run_folder(os.environ['PS04_OFFLINE_CONTRACT_RUN'])
            require(load(folder/'run.json')['mode']=='contract_offline_test' and
                    os.environ.get('PS04_ALLOW_COLLECTION')=='0' and os.environ.get('PS04_ENABLE_MODEL_CALLS')=='0',
                    'Offline test entry cannot claim or enable live execution')
            print(relative(folder))
            return
        require(os.environ.get('PS04_ALLOW_COLLECTION') == '1', 'New collection requires explicit PS04_ALLOW_COLLECTION=1; no network request made')
        require(os.environ.get('PS04_ENABLE_MODEL_CALLS') == '1' and os.environ.get('PS04_MODEL', '').strip(), 'Live default workflow needs an explicitly enabled model before collection')
        active_feeds = [x for x in load(ROOT / 'config/active_sources.json') if x['kind'] == 'feed']
        require(load(ROOT / 'config/sources.json') == active_feeds, 'RSS collector config differs from active feed snapshot')
        folder = initialize('live', utc()[:10])
        write_new(folder / 'sources.json', (folder / 'config/sources.json').read_bytes())
        print(relative(folder))
    elif sys.argv[1] == 'annotate':
        folder = run_folder(sys.argv[2])
        require(not (folder / 'collection_eligible.jsonl').exists(), 'Collection already annotated')
        original = (folder / 'eligible.jsonl').read_bytes()
        items = discovery_annotations(jsonl(folder / 'eligible.jsonl'), folder)
        validate_items(items, folder)
        write_new(folder / 'collection_eligible.jsonl', original)
        (folder / 'eligible.jsonl').write_bytes(b''.join(canonical(x) + b'\n' for x in items))
    else:
        require(False, 'Unknown initialization action')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError) as exc:
        print('Editorial initialization: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
