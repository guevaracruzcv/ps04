#!/usr/bin/env bash
set -euo pipefail

# Required RUN_DIR interface; original config-path/legacy body remains below.
if [[ $# -eq 1 && -d "$1" && -f "$1/run.json" ]] && python -B -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1],encoding="utf-8")).get("contract_version")==2 else 1)' "$1/run.json"; then
    CONTRACT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$CONTRACT_ROOT"
    python -B -m collectors.contracts podcast "$1"
    exit $?
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: bash collectors/fetch_podcasts.sh RUN_DIR" >&2
    exit 2
fi

RUN_DIR="$1"

if [[ ! -f "$RUN_DIR/run.json" ]]; then
    echo "ERROR: run.json not found" >&2
    exit 2
fi

if [[ -n "${PS04_PODCAST_SOURCES:-}" ]]; then
    SOURCES="$PS04_PODCAST_SOURCES"
elif [[ -f "$RUN_DIR/sources.json" ]]; then
    SOURCES="$RUN_DIR/sources.json"
else
    SOURCES="config/sources.json"
fi

python - "$RUN_DIR" "$SOURCES" <<'PY'
import sys
import json
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

run_dir = Path(sys.argv[1])
sources_path = Path(sys.argv[2])

run = json.loads(
    (run_dir / "run.json").read_text(encoding="utf-8")
)
sources = json.loads(
    sources_path.read_text(encoding="utf-8")
)

as_of = datetime.strptime(
    run["as_of_date"], "%Y-%m-%d"
).date()
first_date = as_of - timedelta(days=29)

for source in sources:
    if source["kind"] != "podcast":
        continue

    request = urllib.request.Request(
        source["url"],
        headers={"User-Agent": "Mozilla/5.0 PS04 Research"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())

    for episode in root.findall(".//channel/item"):
        title = episode.findtext("title", "").strip()
        link = episode.findtext("link", "").strip()
        guid = episode.findtext("guid", "").strip()
        pub_date = episode.findtext("pubDate", "").strip()
        enclosure = episode.find("enclosure")

        if not title or not pub_date or enclosure is None:
            continue

        audio_url = enclosure.get("url", "")
        if not audio_url:
            continue

        published = parsedate_to_datetime(pub_date)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        published = published.astimezone(timezone.utc)

        if not first_date <= published.date() <= as_of:
            continue

        identity = guid or link or audio_url
        stable_id = hashlib.sha256(
            (source["source_id"] + ":" + identity)
            .encode("utf-8")
        ).hexdigest()[:20]

        candidate = {
            "item_id": "podcast:" + stable_id,
            "source_id": source["source_id"],
            "publisher_id": source["publisher_id"],
            "kind": "podcast",
            "title": title,
            "url": link or audio_url,
            "published_at": published.isoformat()
                .replace("+00:00", "Z"),
            "retrieved_at": datetime.now(timezone.utc)
                .isoformat().replace("+00:00", "Z"),
            "media_url": audio_url
        }

        print(json.dumps(candidate, ensure_ascii=True))
PY
