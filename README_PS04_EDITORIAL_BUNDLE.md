# PS04 Editorial Draft Bundle - Version 1

This package saves the three English article drafts and three companion video scripts from the PS04 learning workflow, plus a technical demo runbook and submission-readiness checklist.

## Source of material

These are **assistant-prepared drafts based on the evidence packets and source extracts reviewed during this project**. They are not verified final publications and do not imply the user has approved the finished texts.

## Files

- `editorial/drafts/01_ai_at_work.md`
- `editorial/drafts/02_who_should_decide.md`
- `editorial/drafts/03_ai_and_developing_economies.md`
- `writing/video_scripts/01_ai_at_work_video.md`
- `writing/video_scripts/02_who_should_decide_video.md`
- `writing/video_scripts/03_developing_economies_video.md`
- `docs/TECHNICAL_DEMO_RUNBOOK.md`
- `docs/SUBMISSION_READINESS.md`
- `docs/EDITORIAL_BUNDLE_MANIFEST.json` (SHA-256 hashes of the eight content files)

## Import into the Windows Git Bash project

1. Save `ps04_editorial_bundle_v1.zip` from ChatGPT into your Windows Downloads folder.
2. Open Git Bash at your actual `ps04` project root.
3. Use the safe import command provided in the accompanying ChatGPT response. It checks whether the destination files already exist and verifies SHA-256 hashes before writing.
4. Run `git status --short` to review the new files. Do not commit secret keys or personal data.

## Editorial publication gate

Human editor approved the **source selection** under V2, not final wording or publication. No Substack/YouTube posts or videos are represented as completed or published. Publication remains NOT AUTHORIZED.

## Preservation

The bundle is intended to add new `drafts/`, `video_scripts/`, and `docs/` files. It must not overwrite the existing `editorial/article*_evidence_packet*.md` files, `run.sh`, databases, or policy/event histories.
