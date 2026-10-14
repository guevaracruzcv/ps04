"""Local production handoff, gated by current assessment and human approval."""
import json
import re
import uuid
from datetime import datetime
from pipeline_common import (canonical, digest, jsonl, load, relative, require, root_file,
                             save_json, stage_main, validate_items, write_new)
from content.render_common import source_notes
from review.check_content import assessment


def approval_valid(approval, review):
    if not review['passed']:
        raise RuntimeError('Content checks contain blocking errors; package refused')
    if approval.get('review_id') != review['review_id'] or approval.get('decision') != 'approve':
        raise RuntimeError('Missing, stale, or non-approving human final-content review')
    for field in ['reviewer', 'reviewed_at', 'notes']:
        require(isinstance(approval.get(field), str) and bool(approval[field].strip()), 'Human approval requires ' + field)
    reviewed = datetime.fromisoformat(approval['reviewed_at'].replace('Z', '+00:00'))
    require(reviewed.tzinfo is not None, 'Human review timestamp requires timezone')
    require(approval.get('publication_authorized', False) is False, 'This mission cannot authorize publication')


def package_payload(folder, review):
    """Pure assembly; tests can inspect payload without inventing approval."""
    items = validate_items(jsonl(folder / 'eligible.jsonl'), folder)
    briefs = jsonl(folder / 'briefs.jsonl')
    assets = {}
    entries = []
    for kind in ['articles', 'video_scripts']:
        for record in jsonl(folder / (kind + '.jsonl')):
            name = kind + '/' + record['piece_id'] + '.md'
            assets[name] = root_file(record['path']).read_bytes()
            entries.append(dict(piece_id=record['piece_id'], kind=kind, path=name, sha256=digest(assets[name])))
    for brief in briefs:
        name = 'source_notes/' + brief['piece_id'] + '.md'
        assets[name] = (source_notes(brief, items) + '\n').encode('utf-8')
        entries.append(dict(piece_id=brief['piece_id'], kind='source_notes', path=name, sha256=digest(assets[name])))
    # Retain complete local provenance in the handoff.
    for name in ['run.json', 'review.json', 'briefs.jsonl', 'decisions.jsonl', 'eligible.jsonl', 'articles.jsonl', 'video_scripts.jsonl']:
        assets[name] = (folder / name).read_bytes()
    for directory in ['config', 'prompts']:
        for path in (folder / directory).glob('*'):
            assets[directory + '/' + path.name] = path.read_bytes()
    for name in ['source_review.json', 'approval.json']:
        if (folder / name).is_file():
            assets[name] = (folder / name).read_bytes()
    for item in items.values():
        for field in ['text_path', 'segments_path']:
            if item.get(field):
                path = root_file(item[field])
                # Package paths retain root-relative provenance without rewriting IDs.
                assets['evidence/' + relative(path)] = path.read_bytes()
    manifest = dict(run_id=load(folder / 'run.json')['run_id'], review_id=review['review_id'],
                    publication_authorized=False, status='ready_for_production', assets=entries,
                    all_files_sha256={name: digest(data) for name, data in assets.items()},
                    evidence_paths_relative_to='repository root; copies stored under package/evidence/',
                    remaining_manual_actions=['Review warnings and source notes', 'Produce and review videos in Google Vids or HeyGen',
                                              'Obtain separate explicit publication authorization', 'Publish manually only after authorization',
                                              'Record actual Substack and YouTube links'])
    return assets, manifest


def existing_package(destination, assets, manifest):
    """Verify an unchanged package without rewriting entered publication links."""
    previous = load(destination / 'manifest.json')
    require(previous == manifest, 'Existing package differs; preserve it and create a new run')
    for name, data in assets.items():
        require((destination / name).read_bytes() == data, 'Existing package asset integrity failure')
    links = load(destination / 'publication_links.json')
    require(isinstance(links, list) and all(isinstance(x, dict) for x in links) and len(links) == 3 and {x.get('piece_id') for x in links} == {'01', '02', '03'}, 'Invalid existing publication links')
    return previous


def prepare(folder, inputs, metadata):
    review = assessment(folder)  # Direct invocation cannot bypass current checks.
    saved = load(folder / 'review.json')
    if saved.get('review_id') != review['review_id'] or saved.get('passed') is not True:
        raise RuntimeError('Saved review is missing, stale, or failed')
    if not (folder / 'approval.json').is_file():
        raise RuntimeError('Human final-content approval.json is missing; source approval is insufficient')
    approval_valid(load(folder / 'approval.json'), review)
    assets, manifest = package_payload(folder, review)
    destination = folder / 'package'
    if destination.exists():
        return existing_package(destination, assets, manifest)
    # Build in a new directory; retain partial attempts on failure for inspection.
    staging = folder / ('package-incomplete-' + uuid.uuid4().hex)
    staging.mkdir()
    for name, data in assets.items():
        write_new(staging / name, data)
    save_json(staging / 'publication_links.json', [dict(piece_id=p, substack_url=None, youtube_url=None) for p in ['01', '02', '03']])
    save_json(staging / 'manifest.json', manifest)
    current = assessment(folder)
    require(current['review_id'] == review['review_id'], 'Reviewed inputs changed during packaging')
    approval_valid(load(folder / 'approval.json'), current)
    staging.rename(destination)
    return manifest


if __name__ == '__main__':
    raise SystemExit(stage_main('prepare_package', prepare, stream=False))
