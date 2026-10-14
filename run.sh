#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# New editorial modes use isolated managed runs. Historical collect/replay below
# retain their original implementation and are never called by offline tests.
if [[ $# -eq 0 || "${1:-}" == "--editorial-replay" || "${1:-}" == "--package" ]]; then
    if [[ "${1:-}" == "--package" ]]; then
        if [[ $# -ne 2 ]]; then echo "Usage: bash run.sh --package RUN_DIR" >&2; exit 2; fi
        RUN_DIR="$2"
        python -B -c 'import sys; from pipeline_common import run_folder; run_folder(sys.argv[1])' "$RUN_DIR"
        code=0
        bash review/check_content.sh "$RUN_DIR" | python -B -m workflows.artifacts refresh-review "$RUN_DIR" || code=$?
        if [[ "$code" -eq 0 ]]; then
            bash publishing/prepare_package.sh "$RUN_DIR" >&2 || code=$?
        fi
        bash reporting/summarize_run.sh "$RUN_DIR"
        exit "$code"
    fi
    if [[ "${1:-}" == "--editorial-replay" ]]; then
        if [[ $# -ne 2 ]]; then echo "Usage: bash run.sh --editorial-replay YYYY-MM-DD" >&2; exit 2; fi
        RUN_DIR="$(python -B -m workflows.editorial_run init-offline "$2")"
        python -B -m workflows.offline_replay "$RUN_DIR"
    else
        if RUN_DIR="$(python -B -m workflows.editorial_run init-live)"; then
            :
        else
            code=$?
            python -B -c 'import json; print(json.dumps(dict(run_id=None,status="failed",counts=None,source_coverage=None,failed_stages=["initialize"],incomplete_stages=["collection","series"],errors=["Initialization refused or invalid; see stderr; no pipeline execution recorded"],elapsed_seconds=None,known_cost_usd=None,publication_authorized=False)))'
            exit "$code"
        fi
    fi
    echo "Editorial run: $RUN_DIR" >&2
    code=0
    if [[ $# -eq 0 ]]; then
        PS04_RUN_DIR="$RUN_DIR" PS04_PODCAST_SOURCES="$RUN_DIR/config/podcast_sources.json" bash workflows/collect_sources.sh "$RUN_DIR" >&2 || code=$?
        if [[ "$code" -eq 0 ]]; then python -B -m workflows.editorial_run annotate "$RUN_DIR" || code=$?; fi
    fi
    if [[ "$code" -eq 0 ]]; then bash workflows/create_series.sh "$RUN_DIR" >&2 || code=$?; fi
    bash reporting/summarize_run.sh "$RUN_DIR"
    exit "$code"
fi

if [[ "${1:-}" == "collect" ]]; then
    if [[ $# -ne 2 ]]; then
        echo "Usage: bash run.sh collect YYYY-MM-DD" >&2
        exit 2
    fi

    if [[ -n "${PS04_CANDIDATES_FILE:-}" ]]; then
        echo "ERROR: Live collection cannot use test fixtures" >&2
        exit 2
    fi

    python - "$2" <<'PY_CHECK'
import sys
from datetime import date

try:
    value = date.fromisoformat(sys.argv[1])
    assert value.isoformat() == sys.argv[1]
except (ValueError, AssertionError):
    raise SystemExit("ERROR: Expected YYYY-MM-DD")
PY_CHECK

    RUN_ID="collect-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    RUN_DIR="runs/$RUN_ID"

    mkdir -p "$RUN_DIR"
    cp config/active_sources.json "$RUN_DIR/sources.json"

    python - "$RUN_DIR" "$RUN_ID" "$2" <<'PY_MANIFEST'
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1])
manifest = {
    "run_id": sys.argv[2],
    "as_of_date": sys.argv[3],
    "mode": "live_collection",
    "publication_authorized": False
}

with (folder / "run.json").open(
    "x", encoding="utf-8", newline="\n"
) as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY_MANIFEST

    echo "=== PS04 LIVE COLLECTION ==="
    echo "RUN: $RUN_DIR"

    PS04_EVIDENCE_DB="runs/live_evidence.db" \
      bash workflows/collect_sources.sh "$RUN_DIR"

    echo "LIVE COLLECTION: PASS"
    exit 0
fi

if [[ "${1:-}" != "replay" || $# -ne 2 ]]; then
    echo "Usage: bash run.sh replay YYYY-MM-DD" >&2
    echo "The replay mode is offline; no downloads, API calls, or publication." >&2
    exit 2
fi

python - "$2" <<'PY_REPLAY'
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

root = Path.cwd()
runs = root / "runs"
editorial = runs / "editorial-prep"
policy_path = root / "config/editorial_policy.md"
active_path = root / "config/active_editorial_policy.json"
corpus_path = editorial / "corpus_verified.jsonl"
decisions_path = editorial / "human_decisions_v2.jsonl"
registry_path = runs / "replay_registry.json"


def require(condition, message):
    if not condition:
        raise SystemExit("PS04 ERROR: " + message)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    require(path.is_file(), "missing " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    require(path.is_file(), "missing " + str(path))
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(bool(records), "empty " + str(path))
    return records


def original_file(path_string):
    path = Path(path_string)
    return path if path.is_absolute() else root / path


try:
    as_of = date.fromisoformat(sys.argv[1])
    require(as_of.isoformat() == sys.argv[1], "expected YYYY-MM-DD")
except ValueError:
    raise SystemExit("PS04 ERROR: invalid date; use YYYY-MM-DD")
window_start = as_of - timedelta(days=29)

active = read_json(active_path)
approval = read_json(original_file(active["approval_event"]))
policy_bytes = policy_path.read_bytes()
require(active.get("active_policy_version") == "v2", "V2 is not active")
require(active.get("publication_authorized") is False, "publication must remain blocked")
require(sha256(policy_bytes) == active.get("policy_sha256"), "policy SHA-256 mismatch")
require(approval.get("approval_id") == active.get("approval_id"), "approval ID mismatch")
require(approval.get("publication_authorized") is False, "approval permits publication")

items = read_jsonl(corpus_path)
decisions = read_jsonl(decisions_path)
require(len(items) == 12, "expected 12 evidence items")
require(len(decisions) == 12, "expected 12 human decisions")
item_by_id = {item["item_id"]: item for item in items}
decision_by_id = {item["item_id"]: item for item in decisions}
require(len(item_by_id) == 12, "duplicate evidence item_id")
require(len(decision_by_id) == 12, "duplicate decision item_id")
require(item_by_id.keys() == decision_by_id.keys(), "evidence/decision IDs differ")

kind_counts = Counter(item["kind"] for item in items)
require(kind_counts == {"feed": 8, "podcast": 2, "youtube": 2}, "unexpected format counts")
decision_counts = Counter(d["human_decision"] for d in decisions)
require(decision_counts == {"ACCEPT": 9, "DEFER": 3}, "unexpected V2 decisions")
organizations = {"mit" if x["publisher_id"] == "mit-sloan" else x["publisher_id"] for x in items}
require(len(organizations) >= 6, "fewer than six independent publishers")

content = {}
for item_id, item in item_by_id.items():
    decision = decision_by_id[item_id]
    require(item["version_id"] == decision["version_id"], "decision version mismatch: " + item_id)
    require(decision.get("policy_version") == "v2", "decision policy mismatch: " + item_id)
    require(decision.get("human_review_status") == "confirmed", "unreviewed item: " + item_id)
    require(decision.get("publication_authorized") is False, "publication gate open: " + item_id)
    require(decision.get("v2_approval_id") == approval["approval_id"], "decision approval mismatch: " + item_id)
    published = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00")).date()
    require(window_start <= published <= as_of, "outside 30-day window: " + item_id)
    text_bytes = original_file(item["text_path"]).read_bytes()
    require(sha256(text_bytes) == item["version_id"], "text SHA-256 mismatch: " + item_id)
    segment_bytes = None
    if item["kind"] in ("podcast", "youtube"):
        require(bool(item.get("segments_path")), "missing segment path: " + item_id)
        segment_bytes = original_file(item["segments_path"]).read_bytes()
        require(len(segment_bytes) > 0, "empty segments: " + item_id)
    content[item_id] = (text_bytes, segment_bytes)

runs.mkdir(exist_ok=True)
prior = read_json(registry_path) if registry_path.is_file() else {"items": {}}
prior_versions = prior.get("items", {})
new = sum(item_id not in prior_versions for item_id in item_by_id)
unchanged = sum(prior_versions.get(item_id) == item["version_id"] for item_id, item in item_by_id.items())
updated = len(items) - new - unchanged

now = datetime.now(timezone.utc)
run_id = "replay-" + now.strftime("%Y%m%dT%H%M%S%fZ")
run_dir = runs / run_id
stage = Path(tempfile.mkdtemp(prefix=".replay-incomplete-", dir=runs))

try:
    assets = stage / "assets"
    assets.mkdir()
    (stage / "editorial").mkdir()
    (stage / "editorial/policy_v2.md").write_bytes(policy_bytes)
    (stage / "editorial/human_decisions_v2.jsonl").write_bytes(decisions_path.read_bytes())
    (stage / "editorial/human_approval_v2.json").write_bytes(original_file(active["approval_event"]).read_bytes())

    snapshot = []
    for number, item_id in enumerate(sorted(item_by_id), 1):
        item = dict(item_by_id[item_id])
        stem = f"{number:02d}-{sha256(item_id.encode('utf-8'))[:12]}"
        text_bytes, segment_bytes = content[item_id]
        (assets / (stem + ".txt")).write_bytes(text_bytes)
        item["original_text_path"] = item["text_path"]
        item["text_path"] = "assets/" + stem + ".txt"
        if segment_bytes is not None:
            (assets / (stem + ".segments.json")).write_bytes(segment_bytes)
            item["original_segments_path"] = item["segments_path"]
            item["segments_path"] = "assets/" + stem + ".segments.json"
            item["segments_sha256"] = sha256(segment_bytes)
        item["paths_relative_to"] = "run_directory"
        snapshot.append(item)

    with (stage / "items.jsonl").open("x", encoding="utf-8", newline="\n") as f:
        for item in snapshot:
            f.write(json.dumps(item, ensure_ascii=True) + "\n")

    manifest = {
        "run_id": run_id,
        "mode": "offline_replay",
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
        "as_of_date": as_of.isoformat(),
        "window_start": window_start.isoformat(),
        "window_inclusive_days": 30,
        "verified_items": len(items),
        "formats": dict(kind_counts),
        "independent_organizations": len(organizations),
        "human_decisions": dict(decision_counts),
        "active_policy_version": "v2",
        "approval_id": approval["approval_id"],
        "policy_sha256": sha256(policy_bytes),
        "corpus_sha256": sha256(corpus_path.read_bytes()),
        "human_decisions_sha256": sha256(decisions_path.read_bytes()),
        "replay_registry_new": new,
        "replay_registry_unchanged": unchanged,
        "replay_registry_updated": updated,
        "live_collection_performed": False,
        "api_calls_performed": False,
        "publication_authorized": False,
        "rss_provenance_complete": False,
        "content_paths_relative_to": "run_directory",
    }
    (stage / "run.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    stage.rename(run_dir)
finally:
    if stage.exists():
        shutil.rmtree(stage)

new_registry = {
    "last_run_id": run_id,
    "items": {key: item["version_id"] for key, item in item_by_id.items()},
}
registry_tmp = runs / (".replay_registry-" + run_id + ".tmp")
registry_tmp.write_text(json.dumps(new_registry, indent=2) + "\n", encoding="utf-8", newline="\n")
os.replace(registry_tmp, registry_path)

print("=== PS04 OFFLINE REPLAY ===")
print("RUN:", run_dir.relative_to(root))
print("WINDOW:", window_start, "to", as_of)
print("VERIFIED:", len(items), "|", dict(kind_counts))
print("HUMAN DECISIONS:", dict(decision_counts))
print("NEW TO REPLAY REGISTRY:", new)
print("UNCHANGED VERSIONS:", unchanged)
print("UPDATED VERSIONS:", updated)
print("PUBLICATION: NOT AUTHORIZED")
print("OFFLINE REPLAY: PASS")
PY_REPLAY
