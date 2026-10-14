"""Prepare honest structural replay responses from archives, without generation.

Briefs are explicit test scaffolds, not invented factual synthesis. Existing
drafts are imported unchanged into new files and deliberately fail final review.
"""
import sys
from pipeline_common import (ROOT, canonical, digest, jsonl, load, relative, require,
                             root_file, run_folder, save_json, validate_items)
from model_adapter import request_for
from editorial.select_items import archived_decisions, select

ASSIGNMENTS = {
    '01': ['feed:8242ffb6d0f0509890f5', 'feed:cc11de4a9b0277b37619', 'podcast:54e93bb11c79c9a2fc0b', 'youtube:KgI2_dKnpk0'],
    '02': ['feed:5924aebf8110d4f48238', 'youtube:1FeLhg9HqfE', 'feed:ffcd4aee89c680fb7b22', 'feed:48f774f0bb11de5c34ef'],
    '03': ['feed:48f774f0bb11de5c34ef', 'feed:ffcd4aee89c680fb7b22', 'podcast:7f8cbebe3198e9935606', 'youtube:KgI2_dKnpk0', 'youtube:1FeLhg9HqfE'],
}
ARTICLE_FILES = ['01_ai_at_work.md', '02_who_should_decide.md', '03_ai_and_developing_economies.md']
VIDEO_FILES = ['01_ai_at_work_video.md', '02_who_should_decide_video.md', '03_developing_economies_video.md']


def envelope(folder, stage, inputs, evidence, output):
    request = request_for(folder, stage, inputs, evidence)
    save_json(folder / 'model_responses' / (stage + '.json'),
              dict(request_sha256=digest(canonical(request)), mode='offline_replay', model=None,
                   cost_usd=0, output=output, provenance='Archived human selection / structural brief scaffold / existing draft import; no model call'))


def prepare(folder):
    require(load(folder / 'run.json')['mode'] == 'editorial_offline_replay', 'Offline adapter only allowed for explicit replay')
    evidence = jsonl(folder / 'eligible.jsonl')
    items = validate_items(evidence, folder)
    history = archived_decisions(folder)
    require(set(items) == set(history), 'Replay must use the exact curated corpus IDs')
    output = []
    for item in evidence:
        old = history[item['item_id']]
        output.append(dict(item_id=item['item_id'], version_id=item['version_id'],
                           decision=old['human_decision'].lower(), reason=old['ai_reason'],
                           piece_ids=[piece for piece, ids in ASSIGNMENTS.items() if item['item_id'] in ids]))
    envelope(folder, 'select_items', evidence, evidence, output)
    # Match the real selection component's provenance enrichment for response binding.
    decisions = select(folder, evidence, {})
    briefs = []
    for number, (piece, ids) in enumerate(ASSIGNMENTS.items()):
        original = (ROOT / 'editorial/drafts' / ARTICLE_FILES[number]).read_text(encoding='utf-8')
        title = original.splitlines()[0].lstrip('# ')
        claims = []
        for index, key in enumerate(ids, 1):
            item = items[key]
            if item['kind'] == 'feed':
                # Exact bounded locator only; not an asserted interpretation of the prose.
                source = root_file(item['text_path']).read_text(encoding='utf-8')
                quote = next(line for line in source.splitlines() if len(line.strip()) >= 40)[:220]
                locator = dict(type='text', quote=quote)
            else:
                segments = load(root_file(item['segments_path']))
                seg = next(x for x in segments if len(x['text'].split()) >= 6)
                locator = dict(type='segment', segment_id=seg['segment_id'])
            claims.append(dict(claim_id=piece + '-c' + str(index),
                               statement='Offline locator scaffold for ' + item['title'] + '; contextual claim mapping is pending.',
                               type='source_claim', evidence=[dict(item_id=key, version_id=item['version_id'], locator=locator)]))
        briefs.append(dict(piece_id=piece, title=title, question='Which archived evidence passages support this existing draft?',
                           argument='Structural replay of the existing draft; substantive argument must be reviewed by the human editor.',
                           synthesis='This scaffold connects the existing draft to its previously listed source set without asserting that every prose claim is verified.',
                           limitations='Not a generated editorial brief. Passage selection is mechanical and may include navigation; semantic review remains required.',
                           claims=claims, offline_test_scaffold=True))
    envelope(folder, 'create_briefs', decisions, evidence, briefs)
    for stage, directory, filenames in [('write_articles', 'editorial/drafts', ARTICLE_FILES),
                                         ('write_video_scripts', 'writing/video_scripts', VIDEO_FILES)]:
        output = [dict(piece_id=piece, markdown=(ROOT / directory / filename).read_text(encoding='utf-8'),
                       imported_existing_draft=True) for piece, filename in zip(['01', '02', '03'], filenames)]
        envelope(folder, stage, briefs, evidence, output)
    save_json(folder / 'offline_replay_provenance.json', dict(
        mode='structural_test_only', source_corpus='runs/editorial-prep/corpus_verified.jsonl',
        original_source_as_of_date='2026-10-11', replay_as_of_date=load(folder / 'run.json')['as_of_date'],
        new_collection=False, new_generation=False, new_human_approval=False,
        expected_review_result='blocked: scaffolds, unverified imported prose and no accepted genuine RSS contribution',
        imported_draft_paths=['editorial/drafts/' + f for f in ARTICLE_FILES] + ['writing/video_scripts/' + f for f in VIDEO_FILES]))


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2, 'Usage: offline_replay RUN_DIR')
        prepare(run_folder(sys.argv[1]))
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print('Offline replay preparation: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
