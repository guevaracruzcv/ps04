import sys
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta

if len(sys.argv) != 2:
    print('Usage: filter_items.py RUN_DIR', file=sys.stderr)
    raise SystemExit(2)
run_dir = Path(sys.argv[1])
if not (run_dir/'run.json').is_file():
    print('ERROR: run.json unavailable', file=sys.stderr)
    raise SystemExit(2)
(run_dir/'logs').mkdir(parents=True, exist_ok=True)
started = datetime.now(timezone.utc)

try:
    run = json.loads((run_dir / "run.json").read_text(
        encoding="utf-8"
    ))

    as_of = datetime.strptime(
        run["as_of_date"], "%Y-%m-%d"
    ).date()

    window_start = as_of - timedelta(days=29)
    eligible = []
    exclusions = []

    for line_number, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue

        item = json.loads(line)
        published = item.get("published_at")

        if published is None or published == "":
            reason = "unknown_date"
        else:
            try:
                dt = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                )

                if dt.tzinfo is None:
                    raise ValueError("Timezone missing")

                pub_date = dt.astimezone(timezone.utc).date()

                if pub_date > as_of:
                    reason = "future_date"
                elif pub_date < window_start:
                    reason = "outside_window"
                else:
                    reason = None

            except (ValueError, AttributeError, TypeError):
                reason = "invalid_date"

        if reason is None:
            eligible.append(item)
        else:
            exclusions.append({
                "item_id": item.get("item_id"),
                "version_id": item.get("version_id"),
                "reason": reason,
                "detail": f"published_at={published}"
            })

    (run_dir / "exclusions.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=True) + "\n"
                for x in exclusions),
        encoding="utf-8"
    )

    for item in eligible:
        print(json.dumps(item, ensure_ascii=True))

    status = "success"
    error = None

except Exception as exc:
    status = "failed"
    error = str(exc)
    print(f"ERROR: {error}", file=sys.stderr)

finally:
    finished = datetime.now(timezone.utc)
    receipt = {
        "stage": "filter_items",
        "status": status,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "input_count": (
            len(eligible) + len(exclusions)
            if status == "success" else None
        ),
        "output_count": (
            len(eligible) if status == "success" else None
        ),
        "tool": "Python standard library",
        "cost_usd": 0,
        "errors": [error] if error else []
    }
    receipt_path = run_dir / "logs" / (
        "filter_items_" + uuid.uuid4().hex + ".json"
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2),
        encoding="utf-8"
    )

if status != "success":
    sys.exit(2)
