"""Shared contracts, evidence validation and receipts; no workflow dispatch."""
import hashlib
import json
import math
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
POLICY_HASH = '92f79fe975c33b302d069b52b639b3e6c344fb8a4b08cb41867ee9c0291f8126'
APPROVAL_ID = 'a589cd099dee6f96'
MANAGED = 'ps04-editorial-v1'
PIECES = {'01', '02', '03'}


class Invalid(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise Invalid(message)


def utc():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode('utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'), parse_constant=lambda x: (_ for _ in ()).throw(Invalid('Nonfinite JSON number')))


def jsonl(path):
    return parse_lines(Path(path).read_text(encoding='utf-8'))


def parse_lines(text):
    result = []
    for number, line in enumerate(text.splitlines(), 1):
        if line.strip():
            try:
                value = json.loads(line)
                require(isinstance(value, dict), f'JSONL line {number} must be an object')
                result.append(value)
            except json.JSONDecodeError:
                raise Invalid(f'Malformed JSONL at line {number}') from None
    return result


def write_new(path, data):
    path = Path(path)
    require(path.resolve().is_relative_to(ROOT), 'Output escapes repository')
    require(not path.is_symlink(), 'Refusing symlink output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def save_json(path, value):
    write_new(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n')


def lines(records):
    return b''.join(canonical(x) + b'\n' for x in records)


def root_file(value):
    require(isinstance(value, str) and bool(value), 'Missing file path')
    path = (ROOT / value).resolve()
    require(path.is_relative_to(ROOT), 'Evidence path escapes repository')
    require(path.is_file(), 'Missing required file: ' + value)
    return path


def run_folder(value):
    folder = (ROOT / value).resolve()
    require(folder.is_relative_to(ROOT) and folder != ROOT, 'Run must be within repository')
    run = load(folder / 'run.json')
    require(run.get('managed_by') == MANAGED, 'Historical/unmanaged run is read-only; create a new editorial run')
    require(run.get('publication_authorized') is False, 'Publication must remain unauthorized')
    require(isinstance(run.get('run_id'), str) and run['run_id'], 'Missing run ID')
    date.fromisoformat(run['as_of_date'])
    return folder


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def nonempty(value, name):
    require(isinstance(value, str) and bool(value.strip()), 'Missing/nonstring ' + name)


def url(value):
    require(isinstance(value, str), 'Missing URL')
    parsed = urlparse(value)
    require(parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not parsed.username and not parsed.password, 'Invalid source URL')


def policy(folder):
    run = load(folder / 'run.json')
    for name, expected in run.get('snapshot_sha256', {}).items():
        path = (folder / name).resolve()
        require(path.is_relative_to(folder) and path.is_file() and digest(path.read_bytes()) == expected, 'Configuration/prompt snapshot changed: ' + name)
    active = load(folder / 'config/active_editorial_policy.json')
    approval = load(folder / 'config/source_approval.json')
    require(digest((folder / 'config/editorial_policy.md').read_bytes()) == POLICY_HASH, 'Snapshotted policy integrity failure')
    require(digest((ROOT / 'config/editorial_policy.md').read_bytes()) == POLICY_HASH, 'Active approved policy changed')
    for record in [active, approval]:
        require(record.get('approval_id') == APPROVAL_ID and record.get('policy_sha256') == POLICY_HASH, 'Source approval ID/hash mismatch')
        require(record.get('publication_authorized') is False, 'Source approval opens publication gate')
    require(active.get('active_policy_version') == 'v2' and approval.get('policy_version') == 'v2', 'V2 required')
    require(approval.get('human_decisions') == {'ACCEPT': 9, 'DEFER': 3, 'REJECT': 0}, 'Archived decision counts changed')
    if run.get('contract_version') == 2:
        event=load(folder/'config/rss_source_selection.json')
        require(digest((folder/'config/evidence_cache.jsonl').read_bytes())==event.get('expanded_corpus_sha256'),
                'Expanded cache differs from the human source-selection event')
    return active


def organization(item):
    return 'mit' if item['publisher_id'] == 'mit-sloan' else item['publisher_id']


def validate_items(items, folder):
    require(isinstance(items, list) and bool(items), 'Required evidence is unavailable')
    end = date.fromisoformat(load(folder / 'run.json')['as_of_date'])
    start = end - timedelta(days=29)
    seen = set()
    for item in items:
        require(isinstance(item, dict), 'Item must be an object')
        for key in ['item_id', 'version_id', 'source_id', 'publisher_id', 'title', 'published_at', 'retrieved_at', 'text_path']:
            nonempty(item.get(key), key)
        require(item['item_id'] not in seen, 'Duplicate evidence item ID')
        seen.add(item['item_id'])
        require(item.get('kind') in {'feed', 'youtube', 'podcast'}, 'Invalid evidence kind')
        url(item.get('url'))
        require('media_url' in item and 'segments_path' in item, 'Missing nullable evidence fields')
        if item['media_url'] is not None:
            url(item['media_url'])
        published = datetime.fromisoformat(item['published_at'].replace('Z', '+00:00'))
        retrieved = datetime.fromisoformat(item['retrieved_at'].replace('Z', '+00:00'))
        require(published.tzinfo is not None and retrieved.tzinfo is not None, 'Evidence dates require timezone')
        require(start <= published.astimezone(timezone.utc).date() <= end, 'Evidence outside as-of date window')
        text = root_file(item['text_path']).read_bytes()
        from processing.evidence_contract import verify_version
        verify_version(item, text)
        if load(folder/'run.json').get('contract_version') == 2:
            from processing.evidence_contract import verify_legacy_metadata
            verify_legacy_metadata(item,folder)
        if item['kind'] == 'feed':
            require(item['segments_path'] is None, 'Written item must not have media segments')
        else:
            segment_path = root_file(item.get('segments_path'))
            if item.get('segments_sha256'):
                require(digest(segment_path.read_bytes()) == item['segments_sha256'], 'Segments integrity failure')
            segments = load(segment_path)
            require(isinstance(segments, list) and bool(segments), 'Missing timed segments')
            ids = set()
            for segment in segments:
                require(isinstance(segment, dict), 'Segment must be an object')
                nonempty(segment.get('segment_id'), 'segment_id')
                nonempty(segment.get('text'), 'segment text')
                require(segment['segment_id'] not in ids, 'Duplicate segment ID')
                ids.add(segment['segment_id'])
                times = [segment.get('start_seconds'), segment.get('end_seconds')]
                require(all(type(t) in (int, float) and math.isfinite(t) for t in times), 'Invalid segment times')
                require(0 <= times[0] < times[1], 'Invalid segment interval')
        if load(folder/'run.json').get('contract_version') == 2 and item['kind'] != 'feed':
            from processing.evidence_contract import check_media
            check_media(item)
            require(not item.get('media_is_fixture') or load(folder/'run.json')['mode']=='contract_offline_test', 'Fixture media cannot enter live evidence')
    return {x['item_id']: x for x in items}


def decisions_valid(records, items):
    from collections import Counter
    require(isinstance(records, list), 'Decision records must be objects')
    expected = {(key, item['version_id']) for key, item in items.items()}
    pairs = []
    invalid = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            invalid.append(f'{index}: Decision records must be objects')
            continue
        identifiers = [record.get('item_id'), record.get('version_id')]
        if not all(isinstance(x, str) and bool(x.strip()) for x in identifiers):
            invalid.append(f'{index}: Invalid decision identifiers')
        else:
            pairs.append(tuple(identifiers))
        decision = record.get('decision')
        if not isinstance(decision, str) or decision not in {'accept', 'reject', 'defer'}:
            invalid.append(f'{index}: Invalid editorial decision')
    counts = Counter(pairs)
    actual = set(counts)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    duplicates = [(pair, count) for pair, count in sorted(counts.items()) if count > 1]
    versions = {}
    for key, version in sorted(actual):
        versions.setdefault(key, []).append(version)
    conflicts = [(key, values) for key, values in sorted(versions.items()) if len(values) > 1]
    require(len(records) == len(items) and not any([missing, unexpected, duplicates, conflicts, invalid]),
            'One decision required per eligible item; '
            f'expected_count={len(items)} returned_count={len(records)}; '
            f'missing={missing}; unexpected={unexpected}; duplicate_pairs={duplicates}; '
            f'conflicting_item_versions={conflicts}; invalid_records={invalid}')
    by = {}
    for record in records:
        key = record.get('item_id')
        require(key in items and key not in by, 'Unknown/duplicate decision item')
        require(record.get('version_id') == items[key]['version_id'], 'Decision version mismatch')
        require(record.get('decision') in {'accept', 'reject', 'defer'}, 'Invalid editorial decision')
        nonempty(record.get('reason'), 'decision reason')
        pieces = record.get('piece_ids')
        require(isinstance(pieces, list) and all(isinstance(x, str) and x in PIECES for x in pieces) and len(pieces) == len(set(pieces)), 'Invalid decision piece IDs')
        require(bool(pieces) if record['decision'] == 'accept' else pieces == [], 'Only accepted items may support pieces')
        require(record.get('publication_authorized', False) is False, 'Decision permits publication')
        by[key] = record
    return by


def preserved_decisions(folder, records, items):
    """Validate saved decisions independently of the selection entry point."""
    by = decisions_valid(records, items)
    archive = jsonl(folder / 'config/human_decisions_v2.jsonl')
    require(digest((folder / 'config/human_decisions_v2.jsonl').read_bytes()) == digest((ROOT / 'runs/editorial-prep/human_decisions_v2.jsonl').read_bytes()), 'Human selection snapshot differs from archive')
    history = {x['item_id']: x for x in archive}
    require(len(history) == 12, 'Archived selection must remain distinct and complete')
    for key, record in by.items():
        if key in history and record['version_id'] == history[key]['version_id']:
            old = history[key]
            require(record['version_id'] == old['version_id'] and record['decision'] == old['human_decision'].lower(), 'Archived human decision/version changed')
            require(record.get('human_review_status') == 'confirmed' and record.get('source_approval_id') == APPROVAL_ID, 'Missing archived source approval provenance')
        else:
            require(record.get('human_review_status') == 'pending', 'New source decisions cannot claim archived human confirmation')
            require(record.get('source_approval_id') is None, 'Changed/new version cannot claim historical source approval')
    return by


def human_record(record):
    for key in ['reviewer', 'reviewed_at', 'notes']:
        nonempty(record.get(key), 'human ' + key)
    when = datetime.fromisoformat(record['reviewed_at'].replace('Z', '+00:00'))
    require(when.tzinfo is not None, 'Human review timestamp requires timezone')
    require(record.get('publication_authorized', False) is False, 'Human review cannot open publication gate')


def confirmed_new_sources(folder, decisions):
    """Read separate human confirmation for new live-source recommendations."""
    path = folder / 'source_review.json'
    bound = set()
    event_path = folder/'config/rss_source_selection.json'
    if event_path.is_file():
        policy(folder)
        event=load(event_path)
        payload={k:v for k,v in event.items() if k not in {'event_id','payload_sha256'}}
        require(digest(canonical(payload))==event['payload_sha256'] and event['event_id']=='da6884883a48d1c0', 'Source-selection event integrity failure')
        require(event.get('event_type')=='human_source_selection_only' and event.get('publication_authorized') is False and event.get('final_content_human_approved') is False, 'Source-selection scope invalid')
        for selected in event['selections']:
            d=decisions.get(selected['item_id'])
            if d and d['version_id']==selected['version_id'] and d['decision']=='accept':
                bound.add(d['item_id'])
    if not path.exists():
        return bound
    record = load(path)
    human_record(record)
    require(record.get('decision') == 'approve', 'Source review requests revision')
    require(record.get('decisions_sha256') == digest((folder / 'decisions.jsonl').read_bytes()) and
            record.get('eligible_sha256') == digest((folder / 'eligible.jsonl').read_bytes()), 'Source review is stale')
    reviewed = record.get('items')
    require(isinstance(reviewed, list), 'Source review needs explicit item decisions')
    seen = set()
    for item in reviewed:
        require(isinstance(item, dict), 'Human source review item must be an object')
        key = item.get('item_id')
        require(key in decisions and key not in seen, 'Unknown/duplicate human source review item')
        require(item.get('version_id') == decisions[key]['version_id'] and item.get('decision') == decisions[key]['decision'], 'Source review differs from saved recommendation; create a new run for changes')
        seen.add(key)
    return seen | bound


def briefs_valid(records, items, decisions):
    require(isinstance(records, list) and all(isinstance(x, dict) for x in records), 'Brief records must be objects')
    require(len(records) == 3 and {x.get('piece_id') for x in records} == PIECES, 'Exactly three briefs required')
    titles = set()
    claim_ids = set()
    for brief in records:
        piece = brief['piece_id']
        for key in ['title', 'question', 'argument', 'synthesis', 'limitations']:
            nonempty(brief.get(key), key)
        require(brief['title'] not in titles, 'Brief titles must be distinct')
        titles.add(brief['title'])
        claims = brief.get('claims')
        require(isinstance(claims, list) and bool(claims), 'Brief lacks claims')
        publishers = set()
        for claim in claims:
            require(isinstance(claim, dict), 'Claim must be an object')
            cid = claim.get('claim_id')
            require(isinstance(cid, str) and cid.startswith(piece + '-c') and cid not in claim_ids, 'Invalid/duplicate claim ID')
            claim_ids.add(cid)
            nonempty(claim.get('statement'), 'claim statement')
            require(claim.get('type') in {'reported_fact', 'source_claim', 'inference'}, 'Invalid claim type')
            refs = claim.get('evidence')
            require(isinstance(refs, list) and bool(refs), 'Claim lacks evidence')
            for ref in refs:
                require(isinstance(ref, dict), 'Evidence reference must be an object')
                key = ref.get('item_id')
                require(key in items and key in decisions, 'Unknown evidence reference')
                item, decision = items[key], decisions[key]
                require(ref.get('version_id') == item['version_id'], 'Evidence version mismatch')
                require(decision['decision'] == 'accept' and piece in decision['piece_ids'], 'Unaccepted/unassigned evidence')
                publishers.add(organization(item))
                locator = ref.get('locator')
                require(isinstance(locator, dict), 'Missing locator')
                if item['kind'] == 'feed':
                    nonempty(locator.get('quote'), 'exact evidence quote')
                    require(locator.get('type') == 'text' and locator['quote'] in root_file(item['text_path']).read_text(encoding='utf-8'), 'Quote not found in exact source version')
                else:
                    require(locator.get('type') == 'segment', 'Timed media locator required')
                    segments = load(root_file(item['segments_path']))
                    require(locator.get('segment_id') in {x['segment_id'] for x in segments}, 'Unknown media segment')
                    require(not locator.get('verified_quote', False), 'Caption/transcript cues cannot be marked verified by automation')
        require(len(publishers) >= 3, 'Each piece requires three independent organizations')
    return records


def manifest_valid(records, briefs, folder, kind):
    require(isinstance(records, list) and all(isinstance(x, dict) for x in records), 'Manifest records must be objects')
    require(len(records) == 3 and {x.get('piece_id') for x in records} == PIECES, 'Exactly three content manifests required')
    by = {b['piece_id']: b for b in briefs}
    for record in records:
        piece = record['piece_id']
        path = root_file(record.get('path'))
        require(path == (folder / kind / (piece + '.md')).resolve(), 'Unexpected content output path')
        expected = [c['claim_id'] for c in by[piece]['claims']]
        require(record.get('claim_ids') == expected, 'Content claim IDs differ from brief')
        text = path.read_text(encoding='utf-8')
        require(all('[' + cid + ']' in text for cid in expected), 'Missing inspectable claim markers')
        require(load(folder / 'run.json')['as_of_date'] in text, 'Missing as-of date')
        require('NOT AUTHORIZED' in text, 'Missing publication status')
    return records


def receipt(folder, stage, started, status, count_in, count_out, errors, metadata=None):
    value = dict(stage=stage, status=status, started_at=started, finished_at=utc(), input_count=count_in, output_count=count_out,
                 tool='Python standard library', model=None, cost_usd=0, cost_is_estimate=False, errors=errors)
    if metadata:
        value.update(metadata)
    save_json(folder / 'logs' / (stage + '-' + uuid.uuid4().hex + '.json'), value)


def stage_main(stage, operation, stream=True):
    sys.stderr.reconfigure(encoding='utf-8')
    started = utc()
    folder = None
    count_in = None
    metadata = {}
    status = 'failure'
    errors = []
    count_out = None
    code = 0
    try:
        require(len(sys.argv) == 2, 'Usage: stage RUN_DIR')
        folder = run_folder(sys.argv[1])
        policy(folder)
        inputs = parse_lines(sys.stdin.buffer.read().decode('utf-8')) if stream else None
        count_in = len(inputs) if stream else None
        result = operation(folder, inputs, metadata)
        status = 'success'
        if isinstance(result, list):
            count_out = len(result)
            sys.stdout.buffer.write(lines(result))
        else:
            count_out = 1
            sys.stdout.buffer.write(canonical(result) + b'\n')
    except (Invalid, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        errors = [str(exc)]
        code = 2
    except (OSError, RuntimeError) as exc:
        # Provider exceptions are sanitized by its adapter; never log request credentials.
        errors = [str(exc)]
        code = 1
    finally:
        if folder:
            receipt(folder, stage, started, status, count_in, count_out, errors, metadata)
    if errors:
        print(stage + ': ' + errors[0], file=sys.stderr)
    return code
