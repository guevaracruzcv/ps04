"""Mechanical assessment and content fingerprint; never supplies human approval."""
import re
from collections import Counter
from pipeline_common import (Invalid, MANAGED, briefs_valid, canonical, preserved_decisions, confirmed_new_sources, digest,
                             jsonl, load, manifest_valid, organization, policy, root_file,
                             stage_main, validate_items)


def assessment(folder):
    issues = []
    hashes = {}
    records = {}

    def issue(artifact, severity, message):
        issues.append(dict(artifact=artifact, severity=severity, message=message))

    # Fingerprint exact run inputs, not receipts/review/approval/publication links.
    paths = [folder / 'run.json']
    hashes['source_review.json'] = digest((folder / 'source_review.json').read_bytes()) if (folder / 'source_review.json').exists() else None
    paths += list((folder / 'config').glob('*')) + list((folder / 'prompts').glob('*'))
    paths += [folder / x for x in ['eligible.jsonl', 'decisions.jsonl', 'briefs.jsonl', 'articles.jsonl', 'video_scripts.jsonl']]
    paths += [folder / kind / (piece + '.md') for kind in ['articles', 'video_scripts'] for piece in ['01', '02', '03']]
    for path in sorted(paths):
        key = path.relative_to(folder).as_posix()
        if path.is_file():
            hashes[key] = digest(path.read_bytes())
        else:
            hashes[key] = None
            issue(key, 'error', 'Required assessed file is missing')
    for name in ['eligible', 'decisions', 'briefs', 'articles', 'video_scripts']:
        try:
            records[name] = jsonl(folder / (name + '.jsonl'))
        except (OSError, ValueError):
            records[name] = []
            issue(name + '.jsonl', 'error', 'Missing or malformed record stream')
    evidence = records['eligible']
    for item in evidence:
        for field in ['text_path', 'segments_path', 'source_media_path']:
            if item.get(field):
                try:
                    path = root_file(item[field])
                    hashes['evidence:' + item['item_id'] + ':' + field] = digest(path.read_bytes())
                except (OSError, ValueError, KeyError):
                    hashes['evidence:' + str(item.get('item_id')) + ':' + field] = None
                    issue('eligible.jsonl', 'error', 'Missing or unsafe evidence path')
    try:
        policy(folder)
        items = validate_items(evidence, folder)
        decisions = preserved_decisions(folder, records['decisions'], items)
        separately_confirmed = confirmed_new_sources(folder, decisions)
        briefs_valid(records['briefs'], items, decisions)
        if any(b.get('offline_test_scaffold') for b in records['briefs']):
            issue('briefs.jsonl', 'error', 'Offline structural scaffolds are not completed editorial synthesis')
        for kind in ['articles', 'video_scripts']:
            manifest_valid(records[kind], records['briefs'], folder, kind)
        if len(items) < 12 or len({organization(x) for x in items.values()}) < 6:
            issue('eligible.jsonl', 'error', 'Corpus needs 12 distinct items and six independent organizations')
        kinds = Counter(x['kind'] for x in items.values())
        if any(kinds[k] < 2 for k in ['feed', 'youtube', 'podcast']):
            issue('eligible.jsonl', 'error', 'At least two items of each input type required')
        if sum(x['kind'] == 'feed' and x.get('discovery_method') == 'rss' for x in items.values()) < 2:
            issue('eligible.jsonl', 'error', 'At least two written items need genuine RSS discovery evidence')
        underlying = [x.get('underlying_item_id') or x['url'] for x in items.values()]
        if len(underlying) != len(set(underlying)):
            issue('eligible.jsonl', 'error', 'Duplicate underlying material requires reconciliation')
        refs = [ref for b in records['briefs'] for c in b['claims'] for ref in c['evidence']]
        used = {ref['item_id'] for ref in refs}
        if {items[key]['kind'] for key in used} != {'feed', 'podcast', 'youtube'}:
            issue('briefs.jsonl', 'error', 'All three input types must contribute to the series')
        if not any(items[key].get('discovery_method') == 'rss' and items[key]['kind'] == 'feed' for key in used):
            issue('briefs.jsonl', 'error', 'No accepted genuine RSS written evidence contributes; feed labels alone do not prove RSS')
        for key in used:
            if decisions[key].get('human_review_status') != 'confirmed' and key not in separately_confirmed:
                issue('decisions.jsonl', 'error', 'Source selection awaits human review: ' + key)
            if items[key].get('discovery_method') not in {'rss', 'direct_webpage', 'youtube', 'podcast_rss'}:
                issue('eligible.jsonl', 'error', 'Unknown discovery provenance: ' + key)
        if any(x['kind'] == 'youtube' for x in items.values() if x['item_id'] in used):
            issue('briefs.jsonl', 'warning', 'YouTube caption cues are navigation markers, not verified quotations; review surrounding media')
        if any(x.get('media_is_fixture') for x in items.values()):
            issue('series','warning','EXPLICIT OFFLINE MEDIA FIXTURES; no actual media collection demonstrated')
        for kind in ['articles', 'video_scripts']:
            for record in records[kind]:
                piece = record['piece_id']
                text = root_file(record['path']).read_text(encoding='utf-8')
                prose = text.split('## Evidence notes for human review')[0]
                prose = prose.split('### Editorial review notes')[0]
                words = len(re.findall(r"\b[\w’'-]+\b", prose))
                if record.get('imported_existing_draft'):
                    issue(record['path'], 'error', 'Imported draft replay does not establish prose-to-claim alignment; editorial mapping required')
                if kind == 'articles' and not 600 <= words <= 900:
                    issue(record['path'], 'warning', f'Approximate article length {words}; target 600–900 words')
                if kind == 'video_scripts' and (not 390 <= words <= 750 or '90 seconds' in prose):
                    issue(record['path'], 'warning', 'Script duration requires rehearsal and revision to 3–5 minutes')
                for ref in [r for c in next(b for b in records['briefs'] if b['piece_id'] == piece)['claims'] for r in c['evidence']]:
                    source=items[ref['item_id']]
                    audience_url=source['media_url'] if source['kind']=='podcast' else source['url']
                    if audience_url not in text:
                        issue(record['path'], 'error', 'Missing audience-facing source link')
        issue('series', 'warning', 'Machine validation checks references, not the truth of interpretations or complete independence; human factual review required')
    except (Invalid, ValueError, TypeError, KeyError, OSError) as exc:
        issue('series', 'error', str(exc))
    return dict(review_id=digest(canonical(hashes)), passed=not any(x['severity'] == 'error' for x in issues),
                issues=issues, assessed_sha256=hashes, publication_authorized=False,
                source_selection_approval_id='a589cd099dee6f96', human_final_review_required=True)


def check(folder, inputs, metadata):
    result = assessment(folder)
    metadata['assessment_passed'] = result['passed']
    return result


if __name__ == '__main__':
    raise SystemExit(stage_main('check_content', check, stream=False))
