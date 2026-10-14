#!/usr/bin/env python3
"""PS04 SQLite Evidence Store with persistent evidence assets."""

import sys
import os
import json
import sqlite3
import hashlib
import tempfile
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CONTRACT_FOLDER = None
if os.environ.get('PS04_RUN_DIR'):
    candidate = (ROOT/os.environ['PS04_RUN_DIR']).resolve()
    if json.loads((candidate/'run.json').read_text(encoding='utf-8')).get('contract_version') == 2:
        CONTRACT_FOLDER = candidate

DB_PATH = Path(
    os.environ.get(
        "PS04_EVIDENCE_DB",
        str(ROOT / "data/evidence/evidence.db")
    )
).resolve()

ASSETS = DB_PATH.parent / "assets"
if CONTRACT_FOLDER is not None:
    run = json.loads((CONTRACT_FOLDER/'run.json').read_text(encoding='utf-8'))
    DB_PATH = (ROOT/run['evidence_db']).resolve()
    if not DB_PATH.is_relative_to(ROOT/'data/evidence/contract_v2'):
        raise ValueError('Prospective store cannot modify a historical database')
    ASSETS = ROOT/'data/assets/contract_v2/stored'/hashlib.sha256(str(DB_PATH.relative_to(ROOT)).encode()).hexdigest()[:16]


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_store():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            publisher_id TEXT NOT NULL,
            kind TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS versions (
            item_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            content_json TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY (item_id, version_id),
            FOREIGN KEY (item_id) REFERENCES items(item_id)
        );

        CREATE TABLE IF NOT EXISTS observations (
            run_id TEXT NOT NULL,
            item_id TEXT NOT NULL,
            version_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (run_id, item_id, version_id),
            FOREIGN KEY (item_id, version_id)
                REFERENCES versions(item_id, version_id)
        );
        """)


def resolve_source(value):
    """Resolve an input path without changing its contents."""
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def preserve_file(source_value, destination, expected_hash=None):
    """Copy a verified asset without overwriting incompatible evidence."""
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.is_file():
        existing = destination.read_bytes()
        if expected_hash and sha256(existing) != expected_hash:
            raise ValueError(
                f"Persistent asset integrity failure: {destination}"
            )
        return destination.relative_to(ROOT).as_posix() if CONTRACT_FOLDER else str(destination)

    source = resolve_source(source_value)

    if not source.is_file():
        raise FileNotFoundError(f"Evidence file not found: {source}")

    data = source.read_bytes()

    if expected_hash and sha256(data) != expected_hash:
        raise ValueError(
            f"Source asset SHA-256 mismatch: {source}"
        )

    # Create a temporary file alongside its permanent destination.
    fd, temporary_name = tempfile.mkstemp(
        prefix=".evidence-",
        dir=str(destination.parent)
    )

    try:
        with os.fdopen(fd, "wb") as temporary:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())

        # Never replace an incompatible existing destination.
        if destination.exists():
            if destination.read_bytes() != data:
                raise ValueError(
                    f"Conflicting persistent asset: {destination}"
                )
        else:
            os.replace(temporary_name, destination)
            temporary_name = None
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)

    if sha256(destination.read_bytes()) != sha256(data):
        raise ValueError("Asset copy verification failed")

    return destination.relative_to(ROOT).as_posix() if CONTRACT_FOLDER else str(destination)


def preserve_evidence(item, previous=None):
    """Return item metadata pointing to preserved evidence files."""
    result = dict(item)
    item_id = item["item_id"]
    version_id = item["version_id"]

    safe_id = hashlib.sha256(
        item_id.encode("utf-8")
    ).hexdigest()[:20]

    previous = previous or {}

    text_source = item.get("text_path") or previous.get("text_path")

    if text_source:
        destination = (
            ASSETS / "text" / safe_id / f"{version_id}.txt"
        )

        result["text_path"] = preserve_file(
            text_source,
            destination,
            expected_hash=item.get('text_sha256') or version_id
        )

    segments_source = (
        item.get("segments_path")
        or previous.get("segments_path")
    )

    if segments_source:
        source = resolve_source(segments_source)

        if not source.is_file():
            old_source = previous.get("segments_path")
            if old_source:
                source = resolve_source(old_source)

        if not source.is_file():
            raise FileNotFoundError(
                f"Segments file not found: {segments_source}"
            )

        segments_hash = sha256(source.read_bytes())

        destination = (
            ASSETS / "segments" / safe_id /
            (f"{segments_hash}{source.suffix}" if CONTRACT_FOLDER else f"{version_id}_{segments_hash}{source.suffix}")
        )

        result["segments_path"] = preserve_file(
            str(source),
            destination,
            expected_hash=segments_hash
        )

    return result


def upsert(run_dir):
    run_path = Path(run_dir) / "run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run_id = run["run_id"]

    if not run_id:
        raise ValueError("run_id cannot be empty")

    records = [
        json.loads(line.decode("utf-8", errors="strict"))
        for line in sys.stdin.buffer
        if line.strip()
    ]

    init_store()
    changes = []

    with connect() as db:
        for item in records:
            if CONTRACT_FOLDER:
                from processing.evidence_contract import verify_version, verify_legacy_metadata
                verify_version(item, resolve_source(item['text_path']).read_bytes())
                verify_legacy_metadata(item, CONTRACT_FOLDER)
            item_id = item["item_id"]
            version_id = item["version_id"]

            existing = db.execute(
                "SELECT item_id FROM items WHERE item_id = ?",
                (item_id,)
            ).fetchone()

            version_row = db.execute(
                """SELECT content_json FROM versions
                   WHERE item_id = ? AND version_id = ?""",
                (item_id, version_id)
            ).fetchone()

            previous = (
                json.loads(version_row[0])
                if version_row else None
            )
            if CONTRACT_FOLDER and previous:
                for key in ['title','published_at','url','media_url','segments_sha256','source_media_sha256']:
                    if previous.get(key) != item.get(key):
                        raise ValueError('Evidence-relevant metadata changed without a new version: '+key)

            # Preserve evidence before committing its metadata.
            stored_item = preserve_evidence(item, previous)

            if existing is None:
                db.execute(
                    """INSERT INTO items
                       (item_id, source_id, publisher_id, kind)
                       VALUES (?, ?, ?, ?)""",
                    (
                        item_id,
                        item["source_id"],
                        item["publisher_id"],
                        item["kind"]
                    )
                )
                change = "new"
            else:
                change = "unchanged"

            now = datetime.now(timezone.utc).isoformat()
            content_json = json.dumps(
                stored_item, ensure_ascii=True
            )

            if version_row is None:
                db.execute(
                    """INSERT INTO versions
                       (item_id, version_id, content_json, first_seen_at)
                       VALUES (?, ?, ?, ?)""",
                    (item_id, version_id, content_json, now)
                )

                if change != "new":
                    change = "changed"

            else:
                # An existing version can acquire a permanent path
                # without becoming a new content version.
                migrated = dict(previous)

                for field in ("text_path", "segments_path"):
                    if stored_item.get(field):
                        migrated[field] = stored_item[field]

                if migrated != previous:
                    db.execute(
                        """UPDATE versions SET content_json = ?
                           WHERE item_id = ? AND version_id = ?""",
                        (
                            json.dumps(migrated, ensure_ascii=True),
                            item_id,
                            version_id
                        )
                    )

            db.execute(
                """INSERT OR IGNORE INTO observations
                   (run_id, item_id, version_id, observed_at)
                   VALUES (?, ?, ?, ?)""",
                (run_id, item_id, version_id, now)
            )

            changes.append({
                "item_id": item_id,
                "version_id": version_id,
                "change": change
            })

    for change in changes:
        print(json.dumps(change, ensure_ascii=True))


def list_items():
    init_store()

    with connect() as db:
        rows = db.execute("""
            SELECT v.content_json
            FROM versions v
            WHERE v.rowid = (
                SELECT MAX(v2.rowid)
                FROM versions v2
                WHERE v2.item_id = v.item_id
            )
            ORDER BY v.item_id
        """).fetchall()

    for (content,) in rows:
        print(content)


def get_item(item_id, version_id=None):
    init_store()

    with connect() as db:
        if version_id:
            row = db.execute(
                """SELECT content_json FROM versions
                   WHERE item_id = ? AND version_id = ?""",
                (item_id, version_id)
            ).fetchone()
        else:
            row = db.execute(
                """SELECT content_json FROM versions
                   WHERE item_id = ?
                   ORDER BY rowid DESC LIMIT 1""",
                (item_id,)
            ).fetchone()

    if row is None:
        print("ERROR: Evidence item not found", file=sys.stderr)
        return 1

    print(row[0])
    return 0


def main():
    if len(sys.argv) < 2:
        raise ValueError("Usage: store.sh init|upsert|list|get")

    command = sys.argv[1]

    if command == "init":
        if len(sys.argv)!=2:raise ValueError('Usage: store.sh init')
        init_store()

    elif command == "upsert":
        if len(sys.argv) != 3:
            raise ValueError("Usage: store.sh upsert RUN_DIR")
        upsert(sys.argv[2])

    elif command == "list":
        if len(sys.argv)!=2:raise ValueError('Usage: store.sh list')
        list_items()

    elif command == "get":
        if len(sys.argv) not in (3, 4):
            raise ValueError(
                "Usage: store.sh get ITEM_ID [VERSION_ID]"
            )
        return get_item(
            sys.argv[2],
            sys.argv[3] if len(sys.argv) == 4 else None
        )

    else:
        raise ValueError("Unknown command: " + command)

    return 0


def contract_main():
    """Store-owned receipt boundary; no other component accesses SQLite."""
    from pipeline_common import receipt, utc
    import contextlib
    import io
    started=utc();output=io.StringIO();code=0;errors=[]
    try:
        from pipeline_common import policy
        policy(CONTRACT_FOLDER)
        with contextlib.redirect_stdout(output):code=main()
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        code=2;errors=[str(exc)]
    text=output.getvalue()
    receipt(CONTRACT_FOLDER,'store_'+(sys.argv[1] if len(sys.argv)>1 else 'unknown'),started,'success' if code==0 else 'failure',
            None,len(text.splitlines()),errors,dict(cost_usd=0,tool='SQLite',evidence_db=DB_PATH.relative_to(ROOT).as_posix()))
    sys.stdout.write(text)
    for error in errors:print('ERROR: '+error,file=sys.stderr)
    return code


if __name__ == "__main__":
    try:
        sys.exit(contract_main() if CONTRACT_FOLDER else main())
    except (
        ValueError, KeyError, OSError, sqlite3.Error
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
