#!/usr/bin/env python3
"""PS04 - Transcribe a podcast with timestamped evidence."""

import sys
import json
from pathlib import Path
from openai import OpenAI

def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python processing/transcribe_podcast.py AUDIO.mp3 OUTPUT_DIR"
        )

    audio = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    text_path = output_dir / "transcript.txt"
    segments_path = output_dir / "segments.json"
    raw_path = output_dir / "transcription_raw.json"

    if any(p.exists() for p in (text_path, segments_path, raw_path)):
        raise SystemExit(
            "Output already exists. Refusing to repeat a paid transcription."
        )

    if audio.stat().st_size > 25 * 1024 * 1024:
        raise SystemExit("Audio exceeds the 25 MB API upload limit.")

    client = OpenAI()

    print("Submitting podcast for transcription...", flush=True)

    with audio.open("rb") as file:
        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=file,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
            language="en"
        )

    # Keep the complete response for the evidence audit.
    raw_path.write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
        newline="\n"
    )

    segments = []

    for index, segment in enumerate(result.segments or [], 1):
        text = segment.text.strip()

        if not text:
            continue

        segments.append({
            "segment_id": f"seg-{index:05d}",
            "start_seconds": float(segment.start),
            "end_seconds": float(segment.end),
            "text": text
        })

    if not segments:
        raise ValueError("API returned no timestamped segments")

    transcript = "\n".join(s["text"] for s in segments)

    text_path.write_bytes(transcript.encode("utf-8"))

    segments_path.write_text(
        json.dumps(segments, indent=2, ensure_ascii=False),
        encoding="utf-8",
        newline="\n"
    )

    print("Segments:", len(segments))
    print("Words:", len(transcript.split()))
    print("Transcript:", text_path)
    print("Timestamps:", segments_path)
    print("Podcast transcription: PASS")

if __name__ == "__main__":
    main()
