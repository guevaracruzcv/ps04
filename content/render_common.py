"""Content-only helpers: validate prose and retain auditable claim/source notes."""
from pipeline_common import (briefs_valid, preserved_decisions, jsonl, load, manifest_valid,
                             relative, require, root_file, save_json, validate_items, write_new)
from model_adapter import generate


def source_notes(brief, items):
    lines = ['## Evidence notes for human review', '',
             'Claim links below establish traceability, not factual verification. YouTube cues are navigation markers; contextual review is required.', '']
    for claim in brief['claims']:
        lines.append('### [' + claim['claim_id'] + '] ' + claim['statement'])
        lines.append('Claim type: ' + claim['type'])
        for ref in claim['evidence']:
            item = items[ref['item_id']]
            locator = ref['locator']
            link = item['media_url'] if item['kind']=='podcast' else item['url']
            detail = 'Exact text passage: ' + locator['quote'] if locator['type'] == 'text' else ''
            if locator['type'] == 'segment':
                seg = next(s for s in load(root_file(item['segments_path'])) if s['segment_id'] == locator['segment_id'])
                detail = f"Segment {seg['segment_id']}, {seg['start_seconds']}–{seg['end_seconds']} seconds; contextual verification pending."
                if item['kind'] == 'youtube':
                    link += ('&' if '?' in link else '?') + 't=' + str(int(seg['start_seconds'])) + 's'
                    detail += ' Caption navigation cue, not a verified quotation.'
            lines.append(f"- [{item['title']}]({link}); {item['publisher_id']}; {item['item_id']}; version {item['version_id']}; discovery: {item.get('discovery_method', 'unknown')}. {detail}")
        lines.append('')
    return '\n'.join(lines)


def render(folder, inputs, metadata, kind, stage):
    require(inputs == jsonl(folder / 'briefs.jsonl'), 'Content stdin differs from saved briefs')
    evidence = jsonl(folder / 'eligible.jsonl')
    items = validate_items(evidence, folder)
    decisions = preserved_decisions(folder, jsonl(folder / 'decisions.jsonl'), items)
    briefs_valid(inputs, items, decisions)
    output = generate(folder, stage, inputs, evidence, metadata)
    require(isinstance(output, list) and all(isinstance(x, dict) for x in output) and len(output) == 3 and {x.get('piece_id') for x in output} == {'01', '02', '03'}, 'Three content responses required')
    by = {b['piece_id']: b for b in inputs}
    run = load(folder / 'run.json')
    manifests, assets = [], []
    for result in output:
        piece = result['piece_id']
        markdown = result.get('markdown')
        require(isinstance(markdown, str) and len(markdown.split()) >= 80, 'Missing/substantively empty generated content')
        claims = [x['claim_id'] for x in by[piece]['claims']]
        # Replay imports preserve archived prose and add a labeled review ledger.
        imported = result.get('imported_existing_draft') is True
        if imported:
            require(run['mode'] == 'editorial_offline_replay', 'Imported draft fixtures cannot enter live generation')
        else:
            require(all('[' + cid + ']' in markdown for cid in claims), 'Model content lacks in-text claim markers')
        header = f"**As-of evidence date:** {run['as_of_date']}\n**Publication:** NOT AUTHORIZED. Final wording awaits human review.\n"
        if imported:
            header += '**Offline replay:** Existing draft imported for structural testing. The appended evidence ledger does not verify every claim in its prose.\n'
        body = header + '\n' + markdown + '\n\n' + source_notes(by[piece], items) + '\n'
        target = folder / kind / (piece + '.md')
        require(not target.exists(), 'Content already exists; preserve it and create a new run')
        assets.append((target, body.encode('utf-8')))
        manifests.append(dict(piece_id=piece, path=relative(target), claim_ids=claims,
                              imported_existing_draft=imported, publication_authorized=False))
    # Validate every response before creating any content file.
    for target, body in assets:
        write_new(target, body)
    return manifest_valid(manifests, inputs, folder, kind)
