"""Lossless prompt-only evidence views; archived files and locators stay intact."""
from copy import deepcopy
from pipeline_common import canonical, digest, load, require, root_file
from processing.evidence_contract import verify_version


def rolling_prefix(previous, current):
    """Exact whole-word suffix/prefix overlap; no normalization or rewriting."""
    for size in range(min(len(previous), len(current)), 0, -1):
        start = len(previous) - size
        if start and not previous[start - 1].isspace():
            continue
        if size < len(current) and not current[size].isspace() and not current[size - 1].isspace():
            continue
        if previous.endswith(current[:size]):
            return size
    return 0


QUOTE_CONTRACT = 'bound-passages-v1'


def passage_id(item, number, start, end):
    binding = dict(item_id=item['item_id'], version_id=item['version_id'],
                   start_char=start, end_char=end)
    return f'p{number:04d}@' + digest(canonical(binding))


def validate_catalogue(item, text, rows):
    require(isinstance(rows, list) and bool(rows), 'Missing written passage catalogue')
    seen = set()
    previous = 0
    for number, row in enumerate(rows, 1):
        require(isinstance(row, list) and len(row) == 4, 'Invalid passage row')
        identifier, start, end, passage = row
        require(isinstance(identifier, str) and identifier not in seen, 'Duplicate or ambiguous passage ID')
        seen.add(identifier)
        require(type(start) is int and type(end) is int and
                0 <= start < end <= len(text) and start == previous, 'Invalid passage boundaries')
        require(identifier == passage_id(item, number, start, end), 'Unbound or stale passage ID')
        require(isinstance(passage, str) and text[start:end] == passage, 'Passage text differs from source')
        previous = end
    require(previous == len(text), 'Incomplete passage catalogue')
    return rows


def written_catalogue(item):
    raw = root_file(item['text_path']).read_bytes()
    verify_version(item, raw)
    text = raw.decode('utf-8', errors='strict')
    # briefs_valid uses universal-newline reads. Fail rather than normalize bytes.
    require('\r' not in text, 'CRLF/CR written evidence incompatible with unchanged quote validator')
    offset = 0
    rows = []
    for number, passage in enumerate(text.splitlines(keepends=True), 1):
        end = offset + len(passage)
        rows.append([passage_id(item, number, offset, end), offset, end, passage])
        offset = end
    return text, validate_catalogue(item, text, rows)


def resolve_brief_quotes(records, items, decisions, request, request_sha256,
                        response_sha256, response_path):
    """Resolve only request-bound selectors; never infer anchors from model prose."""
    require(digest(canonical(request)) == request_sha256, 'Stale quotation request binding')
    require(request.get('stage') == 'create_briefs' and
            request.get('written_quote_contract') == QUOTE_CONTRACT, 'Missing quotation selector contract')
    require(isinstance(response_sha256, str) and len(response_sha256) == 64,
            'Missing raw response identity')
    wire = request.get('evidence')
    require(isinstance(wire, list), 'Missing request evidence')
    catalogues = {}
    requested = set()
    for entry in wire:
        require(isinstance(entry, dict) and isinstance(entry.get('item'), dict), 'Invalid request evidence')
        item = entry['item']
        key = item.get('item_id')
        require(key in items and key not in requested and item == items[key], 'Request evidence identity mismatch')
        requested.add(key)
        if item['kind'] == 'feed':
            text, rows = written_catalogue(item)
            validate_catalogue(item, text, entry.get('written_passages'))
            require(entry['written_passages'] == rows, 'Request passage catalogue changed')
            catalogues[key] = text, {row[0]: row for row in rows}
    require(isinstance(records, list) and all(isinstance(b, dict) for b in records), 'Invalid brief response')
    resolved = deepcopy(records)
    for brief in resolved:
        piece = brief.get('piece_id')
        require(piece in {'01', '02', '03'}, 'Invalid brief piece')
        require(isinstance(brief.get('claims'), list), 'Missing brief claims')
        for claim in brief['claims']:
            require(isinstance(claim, dict) and isinstance(claim.get('evidence'), list), 'Missing claim evidence')
            for ref in claim['evidence']:
                require(isinstance(ref, dict), 'Invalid evidence reference')
                key = ref.get('item_id')
                require(key in requested and key in decisions, 'Unauthorized quotation source')
                item = items[key]
                require(ref.get('version_id') == item['version_id'], 'Quotation evidence version mismatch')
                require(decisions[key]['decision'] == 'accept' and piece in decisions[key]['piece_ids'] and
                        key in request.get('evidence_by_piece', {}).get(piece, []), 'Unaccepted or unassigned quotation source')
                if item['kind'] != 'feed':
                    continue  # Existing media contract and validator remain authoritative.
                loc = ref.get('locator')
                require(isinstance(loc, dict) and set(loc) == {'type', 'start_passage_id', 'end_passage_id'} and
                        loc['type'] == 'text', 'Written evidence requires selectors only; no quotes or arbitrary offsets')
                start_id, end_id = loc['start_passage_id'], loc['end_passage_id']
                text, catalogue = catalogues[key]
                require(isinstance(start_id, str) and isinstance(end_id, str) and
                        start_id in catalogue and end_id in catalogue, 'Unknown, cross-source or unbound passage ID')
                start, end = catalogue[start_id][1], catalogue[end_id][2]
                require(catalogue[start_id][1] <= catalogue[end_id][1] and
                        0 <= start < end <= len(text), 'Reversed or invalid quotation range')
                quote = text[start:end]
                require(bool(quote.strip()), 'Empty selected quotation')
                ref['quotation_resolution'] = dict(contract=QUOTE_CONTRACT, item_id=key,
                    version_id=item['version_id'], original_selector=deepcopy(loc),
                    start_char=start, end_char=end, request_sha256=request_sha256,
                    raw_response_sha256=response_sha256, raw_response_path=response_path,
                    quote_utf8_sha256=digest(quote.encode('utf-8')))
                ref['locator'] = dict(type='text', quote=quote)
    return resolved


def evidence_view(item):
    if item['kind'] == 'feed':
        text, rows = written_catalogue(item)
    else:
        text = root_file(item['text_path']).read_text(encoding='utf-8')
        verify_version(item, root_file(item['text_path']).read_bytes())
    result = {'item': dict(item)}
    if item['kind'] == 'feed':
        result.update(written_columns=['passage_id', 'start_char', 'end_char', 'text'],
                      written_passages=rows)
    else:
        segment_path = root_file(item['segments_path'])
        if item.get('segments_sha256'):
            require(digest(segment_path.read_bytes()) == item['segments_sha256'], 'Prompt segments integrity failure')
        segments = load(segment_path)
        rows = []
        previous = ''
        for segment in segments:
            current = segment['text']
            overlap = rolling_prefix(previous, current) if item['kind'] == 'youtube' else 0
            rows.append([segment['segment_id'], segment['start_seconds'],
                         segment['end_seconds'], overlap, current[overlap:]])
            previous = current
        result.update(media_columns=['segment_id', 'start_seconds', 'end_seconds',
                                     'previous_suffix_chars', 'new_text'], media_rows=rows)
        if '\n'.join(segment['text'] for segment in segments) != text:
            # Do not discard unique untimed context in a future source.
            result['supplemental_text'] = text
    return result


FORMAT_INSTRUCTIONS = (
    'Lossless prompt view v1. Original source versions and paths remain in item. '
    'Written passages contain exact source text including original newlines; '
    'start_char/end_char are Python Unicode character offsets into that source. '
    'Passage IDs bind the source item, evidence version and character boundaries. '
    'For bound-passages-v1 briefing requests return passage endpoints, never quote text. '
    'Other stage contracts retain their existing evidence semantics. Never paraphrase '
    'inside a literal quotation. Media rows preserve every original ID and '
    'timestamp. Reconstruct each cue as the last previous_suffix_chars characters '
    'of the PREVIOUS RECONSTRUCTED cue plus new_text; zero means new_text alone. '
    'A duplicate flattened transcript is omitted; supplemental_text, if present, '
    'retains differing untimed source context. Use original segment IDs for media '
    'locators. Caption/transcript cues do not establish verified quotations. '
    'evidence_by_piece lists accepted source IDs assigned to each brief.'
)
