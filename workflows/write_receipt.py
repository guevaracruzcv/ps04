#!/usr/bin/env python3
"""PS04 - Consolidated collection workflow receipt."""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone


def count_jsonl(path):
    if not path.is_file():
        return None

    return sum(
        1 for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: write_receipt.py RUN_DIR EXIT_CODE"
        )

    run_dir = Path(sys.argv[1])
    exit_code = int(sys.argv[2])

    run = json.loads(
        (run_dir / "run.json").read_text(
            encoding="utf-8"
        )
    )

    candidates = count_jsonl(run_dir / "candidates.jsonl")
    extracted = count_jsonl(run_dir / "items.jsonl")
    changes = count_jsonl(run_dir / "changes.jsonl")
    eligible = count_jsonl(run_dir / "eligible.jsonl")

    # The workflow may have multiple extraction attempts.
    # For now, use the most recently modified extraction receipt.
    receipts = list(
        (run_dir / "logs").glob("extract_*.json")
    )

    extraction_errors = []

    if receipts:
        latest = max(
            receipts,
            key=lambda path: path.stat().st_mtime_ns
        )

        data = json.loads(
            latest.read_text(encoding="utf-8")
        )

        extraction_errors = data.get("errors", [])

    status = {
        0: "success",
        1: "partial",
        2: "failure"
    }.get(exit_code, "failure")

    receipt = {
        "run_id": run["run_id"],
        "as_of_date": run["as_of_date"],
        "status": status,
        "finished_at": datetime.now(
            timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "counts": {
            "candidates": candidates,
            "extracted": extracted,
            "changes": changes,
            "eligible": eligible,
            "extraction_errors": len(extraction_errors)
        },
        "errors": extraction_errors,
        "exit_code": exit_code
    }

    destination = run_dir / "logs" / "workflow_receipt.json"
    destination.parent.mkdir(parents=True, exist_ok=True)

    destination.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("Workflow receipt:", destination)
    print("Workflow status:", status)


if __name__ == "__main__":
    main()
