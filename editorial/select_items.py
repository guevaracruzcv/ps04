"""Selection component: model recommendations with immutable archived decisions."""
from collections import Counter
from pipeline_common import APPROVAL_ID, decisions_valid, jsonl, load, require, stage_main, validate_items
from model_adapter import generate


def archived_decisions(folder):
    records = jsonl(folder / 'config/human_decisions_v2.jsonl')
    require(len(records) == 12 and len({x['item_id'] for x in records}) == 12, 'Archived human decisions incomplete')
    require(Counter(x['human_decision'] for x in records) == {'ACCEPT': 9, 'DEFER': 3}, 'Archived human counts changed')
    for x in records:
        require(x.get('v2_approval_id') == APPROVAL_ID and x.get('human_review_status') == 'confirmed' and x.get('publication_authorized') is False, 'Invalid archived approval provenance')
    return {x['item_id']: x for x in records}


def select(folder, inputs, metadata):
    items = validate_items(inputs, folder)
    eligible = jsonl(folder / 'eligible.jsonl')
    require(inputs == eligible, 'Selection stdin differs from saved eligible evidence')
    history = archived_decisions(folder)
    output = generate(folder, 'select_items', inputs, inputs, metadata)
    require(isinstance(output, list), 'Selection output must be an array')
    decisions_valid(output, items)
    for record in output:
        # Never trust a model to assert human authority.
        require(not any(k in record for k in ['human_decision', 'human_review_status', 'approval_id', 'v2_approval_id']), 'Model output must not manufacture human metadata')
        old = history.get(record['item_id'])
        if old and record['version_id'] == old['version_id']:
            require(record['decision'] == old['human_decision'].lower(), 'Model would change archived human decision')
            record.update(human_review_status='confirmed', source_approval_id=APPROVAL_ID,
                          human_decision_provenance=old['human_decision_provenance'])
        else:
            record['human_review_status'] = 'pending'
        record['publication_authorized'] = False
    from pipeline_common import confirmed_new_sources
    event_path=folder/'config/rss_source_selection.json'
    if event_path.exists():
        event=load(event_path)
        pairs={(x['item_id'],x['version_id']) for x in event['selections']}
        for record in output:
            if (record['item_id'],record['version_id']) in pairs:
                require(record['decision']=='accept' and '02' in record['piece_ids'], 'Existing human RSS selection must contribute to Article 2')
                record['source_selection_event_id']=event['event_id']
        confirmed_new_sources(folder,{x['item_id']:x for x in output})
    metadata['human_decisions_changed'] = False
    return output


if __name__ == '__main__':
    raise SystemExit(stage_main('select_items', select))
