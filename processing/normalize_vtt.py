#!/usr/bin/env python3
"""PS04: Convert WebVTT captions to transcript and timed segments."""

import sys
import re
import json
import html
from pathlib import Path

TIMESTAMP = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3})"
    r"\s+-->\s+"
    r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3})"
)


def seconds(value):
    hours, minutes, rest = value.split(":")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + float(rest)
    )


def normalize(vtt_text):
    segments = []
    previous_text = None

    blocks = re.split(r"\n\s*\n", vtt_text)

    for block in blocks:
        lines = block.strip().splitlines()

        if not lines:
            continue

        timestamp_index = next(
            (
                index for index, line in enumerate(lines)
                if TIMESTAMP.search(line)
            ),
            None
        )

        if timestamp_index is None:
            continue

        match = TIMESTAMP.search(lines[timestamp_index])

        text = " ".join(lines[timestamp_index + 1:])
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = " ".join(text.split()).strip()

        if not text or text.lower() in {
            "[music]", "[applause]", "[laughter]"
        }:
            continue

        if text == previous_text:
            continue

        start = seconds(match.group("start"))
        end = seconds(match.group("end"))

        if end <= start:
            continue

        segments.append({
            "segment_id": f"seg-{len(segments) + 1:05d}",
            "start_seconds": start,
            "end_seconds": end,
            "text": text
        })

        previous_text = text

    return segments


def main():
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: normalize_vtt.py INPUT.vtt OUTPUT.txt OUTPUT.json"
        )

    input_path = Path(sys.argv[1])
    text_path = Path(sys.argv[2])
    segments_path = Path(sys.argv[3])

    raw = input_path.read_text(encoding="utf-8-sig")
    segments = normalize(raw)

    if not segments:
        raise SystemExit("ERROR: No transcript segments found")

    text_path.parent.mkdir(parents=True, exist_ok=True)
    segments_path.parent.mkdir(parents=True, exist_ok=True)

    # LF-only, UTF-8 bytes.
    transcript = "\n".join(
        segment["text"] for segment in segments
    )

    text_path.write_bytes(transcript.encode("utf-8"))

    segments_path.write_text(
        json.dumps(segments, indent=2, ensure_ascii=False),
        encoding="utf-8",
        newline="\n"
    )

    print("Segments:", len(segments))
    print("Transcript words:", len(transcript.split()))
    print("Text:", text_path)
    print("Segments JSON:", segments_path)


if __name__ == "__main__":
    main()
