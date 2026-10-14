#!/usr/bin/env bash
set -euo pipefail

# PS04 - Freshness filter
# Input: Items JSONL through stdin
# Output: Eligible Items JSONL through stdout

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -ne 1 ]]; then
    echo "Usage: bash processing/filter_items.sh RUN_DIR" >&2
    exit 2
fi

RUN_DIR="$1"

if [[ ! -f "$RUN_DIR/run.json" ]]; then
    echo "ERROR: run.json not found" >&2
    exit 2
fi

mkdir -p "$RUN_DIR/logs"

python "$ROOT/processing/filter_items.py" "$RUN_DIR"
