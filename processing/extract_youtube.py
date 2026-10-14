#!/usr/bin/env python3
"""PS04: Extract timed YouTube evidence from a candidate."""

import sys
import json
import hashlib
import subprocess
import tempfile
from pathlib import Path

try:
    from .normalize_vtt import normalize
except ImportError:
    from normalize_vtt import normalize


def extract_youtube(candidate, run_dir):
    video_id = candidate["item_id"].split(":", 1)[1]

    if not video_id or candidate["kind"] != "youtube":
        raise ValueError("Invalid YouTube candidate")

    run_dir = Path(run_dir)
    asset_base = run_dir / 'assets'
    if json.loads((run_dir/'run.json').read_text(encoding='utf-8')).get('contract_version') == 2:
        from pipeline_common import ROOT
        asset_base = ROOT/'data/assets/contract_v2'/run_dir.name/'captions'
    vtt_dir = asset_base / "vtt"
    text_dir = asset_base / "text"
    segment_dir = asset_base / "segments"

    for directory in (vtt_dir, text_dir, segment_dir):
        directory.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as temporary:
        pattern = str(Path(temporary) / "%(id)s.%(ext)s")

        command = [
            sys.executable, "-m", "yt_dlp",
            "--js-runtimes", "node",
            "--skip-download",
            "--write-auto-subs",
            "--write-subs",
            "--sub-langs", "en.*",
            "--sub-format", "vtt",
            "--no-playlist",
            "-o", pattern,
            candidate["url"]
        ]

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL
        )

        files = list(Path(temporary).glob(f"{video_id}*.vtt"))

        if not files:
            raise ValueError("No English VTT subtitles available")

        # Prefer original English captions when available.
        files.sort(
            key=lambda p: (
                0 if ".en-orig." in p.name else
                1 if ".en." in p.name else 2,
                p.name
            )
        )

        raw = files[0].read_text(encoding="utf-8-sig")

        # Retain the original VTT for audit.
        vtt_path = vtt_dir / f"{video_id}.vtt"
        vtt_path.write_bytes(raw.encode("utf-8"))

    segments = normalize(raw)

    if not segments:
        raise ValueError("No valid speech segments found")

    transcript = "\n".join(s["text"] for s in segments)
    text_bytes = transcript.encode("utf-8")

    version_id = hashlib.sha256(text_bytes).hexdigest()

    safe_id = hashlib.sha256(
        candidate["item_id"].encode("utf-8")
    ).hexdigest()[:20]

    text_path = text_dir / f"{safe_id}_{version_id}.txt"
    segments_path = (
        segment_dir / f"{safe_id}_{version_id}.json"
    )

    if text_path.exists():
        if hashlib.sha256(text_path.read_bytes()).hexdigest() != version_id:
            raise ValueError("Existing transcript integrity failure")
    else:
        text_path.write_bytes(text_bytes)

    encoded_segments = json.dumps(
        segments, indent=2, ensure_ascii=False
    ).encode("utf-8")

    if segments_path.exists():
        if segments_path.read_bytes() != encoded_segments:
            raise ValueError("Existing segments differ")
    else:
        segments_path.write_bytes(encoded_segments)

    return {
        **candidate,
        "version_id": version_id,
        "text_path": text_path.as_posix(),
        "segments_path": segments_path.as_posix()
    }
