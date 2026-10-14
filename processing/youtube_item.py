#!/usr/bin/env python3
"""PS04 - Create a normalized YouTube evidence item."""

import sys
import json
import hashlib
from pathlib import Path


def main():
    if len(sys.argv) != 5:
        raise SystemExit(
            "Usage: youtube_item.py CANDIDATE.jsonl "
            "TRANSCRIPT.txt SEGMENTS.json OUTPUT.jsonl"
        )

    candidate_path = Path(sys.argv[1])
    text_path = Path(sys.argv[2])
    segments_path = Path(sys.argv[3])
    output_path = Path(sys.argv[4])

    candidates = [
        json.loads(line)
        for line in candidate_path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if len(candidates) != 1:
        raise ValueError("Expected exactly one candidate")

    candidate = candidates[0]

    if candidate["kind"] != "youtube":
        raise ValueError("Candidate is not YouTube")

    content = text_path.read_bytes()

    segments = json.loads(
        segments_path.read_text(encoding="utf-8")
    )

    if not segments:
        raise ValueError("Transcript has no segments")

    # This version identifies the extracted transcript.
    version_id = hashlib.sha256(content).hexdigest()

    item = {
        **candidate,
        "version_id": version_id,
        "text_path": text_path.as_posix(),
        "segments_path": segments_path.as_posix()
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(
        (json.dumps(item, ensure_ascii=True) + "\n")
        .encode("utf-8")
    )

    print("YouTube item:", item["item_id"])
    print("Segments:", len(segments))
    print("Version:", version_id[:16])
    print("YouTube item preparation: PASS")


if __name__ == "__main__":
    main()
