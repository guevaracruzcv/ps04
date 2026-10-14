#!/usr/bin/env bash
set -euo pipefail

# PS04 - Content extraction
# Input: Candidate JSONL through stdin
# Output: Normalized Item JSONL through stdout

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -ne 1 ]]; then
    echo "Usage: bash processing/extract_content.sh RUN_DIR" >&2
    exit 2
fi

RUN_DIR="$1"

if [[ ! -f "$RUN_DIR/run.json" ]]; then
    echo "ERROR: run.json not found" >&2
    exit 2
fi

if python -B -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1],encoding="utf-8")).get("contract_version")==2 else 1)' "$RUN_DIR/run.json"; then
    cd "$ROOT"
    python -B -m processing.contract_extract "$RUN_DIR"
else
    python "$ROOT/processing/extract_content.py" "$RUN_DIR"
fi
