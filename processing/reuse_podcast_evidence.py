#!/usr/bin/env python3
"""PS04: Reuse verified podcast transcripts matched to fresh RSS enclosure candidates.

No audio downloads and no transcription/API calls. The current podcast collector
supplies candidate metadata; the approved editorial corpus supplies transcript
files and stable content hashes. A podcast is reused only with strong identity
agreement, and the match is documented separately for audit.

Usage:
    python processing/reuse_podcast_evidence.py RUN_DIR CANDIDATES_JSONL CORPUS_JSONL

Output: normalized podcast evidence items on stdout (JSONL); receipts and
unmatched candidates in RUN_DIR, diagnostics on stderr.
"""
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


def fail(message):
    raise SystemExit("PS04 PODCAST REUSE ERROR: " + message)


def read_jsonl(path):
    if not path.is_file():
        fail("missing " + str(path))
    items = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            fail(f"invalid JSON at {path}:{line_number}: {exc}")
    return items


def as_date(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def canonical_title(value):
    return " ".join(str(value or "").casefold().split())


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_archived(item):
    if item.get("kind") != "podcast":
        return False
    for field in ("item_id", "title", "publisher_id", "published_at", "media_url",
                  "text_path", "segments_path", "version_id"):
        if not item.get(field):
            fail("archived podcast lacks " + field + ": " + str(item.get("title")))
    text_file = Path(item["text_path"])
    segments_file = Path(item["segments_path"])
    if not text_file.is_file() or not segments_file.is_file():
        fail("missing archived transcript or segments: " + item["item_id"])
    if file_sha256(text_file) != item["version_id"]:
        fail("SHA-256 mismatch: " + item["item_id"])
    if segments_file.stat().st_size == 0:
        fail("empty segments: " + item["item_id"])
    try:
        json.loads(segments_file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        fail("invalid segments JSON: " + item["item_id"])
    return True


def main():
    if len(sys.argv) != 4:
        fail("usage: reuse_podcast_evidence.py RUN_DIR CANDIDATES_JSONL CORPUS_JSONL")
    run_dir = Path(sys.argv[1])
    candidate_file = Path(sys.argv[2])
    catalog_file = Path(sys.argv[3])

    manifest_file = run_dir / "run.json"
    if not manifest_file.is_file():
        fail("missing " + str(manifest_file))
    run = json.loads(manifest_file.read_text(encoding="utf-8"))
    try:
        as_of = date.fromisoformat(run["as_of_date"])
    except (ValueError, KeyError):
        fail("invalid or missing as_of_date in run.json")
    first_date = as_of - timedelta(days=29)

    catalog = read_jsonl(catalog_file)
    candidates = read_jsonl(candidate_file)
    archived = {}
    for item in catalog:
        if item.get("kind") == "podcast":
            check_archived(item)
            media_url = item["media_url"]
            if media_url in archived:
                fail("duplicate archived media URL; cannot safely identify episode")
            archived[media_url] = item

    if not archived:
        fail("no verified podcasts found in archival corpus")

    matched = []
    receipts = []
    pending = []
    seen_ids = set()
    for candidate in candidates:
        if candidate.get("kind") != "podcast":
            continue
        media_url = candidate.get("media_url")
        item = archived.get(media_url)
        reason = None
        if not item:
            reason = "media_enclosure_not_in_verified_archive"
        elif item["item_id"] in seen_ids:
            reason = "duplicate_episode_candidate"
        elif (candidate.get("publisher_id") and
              candidate["publisher_id"] != item["publisher_id"]):
            reason = "publisher_mismatch"
        elif canonical_title(candidate.get("title")) != canonical_title(item["title"]):
            reason = "episode_title_mismatch"
        elif as_date(candidate.get("published_at")) != as_date(item["published_at"]):
            reason = "publication_date_mismatch"
        elif not (first_date <= as_date(item["published_at"]) <= as_of):
            reason = "episode_outside_run_window"

        if reason:
            pending.append({
                "title": candidate.get("title"),
                "publisher_id": candidate.get("publisher_id"),
                "published_at": candidate.get("published_at"),
                "reason": reason,
                "transcription_performed": False,
            })
            continue

        seen_ids.add(item["item_id"])
        matched.append(item)
        receipts.append({
            "item_id": item["item_id"],
            "version_id": item["version_id"],
            "publisher_id": item["publisher_id"],
            "title": item["title"],
            "match_method": "exact_rss_audio_enclosure_url_plus_title_date",
            "rss_candidate_source_id": candidate.get("source_id"),
            "rss_candidate_guid": candidate.get("guid"),
            "rss_candidate_url": candidate.get("url"),
            "media_url": media_url,
            "transcript_sha256": file_sha256(Path(item["text_path"])),
            "segments_sha256": file_sha256(Path(item["segments_path"])),
            "audio_download_performed": False,
            "transcription_performed": False,
        })

    run_dir.mkdir(parents=True, exist_ok=True)
    receipt_file = run_dir / "podcast_match_receipts.jsonl"
    pending_file = run_dir / "podcast_unmatched.jsonl"
    for path, records in ((receipt_file, receipts), (pending_file, pending)):
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=True) + "\n")

    required = int(os.environ.get("PS04_PODCAST_MIN_MATCHES", "2"))
    print("PODCAST RSS CANDIDATES:", sum(c.get("kind") == "podcast" for c in candidates), file=sys.stderr)
    print("MATCHED VERIFIED TRANSCRIPTS:", len(matched), file=sys.stderr)
    print("UNMATCHED CANDIDATES:", len(pending), file=sys.stderr)
    if len(matched) < required:
        fail(f"only {len(matched)} verifiable matches; required {required}. "
             f"See {pending_file}; no transcripts were invented.")

    for item in matched:
        print(json.dumps(item, ensure_ascii=True))
    print("PODCAST ARCHIVAL REUSE: PASS", file=sys.stderr)


if __name__ == "__main__":
    main()
