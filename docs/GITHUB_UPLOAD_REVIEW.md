# GitHub Upload Review - October 14, 2026

**Verdict: BLOCKED pending researcher approval of the final inventory and confirmation of an owned repository.** Academic deliverables remain incomplete, as disclosed in SUBMISSION.md. Development is closed. No staging, commit, push, remote change, pipeline execution or publication occurred.

## Submission files prepared

- `SUBMISSION.md`: completed factual submission with explicit missing-deliverable disclosure.
- `docs/submission_evidence.json`: labelled projections of three saved summaries, selected receipts, source/decision samples, failure references and recorded tests. Originals remain unchanged. Source paths identify local originals; complete assets are not distributed.
- `docs/GITHUB_UPLOAD_REVIEW.md`: inventory and exclusion review.
- `docs/github-upload-paths.txt`: exact proposed allowlist for later approved staging, including current implementations and the three historical Mission 22 Markdown briefings and JSONL. Their pending-publication notices remain intact.

## Existing staged inventory - 38 entries, unchanged

Raw index SHA-256: `7d812694e5f0c2faa8f28d46ef7621712c81f797b14945f86084db967b41417f`.

```text
.gitattributes
.gitignore
README_PS04_EDITORIAL_BUNDLE.md
collectors/fetch_feeds.sh
collectors/fetch_podcasts.sh
collectors/fetch_youtube.sh
config/active_editorial_policy.json
config/active_sources.json
config/editorial_policy.md
config/editorial_policy_v1.md
config/editorial_policy_v2.md
config/podcast_sources.json
config/project.json
config/sources.json
data/store.py
data/store.sh
docs/PS04_EXECUTION_AUDIT.md
docs/PS04_HUMAN_APPROVAL_V2.json
docs/PS04_HUMAN_DECISIONS_V2.jsonl
docs/SUBMISSION_READINESS.md
docs/TECHNICAL_DEMO_RUNBOOK.md
editorial/drafts/01_ai_at_work.md
editorial/drafts/02_who_should_decide.md
editorial/drafts/03_ai_and_developing_economies.md
processing/extract_content.py
processing/extract_content.sh
processing/extract_institutional.py
processing/extract_youtube.py
processing/filter_items.py
processing/filter_items.sh
processing/normalize_vtt.py
processing/reuse_podcast_evidence.py
run.sh
workflows/collect_sources.sh
workflows/write_receipt.py
writing/video_scripts/01_ai_at_work_video.md
writing/video_scripts/02_who_should_decide_video.md
writing/video_scripts/03_developing_economies_video.md
```

Staged blob payload totals 128,328 bytes. Largest staged file: `editorial/drafts/02_who_should_decide.md` (10,864 bytes). No media/database files or common provider-token/private-key signatures were found in the staged blobs. Focused pattern inspection cannot guarantee detection of every secret or sensitive passage. Human decisions and drafts require the researcher's final public-disclosure review.

## Specific reasons to approve additional staging

The index omits current `SUBMISSION.md`, several implemented Bash components, all four current prompts, critical Python helpers (`pipeline_common.py`, `model_adapter.py`, `model_evidence.py`, editorial/rendering/review/packaging helpers), tests and the submission evidence sample. Several staged paths also have newer working-tree versions. Committing the existing index alone would not capture the implemented project. The exact allowlist proposes adding missing files and updating older blobs. **No such staging has occurred.**

The allowlist contains 86 exact paths. It deliberately excludes operational runs and bulk assets; it is not a complete runnable recovery archive. Review the literal file list before approving it. Older `docs/PS04_EXECUTION_AUDIT.md`, `docs/SUBMISSION_READINESS.md` and `docs/TECHNICAL_DEMO_RUNBOOK.md` remain unchanged historical snapshots. SUBMISSION.md distinguishes their collection/replay success from later end-to-end failures. Earlier drafts remain unpublished working material.

## Files to exclude and portability limits

Current `.gitignore` covers `.env`/`.env.*` (except `.env.example`), `*.key`, `*.pem`, virtual environments, bytecode, `runs/`, `data/raw/`, `data/evidence/`, database extensions, backups and logs. **It does not cover `data/media/`, `data/assets/`, ZIP archives or generated test artifacts.** It remains unchanged because it is already staged. Use the exact allowlist; do not use `git add .`, `git add -A` or broad forced staging.

Exclude from proposed public upload:

- API keys, tokens, secret environment/configuration files, private/sensitive data and unrelated personal documents.
- `data/media/`: 151 files, 781,124,425 bytes. Downloaded copies of `1FeLhg9HqfE.webm` are 91,628,767 bytes; `KgI2_dKnpk0.webm` copies are 126,504,235 bytes. Keep them local; do not add large-file storage simply to bypass inventory review.
- Bulk `data/assets/`: 2,522 files, 419,768,757 bytes of extracts, transcripts and duplicated generated assets. Public samples provide metadata, hashes and limited passages/segments.
- Operational `runs/`, `data/evidence/`, databases/WAL/SHM files, external backups and full provider request/response dumps. Selected records appear in the new sample instead.
- `docs/submission_preflight_v1.zip`, `editorial/rss_integration_v3.zip`, generated snapshot bundles, `tests/artifacts/`, caches, bytecode, virtual environments and temporary outputs.
- Historic preservation-baseline inventories and unrelated audit bulk. Local archives and backups are preserved.

The allowlist has no broad recursive directories. No common token/private-key signatures were detected in the proposed current files. This focused inspection is not blanket approval to disclose every historical human record or third-party text.

Tests and initialization reference historical assets absent from the proposed small public upload. Full clean-clone regression reproduction and end-to-end execution are not established. Source samples support selected trace inspection, not reconstruction of every quotation. Complete evidence would require a separately reviewed distribution arrangement. Publisher material needs normal rights/context review before wider redistribution.

## Branch and remote

Branch: `main`. Existing `origin` fetch/push URL: `https://github.com/onexi/ps04.git` (course repository). No remote was contacted; access, fork status and server ahead/behind were not verified. Intended account: `guevaracruzcv`. `https://github.com/guevaracruzcv/ps04` is a proposed destination, not a verified existing submission repository.

## Exact conditional commit/push commands

First create or confirm an owned `guevaracruzcv/ps04` repository through the human GitHub interface. The commands below assume a new empty destination and explicit approval of every allowlisted file. If the destination has different commits, inspect/reconcile before proceeding; do not force-push. They are review instructions, not authorized actions in this task.

```bash
export GIT_OPTIONAL_LOCKS=0
git status --short
git diff -- SUBMISSION.md
git add --pathspec-from-file=docs/github-upload-paths.txt
git diff --cached --stat
git diff --cached --check
git diff --cached --name-status
# Review complete staged content against the approved inventory.
git diff --cached
git commit -m "Document PS04 academic submission and incomplete deliverables"
git remote add submission https://github.com/guevaracruzcv/ps04.git
git remote -v
# Confirm submission is the owned destination, with no conflicting history.
git push -u submission main
```

Do not push to the course `origin`. Credentials and push access are not verified by these instructions. Do not run the pipeline, inference, collection or publishing for this upload. No class spreadsheet was accessed or changed.
