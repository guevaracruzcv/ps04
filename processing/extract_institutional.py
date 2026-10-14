#!/usr/bin/env python3
"""PS04: Extract institutional article text."""

import json
import hashlib
import sys
import urllib.request
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timezone


class BodyParser(HTMLParser):
    def __init__(self, publisher):
        super().__init__(convert_charrefs=True)
        self.publisher = publisher
        self.depth = 0
        self.skip = 0
        self.parts = []

    def matches(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()

        if self.publisher == "harvard":
            return tag == "div" and "entry-content" in classes

        if self.publisher == "mit-sloan":
            return tag == "article" and "article" in classes

        if self.publisher == "world-bank":
            return tag == "div" and "cmp-text" in classes

        return False

    def handle_starttag(self, tag, attrs):
        if self.depth:
            self.depth += 1
        elif self.matches(tag, attrs):
            self.depth = 1

        if self.depth and tag in (
            "script", "style", "nav", "footer", "aside"
        ):
            self.skip += 1

    def handle_endtag(self, tag):
        if self.depth:
            self.depth -= 1

        if self.skip and tag in (
            "script", "style", "nav", "footer", "aside"
        ):
            self.skip -= 1

    def handle_data(self, data):
        if self.depth and not self.skip:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: extract_institutional.py SOURCES.json RUN_DIR"
        )

    sources = json.loads(
        Path(sys.argv[1]).read_text(encoding="utf-8")
    )
    run_dir = Path(sys.argv[2])
    assets = run_dir / "assets" / "institutional"
    assets.mkdir(parents=True, exist_ok=True)

    output = run_dir / "institutional_items.jsonl"

    with output.open("w", encoding="utf-8", newline="\n") as stream:
        for source in sources:
            publisher = source["publisher_id"]

            if publisher not in ("harvard", "mit-sloan", "world-bank"):
                continue

            request = urllib.request.Request(
                source["url"],
                headers={"User-Agent": "Mozilla/5.0"}
            )

            with urllib.request.urlopen(
                request, timeout=30
            ) as response:
                html = response.read().decode(
                    "utf-8", errors="replace"
                )

            parser = BodyParser(publisher)
            parser.feed(html)

            text = "\n".join(parser.parts)
            words = len(text.split())

            if words < 300:
                raise ValueError(
                    f"Insufficient article text: {source['title']}"
                )

            content = text.encode("utf-8")
            version = hashlib.sha256(content).hexdigest()

            item_id = "feed:" + hashlib.sha256(
                source["url"].encode("utf-8")
            ).hexdigest()[:20]

            text_path = assets / f"{item_id.replace(':', '_')}_{version}.txt"
            text_path.write_bytes(content)

            item = {
                "item_id": item_id,
                "source_id": publisher + "-institutional",
                "publisher_id": publisher,
                "kind": "feed",
                "title": source["title"],
                "url": source["url"],
                "published_at": source.get("published_at"),
                "retrieved_at": datetime.now(timezone.utc).isoformat()
                    .replace("+00:00", "Z"),
                "media_url": None,
                "version_id": version,
                "text_path": text_path.as_posix(),
                "segments_path": None
            }

            stream.write(json.dumps(item, ensure_ascii=True) + "\n")
            print(
                publisher, "|", words,
                "words |", source["title"]
            )

    print("Institutional extraction: PASS")


if __name__ == "__main__":
    main()
