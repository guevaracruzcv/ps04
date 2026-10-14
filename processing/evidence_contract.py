"""Prospective evidence version/asset contract; approved legacy bytes stay intact."""
from pathlib import Path
from pipeline_common import ROOT, canonical, digest, load, relative, require, write_new

VERSION_FIELDS = ('item_id', 'kind', 'source_id', 'publisher_id', 'title', 'url',
                  'published_at', 'media_url', 'text_sha256', 'segments_sha256', 'source_media_sha256')


def version_hash(item):
    return digest(canonical({k: item.get(k) for k in VERSION_FIELDS}))


def verify_version(item, text):
    require(bool(text.strip()), 'Empty source text')
    require(item.get('version_scheme') in {None,'legacy-text-sha256','evidence-v2'}, 'Unknown evidence version scheme')
    if item.get('version_scheme') == 'evidence-v2':
        require(digest(text) == item.get('text_sha256') and version_hash(item) == item['version_id'], 'Evidence version/text integrity failure')
    else:
        require(digest(text) == item['version_id'], 'Text integrity failure: ' + item['item_id'])


def verify_legacy_metadata(item, folder):
    """Compatibility never permits changed metadata to inherit a text-only approval."""
    if item.get('version_scheme') == 'evidence-v2':
        return
    from pipeline_common import jsonl
    known = next((x for x in jsonl(folder/'config/evidence_cache.jsonl')
                  if x['item_id']==item['item_id'] and x['version_id']==item['version_id']),None)
    require(known is not None, 'Legacy version lacks an immutable source snapshot')
    require(all(item.get(k)==known.get(k) for k in VERSION_FIELDS[:8]), 'Legacy source metadata changed; a new evidence version is required')
    if known.get('segments_path'):
        require(digest((ROOT/item['segments_path']).read_bytes())==digest((ROOT/known['segments_path']).read_bytes()),
                'Legacy timed evidence changed; a new evidence version is required')


def finalize(item, text, segments, folder, legacy=None):
    """New content+metadata versions; unchanged approved legacy evidence retains IDs."""
    result = dict(item)
    result['text_sha256'] = digest(text)
    result['segments_sha256'] = digest(segments) if segments is not None else None
    unchanged = legacy is not None and legacy['version_id'] == digest(text)
    if unchanged:
        unchanged = all(item.get(k) == legacy.get(k) for k in VERSION_FIELDS[:8])
        unchanged = unchanged and (legacy.get('segments_path') is None if segments is None else
                                  digest((ROOT / legacy['segments_path']).read_bytes()) == digest(segments))
        if legacy.get('source_media_sha256'):
            unchanged = unchanged and legacy['source_media_sha256'] == item.get('source_media_sha256')
    if unchanged:
        result.update(version_id=legacy['version_id'], version_scheme='legacy-text-sha256',
                      legacy_approval_version_retained=True)
    else:
        result.update(version_scheme='evidence-v2')
        result['version_id'] = version_hash(result)
    base = ROOT / 'data/assets/contract_v2' / folder.name
    stem = digest(result['item_id'].encode())[:20] + '_' + result['version_id']
    text_path = base / 'text' / (stem + '.txt')
    write_new(text_path, text)
    result['text_path'] = relative(text_path)
    result['segments_path'] = None
    if segments is not None:
        path = base / 'segments' / (stem + '.json')
        write_new(path, segments)
        result['segments_path'] = relative(path)
    return result


def check_media(item):
    path = ROOT / item['source_media_path']
    require(path.is_file() and path.stat().st_size > 0, 'Required original source media unavailable')
    require(digest(path.read_bytes()) == item['source_media_sha256'], 'Source media integrity failure')


def fixture(folder, name):
    """An explicit offline test transport cannot be used by a live run."""
    run = load(folder / 'run.json')
    path = folder / 'fixtures' / name
    if run['mode'] == 'contract_offline_test':
        require(path.is_file(), 'Offline fixture missing: ' + name)
        return load(path)
    require(not path.exists(), 'Offline fixtures forbidden in live execution')
    return None
