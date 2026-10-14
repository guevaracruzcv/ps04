#!/usr/bin/env bash
set -euo pipefail

# Required RUN_DIR interface; original config-path/legacy body remains below.
if [[ $# -eq 1 && -d "$1" && -f "$1/run.json" ]] && python -B -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1],encoding="utf-8")).get("contract_version")==2 else 1)' "$1/run.json"; then
    CONTRACT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    cd "$CONTRACT_ROOT"
    python -B -m collectors.contracts feed "$1"
    exit $?
fi

# PS04 - RSS feed collector
# Input: config/sources.json
# Output: candidate records in JSONL format (stdout)

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCES="${1:-$ROOT/config/sources.json}"

python - "$SOURCES" <<'PY'
import sys
import json
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
import hashlib
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

sources_path = sys.argv[1]

with open(sources_path, encoding="utf-8") as f:
    sources = json.load(f)

for source in sources:
    if source.get("kind") != "feed":
        continue

    try:
        request = urllib.request.Request(
            source["url"],
            headers={"User-Agent": "PS04-Research-Collector/1.0"}
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        retrieved_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        for entry in root.findall("./channel/item"):
            title = (entry.findtext("title") or "").strip()
            url = (entry.findtext("link") or "").strip()
            pub_date = entry.findtext("pubDate")

            if not title or not url or not pub_date:
                continue

            published = parsedate_to_datetime(pub_date)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)

            published_at = published.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

            unique_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]

            candidate = {
                "item_id": f"feed:{unique_id}",
                "source_id": source["source_id"],
                "publisher_id": source["publisher_id"],
                "kind": "feed",
                "title": title,
                "url": url,
                "published_at": published_at,
                "retrieved_at": retrieved_at,
                "media_url": None
            }

            print(json.dumps(candidate, ensure_ascii=False))

    except Exception as exc:
        print(
            f"ERROR collecting {source.get('source_id')}: {exc}",
            file=sys.stderr
        )
        sys.exit(1)
PY
