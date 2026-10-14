#!/usr/bin/env bash
set -euo pipefail

# Required RUN_DIR interface; original config-path/legacy body remains below.
if [[ $# -eq 1 && -d "$1" && -f "$1/run.json" ]] && python -B -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1],encoding="utf-8")).get("contract_version")==2 else 1)' "$1/run.json"; then
    CONTRACT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$CONTRACT_ROOT"
    python -B -m collectors.contracts youtube "$1"
    exit $?
fi

# PS04 - YouTube Collector
# Input: config/sources.json or supplied config path
# Output: Candidate JSONL through stdout

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $# -ne 1 ]]; then
    echo "Usage: bash collectors/fetch_youtube.sh RUN_DIR" >&2
    exit 2
fi

RUN_DIR="$1"

if [[ ! -f "$RUN_DIR/run.json" ]]; then
    echo "ERROR: run.json not found" >&2
    exit 2
fi

if [[ -f "$RUN_DIR/sources.json" ]]; then
    SOURCES="$RUN_DIR/sources.json"
else
    SOURCES="$ROOT/config/sources.json"
fi

python - "$SOURCES" <<'PY'
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

sources = json.loads(
    Path(sys.argv[1]).read_text(encoding="utf-8")
)

for source in sources:

    if source.get("kind") != "youtube":
        continue

    command = [
        sys.executable,
        "-m", "yt_dlp",
        "--js-runtimes", "node",
        "--skip-download",
        "--dump-single-json",
        "--no-playlist",
        source["url"]
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        print(
            "ERROR collecting YouTube source "
            + source["source_id"] + ": "
            + result.stderr[-1000:],
            file=sys.stderr
        )
        sys.exit(1)

    metadata = json.loads(result.stdout)

    video_id = metadata["id"]
    upload_date = metadata.get("upload_date")

    if not upload_date:
        print(
            f"ERROR: Missing upload date for {video_id}",
            file=sys.stderr
        )
        sys.exit(1)

    published = (
        f"{upload_date[:4]}-"
        f"{upload_date[4:6]}-"
        f"{upload_date[6:8]}T00:00:00Z"
    )

    candidate = {
        "item_id": f"youtube:{video_id}",
        "source_id": source["source_id"],
        "publisher_id": source["publisher_id"],
        "kind": "youtube",
        "title": metadata.get("title", ""),
        "url": metadata.get("webpage_url", source["url"]),
        "published_at": published,
        "retrieved_at": datetime.now(
            timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "media_url": metadata.get("webpage_url", source["url"])
    }

    print(json.dumps(candidate, ensure_ascii=True))
PY
