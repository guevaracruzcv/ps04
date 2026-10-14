#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ $# -ne 1 ]]; then echo "Usage: create_series.sh RUN_DIR" >&2; exit 2; fi
RUN_DIR="$1"
python -B -m workflows.artifacts preflight "$RUN_DIR"
STARTED="$(python -B -c 'from pipeline_common import utc; print(utc())')"
trap 'code=$?; python -B -m workflows.artifacts workflow-receipt "$RUN_DIR" "$STARTED" "$code"; exit "$code"' EXIT
cat "$RUN_DIR/eligible.jsonl" | bash editorial/select_items.sh "$RUN_DIR" | python -B -m workflows.artifacts save "$RUN_DIR" decisions.jsonl
python -B -m workflows.artifacts bind-source-selection "$RUN_DIR"
cat "$RUN_DIR/decisions.jsonl" | bash editorial/create_briefs.sh "$RUN_DIR" | python -B -m workflows.artifacts save "$RUN_DIR" briefs.jsonl
cat "$RUN_DIR/briefs.jsonl" | bash content/write_articles.sh "$RUN_DIR" | python -B -m workflows.artifacts save "$RUN_DIR" articles.jsonl
cat "$RUN_DIR/briefs.jsonl" | bash content/write_video_scripts.sh "$RUN_DIR" | python -B -m workflows.artifacts save "$RUN_DIR" video_scripts.jsonl
bash review/check_content.sh "$RUN_DIR" | python -B -m workflows.artifacts save "$RUN_DIR" review.json
python -B -m workflows.artifacts review-status "$RUN_DIR"
