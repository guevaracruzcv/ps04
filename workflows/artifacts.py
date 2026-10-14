"""Small orchestration utilities; stages own their processing."""
import sys
from pipeline_common import (MANAGED, Invalid, jsonl, load, parse_lines, policy, receipt,
                             require, run_folder, save_json, utc, write_new, canonical, digest, ROOT, relative)


def main():
    require(len(sys.argv) >= 3, 'Usage: artifacts ACTION RUN_DIR [NAME]')
    action, value = sys.argv[1:3]
    folder = run_folder(value)
    if action == 'preflight':
        policy(folder)
        for name in ['decisions.jsonl', 'briefs.jsonl', 'articles.jsonl', 'video_scripts.jsonl', 'review.json']:
            require(not (folder / name).exists(), 'Existing series is immutable; use a new run')
        require((folder / 'eligible.jsonl').is_file(), 'Eligible evidence missing')
    elif action == 'save':
        require(len(sys.argv) == 4 and sys.argv[3] in {'decisions.jsonl', 'briefs.jsonl', 'articles.jsonl', 'video_scripts.jsonl', 'review.json'}, 'Invalid output artifact')
        data = sys.stdin.buffer.read()
        if sys.argv[3].endswith('.jsonl'):
            require(bool(parse_lines(data.decode('utf-8'))), 'Stage emitted no records')
        else:
            import json
            review = json.loads(data)
            require(isinstance(review.get('passed'), bool) and isinstance(review.get('issues'), list), 'Invalid assessment output')
        write_new(folder / sys.argv[3], data)
    elif action == 'review-status':
        return 0 if load(folder / 'review.json')['passed'] else 1
    elif action == 'workflow-receipt':
        require(len(sys.argv) == 5, 'Receipt requires start and exit code')
        code = int(sys.argv[4])
        receipt(folder, 'create_series', sys.argv[3], 'success' if code == 0 else 'failure', None, None,
                [] if code == 0 else ['Series incomplete or content assessment has blocking errors'])
    elif action == 'cache-candidates':
        from datetime import date, timedelta
        from workflows.editorial_run import discovery_annotations
        end=date.fromisoformat(load(folder/'run.json')['as_of_date'])
        fresh={(x['kind'],x['url']) for name in ['feeds','youtube','podcasts']
               for x in jsonl(folder/('candidates/'+name+'.jsonl'))}
        for item in discovery_annotations(jsonl(folder/'config/evidence_cache.jsonl')):
            if item['kind']=='feed' and (item['kind'],item['url']) not in fresh and end-timedelta(days=29)<=date.fromisoformat(item['published_at'][:10])<=end:
                from processing.evidence_contract import verify_version
                verify_version(item,(ROOT/item['text_path']).read_bytes())
                value=dict(item,reuse_cached_evidence=True,reused_at_utc=utc())
                sys.stdout.buffer.write(canonical(value)+b'\n')
    elif action == 'collection-receipt':
        code=int(sys.argv[4])
        candidates=jsonl(folder/'candidates.jsonl') if (folder/'candidates.jsonl').exists() else None
        eligible=jsonl(folder/'eligible.jsonl') if (folder/'eligible.jsonl').exists() else None
        receipt(folder,'collect_sources',sys.argv[3],'success' if code==0 else 'failure',
                len(candidates) if candidates is not None else None,len(eligible) if eligible is not None else None,
                [] if code==0 else ['Collection incomplete; inspect individual source/stage receipts'])
    elif action == 'bind-source-selection':
        from pipeline_common import confirmed_new_sources
        records=jsonl(folder/'decisions.jsonl');by={x['item_id']:x for x in records}
        confirmed=confirmed_new_sources(folder,by)
        if (folder/'config/rss_source_selection.json').exists():
            save_json(folder/'source_selection_binding.json',dict(event_id=load(folder/'config/rss_source_selection.json')['event_id'],
                scope='existing human source selection only; not a new human decision',
                decisions_sha256=digest((folder/'decisions.jsonl').read_bytes()),eligible_sha256=digest((folder/'eligible.jsonl').read_bytes()),
                bound_items=[dict(item_id=key,version_id=by[key]['version_id']) for key in sorted(confirmed)],
                final_content_human_approved=False,publication_authorized=False))
    elif action == 'refresh-review':
        # Only managed new runs. Preserve every older assessment before replacing latest.
        import json
        import uuid
        data = sys.stdin.buffer.read()
        result = json.loads(data)
        require(isinstance(result.get('passed'), bool), 'Invalid review')
        if (folder / 'review.json').exists():
            write_new(folder / 'review_history' / (uuid.uuid4().hex + '.json'), (folder / 'review.json').read_bytes())
        (folder / 'review.json').write_bytes(data)
    else:
        raise Invalid('Unknown artifact action')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print('Artifact error: ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
