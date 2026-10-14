"""Three briefs grounded in accepted, exact-version evidence."""
from pipeline_common import briefs_valid, digest, load, preserved_decisions, jsonl, relative, require, stage_main, validate_items
from model_adapter import generate
from model_evidence import resolve_brief_quotes


def create(folder, inputs, metadata):
    require(inputs == jsonl(folder / 'decisions.jsonl'), 'Brief stdin differs from saved decisions')
    evidence = jsonl(folder / 'eligible.jsonl')
    items = validate_items(evidence, folder)
    decisions = preserved_decisions(folder, inputs, items)
    require(any(x['decision'] == 'accept' for x in inputs), 'No accepted evidence available')
    output = generate(folder, 'create_briefs', inputs, evidence, metadata)
    require(isinstance(output, list), 'Brief response must be an array')
    mode = load(folder / 'run.json')['mode']
    response_path = folder / 'model_responses/create_briefs.json'
    response = load(response_path)
    legacy_fixture = ((mode == 'contract_offline_test' and response.get('mode') == 'offline_contract_fixture') or
                      (mode == 'editorial_offline_replay' and response.get('mode') == 'offline_replay'))
    if not legacy_fixture:
        require(response.get('mode') == 'model_response', 'Non-fixture briefing needs a model response')
        request_hash = metadata['request_sha256']
        require(response.get('request_sha256') == request_hash and response.get('output') == output,
                'Brief response identity mismatch')
        raw_text = response.get('raw_output_text')
        require(isinstance(raw_text, str), 'Live briefing response lacks raw output text')
        import json
        require(json.loads(raw_text).get('output') == output, 'Raw briefing output differs from envelope')
        request = load(folder / 'model_requests' / ('create_briefs-' + request_hash + '.json'))
        output = resolve_brief_quotes(output, items, decisions, request, request_hash,
                                     digest(response_path.read_bytes()), relative(response_path))
        metadata['quotation_resolution_contract'] = request['written_quote_contract']
    else:
        metadata['quotation_resolution_contract'] = 'explicit_legacy_offline_quote_fixture'
    return briefs_valid(output, items, decisions)


if __name__ == '__main__':
    raise SystemExit(stage_main('create_briefs', create))
