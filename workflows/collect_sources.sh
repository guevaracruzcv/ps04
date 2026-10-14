#!/usr/bin/env bash
set -euo pipefail

# PS04 - Collection Workflow
# Usage: bash workflows/collect_sources.sh RUN_DIR
#
# Stages:
# 1. Collect candidates
# 2. Extract content
# 3. Store evidence
# 4. Retrieve latest corpus
# 5. Apply freshness filter
#
# Current scope: RSS articles only.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -ne 1 ]]; then
    echo "Usage: bash workflows/collect_sources.sh RUN_DIR" >&2
    exit 2
fi

RUN_DIR="$1"

if [[ ! -f "$RUN_DIR/run.json" ]]; then
    echo "ERROR: run.json not found in $RUN_DIR" >&2
    exit 2
fi

mkdir -p "$RUN_DIR/logs"

echo "PS04 Collection Workflow"
echo "Run directory: $RUN_DIR"

# Prospective contract path; legacy collect/replay workflows below are unchanged.
if python -B -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1],encoding="utf-8")).get("contract_version")==2 else 1)' "$RUN_DIR/run.json"; then
    STARTED="$(python -B -c 'from pipeline_common import utc; print(utc())')"
    code=0
    trap 'last=$?; if [[ "$last" -ne 0 ]]; then code=$last; fi; python -B -m workflows.artifacts collection-receipt "$RUN_DIR" "$STARTED" "$code"; exit "$code"' EXIT
    export PS04_RUN_DIR="$RUN_DIR"
    bash data/store.sh init || exit $?
    bash data/store.sh list > "$RUN_DIR/prior_corpus.jsonl" || exit $?
    mkdir -p "$RUN_DIR/candidates"
    for pair in 'feeds feed' 'youtube youtube' 'podcasts podcast'; do
        read -r name kind <<< "$pair"
        if bash "collectors/fetch_${name}.sh" "$RUN_DIR" > "$RUN_DIR/candidates/$name.jsonl"; then
            :
        else
            stage_code=$?
            if [[ "$stage_code" -eq 2 ]]; then code=2; elif [[ "$code" -eq 0 ]]; then code=1; fi
        fi
    done
    python -B -m workflows.artifacts cache-candidates "$RUN_DIR" > "$RUN_DIR/candidates/cached.jsonl" || code=2
    cat "$RUN_DIR/candidates/feeds.jsonl" "$RUN_DIR/candidates/youtube.jsonl" "$RUN_DIR/candidates/podcasts.jsonl" "$RUN_DIR/candidates/cached.jsonl" > "$RUN_DIR/candidates.jsonl"
    if bash processing/extract_content.sh "$RUN_DIR" < "$RUN_DIR/candidates.jsonl" > "$RUN_DIR/items.jsonl"; then :; else
        stage_code=$?
        if [[ "$stage_code" -eq 2 ]]; then code=2; elif [[ "$code" -eq 0 ]]; then code=1; fi
    fi
    if [[ ! -s "$RUN_DIR/items.jsonl" ]]; then exit 1; fi
    bash data/store.sh upsert "$RUN_DIR" < "$RUN_DIR/items.jsonl" > "$RUN_DIR/changes.jsonl" || exit $?
    bash data/store.sh list > "$RUN_DIR/corpus.jsonl" || exit $?
    bash processing/filter_items.sh "$RUN_DIR" < "$RUN_DIR/corpus.jsonl" > "$RUN_DIR/eligible.jsonl" || exit $?
    exit "$code"
fi

# Stage 1: Collect
echo "[1/5] Collecting candidates"

if [[ -n "${PS04_CANDIDATES_FILE:-}" ]]; then
    echo "Using supplied candidate fixture"
    cp "$PS04_CANDIDATES_FILE" "$RUN_DIR/candidates.jsonl"
else
    echo "Collecting live RSS feeds"
    bash collectors/fetch_feeds.sh \
        > "$RUN_DIR/candidates.jsonl"

    echo "Collecting YouTube videos"
    bash collectors/fetch_youtube.sh "$RUN_DIR" \
        >> "$RUN_DIR/candidates.jsonl"
fi

# PS04_PODCAST_REUSE_BEGIN: retrieve podcast RSS metadata, never audio
# Fixture runs retain their existing behavior.
if [[ -z "${PS04_CANDIDATES_FILE:-}" ]]; then
    PODCAST_SOURCES="${PS04_PODCAST_SOURCES:-config/podcast_sources.json}"
    if [[ ! -f "$PODCAST_SOURCES" ]]; then
        echo "ERROR: missing podcast sources: $PODCAST_SOURCES" >&2
        exit 2
    fi
    echo "Collecting podcast RSS metadata"
    PS04_PODCAST_SOURCES="$PODCAST_SOURCES" bash collectors/fetch_podcasts.sh "$RUN_DIR" \
        > "$RUN_DIR/podcast_candidates.jsonl"
    if [[ ! -s "$RUN_DIR/podcast_candidates.jsonl" ]]; then
        echo "ERROR: podcast RSS collector returned no candidates" >&2
        exit 1
    fi
fi

# Stage 2: Extract
echo "[2/5] Extracting article content"

EXTRACT_STATUS=0

bash processing/extract_content.sh "$RUN_DIR" \
    < "$RUN_DIR/candidates.jsonl" \
    > "$RUN_DIR/items.jsonl" \
    || EXTRACT_STATUS=$?

if [[ "$EXTRACT_STATUS" -ne 0 ]]; then
    echo "WARNING: Extraction encountered errors (exit $EXTRACT_STATUS)" >&2
fi

if [[ ! -s "$RUN_DIR/items.jsonl" ]]; then
    echo "ERROR: No extracted items available for storage" >&2
    exit 1
fi

# Reuse only episodes whose audio enclosure URL, title and date match
# transcript evidence already verified. New episodes remain untranscribed.
if [[ -s "$RUN_DIR/podcast_candidates.jsonl" ]]; then
    echo "[2b/5] Matching podcasts to existing verified transcripts"
    python processing/reuse_podcast_evidence.py \
        "$RUN_DIR" \
        "$RUN_DIR/podcast_candidates.jsonl" \
        "runs/editorial-prep/corpus_verified.jsonl" \
        > "$RUN_DIR/podcast_items.jsonl"
    cat "$RUN_DIR/podcast_items.jsonl" >> "$RUN_DIR/items.jsonl"
fi
# PS04_PODCAST_REUSE_END

# Stage 3: Store
echo "[3/5] Preserving evidence in SQLite"

bash data/store.sh upsert "$RUN_DIR" \
    < "$RUN_DIR/items.jsonl" \
    > "$RUN_DIR/changes.jsonl"

# Stage 4: Retrieve
echo "[4/5] Retrieving latest corpus"

bash data/store.sh list \
    > "$RUN_DIR/corpus.jsonl"

# Stage 5: Filter
echo "[5/5] Applying freshness policy"

bash processing/filter_items.sh "$RUN_DIR" \
    < "$RUN_DIR/corpus.jsonl" \
    > "$RUN_DIR/eligible.jsonl"

echo "Candidates: $RUN_DIR/candidates.jsonl"
echo "Items:      $RUN_DIR/items.jsonl"
echo "Changes:    $RUN_DIR/changes.jsonl"
echo "Corpus:     $RUN_DIR/corpus.jsonl"
echo "Eligible:   $RUN_DIR/eligible.jsonl"

if [[ "$EXTRACT_STATUS" -ne 0 ]]; then
    echo "Collection workflow completed: PARTIAL"
    echo "Some candidates failed extraction." >&2
    exit 1
fi

echo "Collection workflow completed: SUCCESS"
exit 0