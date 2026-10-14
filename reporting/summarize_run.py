"""Report saved observations; absent stages and costs remain unknown."""
from collections import Counter
from datetime import datetime
from pipeline_common import jsonl, load, organization, stage_main


def summarize(folder, inputs, metadata):
    errors = []
    def records(name):
        if not (folder / name).exists():
            return None
        try:
            return jsonl(folder / name)
        except (OSError, ValueError):
            errors.append('Malformed ' + name)
            return None
    values = {name: records(name + '.jsonl') for name in ['candidates', 'items', 'changes', 'eligible', 'exclusions', 'decisions', 'articles', 'video_scripts']}
    def count(name):
        return None if values[name] is None else len(values[name])
    counts = {k: count(v) for k, v in [('discovered', 'candidates'), ('extracted', 'items'), ('eligible', 'eligible'), ('excluded', 'exclusions'), ('articles', 'articles'), ('video_scripts', 'video_scripts')]}
    for kind in ['new', 'changed', 'unchanged']:
        counts[kind] = None if values['changes'] is None else sum(x.get('change') == kind for x in values['changes'])
    for name, decision in [('accepted', 'accept'), ('rejected', 'reject'), ('deferred', 'defer')]:
        counts[name] = None if values['decisions'] is None else sum(x.get('decision') == decision for x in values['decisions'])
    receipts = []
    for path in sorted((folder / 'logs').glob('*.json')):
        try:
            receipts.append(load(path))
        except (OSError, ValueError):
            errors.append('Malformed receipt ' + path.name)
    latest = {}
    for r in sorted(receipts, key=lambda x: x.get('finished_at', '')):
        if r.get('stage'):
            latest[r['stage']] = r
    failed = [name for name, r in latest.items() if r.get('status') not in {'success'} and name != 'summarize_run']
    required = ['select_items', 'create_briefs', 'write_articles', 'write_video_scripts', 'check_content']
    if load(folder/'run.json').get('contract_version') == 2:
        required = ['collect_sources','fetch_feeds','fetch_youtube','fetch_podcasts','extract_content','store_upsert','filter_items'] + required
    missing = [s for s in required if s not in latest]
    review = load(folder / 'review.json') if (folder / 'review.json').exists() else None
    if review and review.get('passed') and not any(s in failed for s in required[:-1]):
        # A repaired current assessment supersedes an earlier workflow review block.
        failed = [s for s in failed if s != 'create_series']
    ready = False
    if (folder / 'package/manifest.json').exists():
        from review.check_content import assessment
        from publishing.prepare_package import approval_valid
        try:
            current = assessment(folder)
            approval_valid(load(folder / 'approval.json'), current)
            ready = load(folder / 'package/manifest.json').get('review_id') == current['review_id']
        except (OSError, ValueError, RuntimeError):
            errors.append('Existing package/approval no longer current')
    status = 'failed' if errors or failed or missing or not review or not review.get('passed') else ('ready_for_production' if ready else 'awaiting_review')
    evidence = values['eligible']
    coverage = None
    if evidence is not None:
        distinct = {x.get('underlying_item_id') or x['url']: x for x in evidence}.values()
        distinct = list(distinct)
        coverage = dict(distinct_items=len(distinct), by_kind=dict(Counter(x['kind'] for x in distinct)),
                        independent_publishers=sorted({organization(x) for x in distinct}),
                        discovery_methods=dict(Counter(x.get('discovery_method', 'unknown') for x in distinct)))
    dates = [r.get('started_at') for r in receipts] + [r.get('finished_at') for r in receipts]
    dates = [datetime.fromisoformat(x.replace('Z', '+00:00')) for x in dates if x]
    cost_receipts = [r for r in receipts if r.get('api_calls_performed') or r.get('response_mode') != 'offline_replay']
    unknown = [r.get('stage', 'unknown') for r in cost_receipts if r.get('cost_usd') is None]
    known = sum(r['cost_usd'] for r in cost_receipts if type(r.get('cost_usd')) in (int, float))
    run = load(folder / 'run.json')
    result = dict(run_id=run['run_id'], mode=run['mode'], status=status, publication_authorized=False,
                counts=counts, source_coverage=coverage, corpus_scope=run.get('corpus_scope'),
                duplicate_observations=None if values['candidates'] is None else len(values['candidates']) - len({x['item_id'] for x in values['candidates']}),
                failed_stages=failed, incomplete_stages=missing, errors=errors,
                elapsed_seconds=(max(dates) - min(dates)).total_seconds() if dates else None,
                known_cost_usd=known if receipts else None, unknown_cost_stages=unknown,
                model_tool_use=[{k: r.get(k) for k in ['stage', 'model', 'tool', 'cost_usd', 'response_mode', 'api_calls_performed', 'provider_request_attempted', 'usage']} for r in receipts],
                coverage_limitations=['Offline replay is not a fresh live run', 'Discovery provenance and independence require human inspection'] if run['mode'] == 'editorial_offline_replay' else ['Collection infrastructure limitations remain explicit'],
                published_links=load(folder / 'package/publication_links.json') if ready else None,
                remaining_manual_actions=['Resolve blocking review issues', 'Human final-content review', 'Video production', 'Separate publication authorization', 'Academic submission and technical demonstration'])
    if run.get('contract_version') == 2:
        cached = folder/'candidates/cached.jsonl'
        result['cached_candidate_count'] = len(jsonl(cached)) if cached.exists() else None
        result['fresh_discovery_count'] = counts['discovered']-result['cached_candidate_count'] if counts['discovered'] is not None and result['cached_candidate_count'] is not None else None
        unprocessed=folder/'processing_exclusions.jsonl'
        result['unprocessed_candidate_count']=len(jsonl(unprocessed)) if unprocessed.exists() else None
        if result['unprocessed_candidate_count']:
            result['coverage_limitations'] += ['Unmatched podcast candidates remain unprocessed; no new audio/transcription was authorized']
        result['coverage_limitations'] += ['Source media/caption context and interpretations require human verification']
        if run['mode']=='contract_offline_test':
            result['coverage_limitations'] += ['EXPLICIT OFFLINE CONTRACT TEST; not a genuine live execution']
        result['api_usage'] = []
        for response in (folder/'model_responses').glob('*.json'):
            envelope=load(response)
            result['api_usage'].append(dict(stage=response.stem,mode=envelope.get('mode'),model=envelope.get('model'),usage=envelope.get('usage'),cost_usd=envelope.get('cost_usd')))
    from pipeline_common import save_json, write_new, canonical
    import uuid
    if (folder/'summary.json').exists():
        write_new(folder/'summary_history'/(uuid.uuid4().hex+'.json'),(folder/'summary.json').read_bytes())
        (folder/'summary.json').write_bytes(canonical(result)+b'\n')
    else:
        save_json(folder/'summary.json',result)
    return result


if __name__ == '__main__':
    raise SystemExit(stage_main('summarize_run', summarize, stream=False))
