# PS04 - Technical Agent Demonstration Runbook

**Status:** Recording guide only. No demonstration video has been recorded or uploaded.
**Suggested duration:** 4-6 minutes, subject to the assignment rubric.
**Recording environment:** Windows, Git Bash, project directory `ps04`.

## Purpose

Demonstrate an evidence-aware agent workflow from source collection through verified content, SQLite versioning, editorial policy, and explicit human gates. Distinguish archived runs from actions performed live on camera. Do not disclose API keys or personal information.

## Narrative and on-screen sequence

### 0:00-0:40 - The problem and architecture

Say: "This project examines how AI changes employment, skills, and public-sector capacity. The system handles articles, YouTube captions, and podcast transcripts, then preserves evidence for editorial decisions."

Show the working directory and modules (read-only):

```bash
pwd
ls -l run.sh
find collectors processing workflows editorial data -maxdepth 1 -type f | sort
```

Explain `run.sh` as orchestrator, the collectors as source interfaces, SQLite as evidence store, and editorial files as an audit trail.

### 0:40-1:40 - Two real collection runs

Refer to actual archived run directories, without starting a new paid or network operation:

- `runs/collect-20261011T163942Z-2489`: 52 items, 50 RSS articles plus two podcasts; zero YouTube due to a source configuration error.
- `runs/collect-20261011T164724Z-2629`: 54 items, including two YouTube videos; 52 versions unchanged and two new.

Say explicitly: "The first run ended technically successfully but missed YouTube. Auditing the format counts detected the failure. Fixing source configuration and rerunning brought in both videos."

Display format and change counts from actual stored JSONL instead of relying only on `SUCCESS` labels:

```bash
python - <<'PY'
import json
from pathlib import Path
from collections import Counter
for name in ['collect-20261011T163942Z-2489',
             'collect-20261011T164724Z-2629']:
    folder=Path('runs')/name
    def rows(filename):
        return [json.loads(line) for line in (folder/filename).read_text(encoding='utf-8').splitlines() if line.strip()]
    items=rows('items.jsonl')
    changes=rows('changes.jsonl')
    print(name)
    print('  items', len(items), 'formats',dict(Counter(i['kind'] for i in items)))
    print('  changes', dict(Counter(i['change'] for i in changes)))
PY
```

### 1:40-2:30 - Offline replay and evidence integrity

Show the archived replay run folders, whose hashes were independently audited:

- `runs/replay-20261011T160340985008Z`: 12 versions first indexed.
- `runs/replay-20261011T160512721898Z`: the same 12 unchanged.

Say: "Offline replay verifies text hashes and timestamped evidence without repeated downloads or paid transcriptions."

Optionally show `run.json` from an archived replay. Avoid claiming these are two fresh collection runs: they are replay runs.

### 2:30-3:30 - Editorial governance and human gate

Show:

```bash
cat config/active_editorial_policy.json
python - <<'PY'
import json
from pathlib import Path
p=Path('runs/editorial-prep/human_approval_v2.json')
r=json.loads(p.read_text(encoding='utf-8'))
print('approval_id',r['approval_id'])
print('human_decisions',r['human_decisions'])
print('publication_authorized',r['publication_authorized'])
PY
```

Explain V1 selection (nine ACCEPT, two DEFER, one REJECT); V2 approved one decision change from REJECT to DEFER. Publication is still unauthorized. Source approval is not article approval.

### 3:30-4:30 - Evidence to editorial deliverables

Show the three evidence packets and the draft Markdown files:

```bash
ls -l editorial/article*_evidence_packet*.md
ls -l editorial/drafts/*.md
ls -l writing/video_scripts/*.md
```

Explain how source `item_id`/`version_id`, timestamped segments, and editorial status support traceability. YouTube VTT subtitle cues overlap, so they are navigation anchors pending contextual review, not verified verbatim quotations.

### 4:30-5:15 - What worked, what failed, and next action

Discuss the real recovery: the source configuration sent only podcasts to YouTube; audit detected zero videos; corrected configuration produced two YouTube items. Mention RSS source access failures (HTTP 403) and rate limiting (HTTP 429) only if their local recovery notes/logs are available and can be shown.

Conclude: "The system demonstrates evidence versioning and human oversight. The drafts still need final verification and publishing approval; successful execution is not automatically permission to publish."

## Recording checklist

- [ ] Screen capture of real files and outputs rather than fabricated screenshots.
- [ ] Do not show API tokens, credentials, private emails, or identifiable account details.
- [ ] Confirm voice audio intelligible and on-screen text readable.
- [ ] Record the demo; store file under a suitable `dist/` or `submission/` directory.
- [ ] Verify its duration, title, and playback.
- [ ] Obtain explicit human approval prior to public upload.
- [ ] Record the actual YouTube URL after uploading; do not put invented URLs in submission files.
