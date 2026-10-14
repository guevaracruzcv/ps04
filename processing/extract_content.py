#!/usr/bin/env python3
"""
PS04 - Content Extraction
Input: Candidate JSONL through stdin
Output: Normalized Item JSONL through stdout

Current implementation:
- MIT News article extraction
- UTF-8 canonical bytes
- SHA-256 content versioning
- Extraction receipts
"""

import sys
import json
import hashlib
import uuid
import urllib.request

from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timezone

try:
    from .extract_youtube import extract_youtube
except ImportError:
    from extract_youtube import extract_youtube


# --------------------------------------------------
# 1. HTML EXTRACTION CONFIGURATION
# --------------------------------------------------

TARGET = "news-article--content--body--inner"

VOID_TAGS = {
    "area", "base", "br", "col", "embed",
    "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr"
}


# --------------------------------------------------
# 2. ARTICLE BODY PARSER
# --------------------------------------------------

class ArticleBodyParser(HTMLParser):

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.target_depth = None
        self.parts = []
        self.found = False

    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()

        if self.target_depth is None and TARGET in classes:
            self.target_depth = len(self.stack)
            self.found = True

        if self.target_depth is not None:
            if tag in ("p", "h1", "h2", "h3", "li", "br"):
                self.parts.append("\n")

        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                if current == tag:
                    break

        if (
            self.target_depth is not None
            and len(self.stack) <= self.target_depth
        ):
            self.target_depth = None

    def handle_data(self, data):
        if self.target_depth is not None:
            if not any(
                tag in self.stack
                for tag in ("script", "style", "noscript")
            ):
                value = " ".join(data.split())
                if value:
                    self.parts.append(value + " ")


# --------------------------------------------------
# 3. EXTRACT ARTICLE TEXT
# --------------------------------------------------

def extract_article_body(html):
    parser = ArticleBodyParser()
    parser.feed(html)

    if not parser.found:
        raise ValueError(
            "MIT article body selector not found"
        )

    text = "\n".join(
        line.strip()
        for line in "".join(parser.parts).splitlines()
        if line.strip()
    )

    if len(text) < 200:
        raise ValueError("Insufficient article text")

    return text


# --------------------------------------------------
# 4. MAIN EXTRACTION PIPELINE
# --------------------------------------------------

def main():

    if len(sys.argv) != 2:
        print(
            "Usage: extract_content.py RUN_DIR",
            file=sys.stderr
        )
        return 2

    run_dir = Path(sys.argv[1])

    if not (run_dir / "run.json").is_file():
        print(
            "ERROR: run.json not found",
            file=sys.stderr
        )
        return 2

    assets = run_dir / "assets" / "text"
    logs = run_dir / "logs"

    assets.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    started = datetime.now(timezone.utc)

    input_count = 0
    output_count = 0
    errors = []

    for line_number, line in enumerate(sys.stdin, 1):

        if not line.strip():
            continue

        input_count += 1
        candidate = None

        try:
            candidate = json.loads(line)

            if candidate["kind"] == "youtube":
                item = extract_youtube(candidate, run_dir)
                print(json.dumps(item, ensure_ascii=True), flush=True)
                output_count += 1
                continue

            if candidate["kind"] != "feed":
                raise ValueError(
                    "Media extraction not implemented for "
                    + str(candidate["kind"])
                )

            url = candidate["url"]

            if not url.startswith(("https://", "http://")):
                raise ValueError("Invalid HTTP URL")

            # Current selector is specific to MIT News.
            if not url.startswith("https://news.mit.edu/"):
                raise ValueError(
                    "Article extractor not configured for this source"
                )

            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 PS04 Research"
                }
            )

            with urllib.request.urlopen(
                request, timeout=30
            ) as response:
                content = response.read()
                charset = (
                    response.headers.get_content_charset()
                    or "utf-8"
                )

            html = content.decode(
                charset, errors="replace"
            )

            text = extract_article_body(html)

            # Canonical UTF-8 bytes.
            content_bytes = text.encode("utf-8")

            # Stable content-based version.
            version_id = hashlib.sha256(
                content_bytes
            ).hexdigest()

            safe_id = hashlib.sha256(
                candidate["item_id"].encode("utf-8")
            ).hexdigest()[:20]

            text_path = assets / (
                f"{safe_id}_{version_id}.txt"
            )

            # Write exactly the bytes used for hashing.
            if not text_path.exists():
                text_path.write_bytes(content_bytes)
            else:
                existing_hash = hashlib.sha256(
                    text_path.read_bytes()
                ).hexdigest()

                if existing_hash != version_id:
                    raise ValueError(
                        "Existing evidence file failed "
                        "byte-integrity verification"
                    )

            # Final integrity verification.
            saved_hash = hashlib.sha256(
                text_path.read_bytes()
            ).hexdigest()

            if saved_hash != version_id:
                raise ValueError(
                    "SHA-256 integrity verification failed"
                )

            item = {
                **candidate,
                "version_id": version_id,
                "text_path": text_path.as_posix(),
                "segments_path": None
            }

            print(
                json.dumps(item, ensure_ascii=True),
                flush=True
            )

            output_count += 1

        except Exception as exc:
            errors.append({
                "line_number": line_number,
                "item_id": (
                    candidate.get("item_id")
                    if isinstance(candidate, dict)
                    else None
                ),
                "error": str(exc)
            })

            print(
                f"Extraction error on line "
                f"{line_number}: {exc}",
                file=sys.stderr
            )

    finished = datetime.now(timezone.utc)

    receipt = {
        "stage": "extract_content",
        "status": (
            "success" if not errors else "partial"
        ),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "input_count": input_count,
        "output_count": output_count,
        "tool": "Python standard library",
        "cost_usd": 0,
        "errors": errors
    }

    receipt_path = logs / (
        f"extract_{uuid.uuid4().hex}.json"
    )

    receipt_path.write_text(
        json.dumps(receipt, indent=2),
        encoding="utf-8"
    )

    print(
        f"Extraction completed: "
        f"{output_count}/{input_count} items",
        file=sys.stderr
    )

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
