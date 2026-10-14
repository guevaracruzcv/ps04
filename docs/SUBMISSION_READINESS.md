# PS04 - Submission Readiness and Remaining Work

**Audit snapshot:** 2026-10-12. Working corpus originally replayed with `as_of_date=2026-10-11` (window 2026-09-12 through 2026-10-11 inclusive). Re-check the date window at actual submission.

## Evidence and workflow already demonstrated

- [x] Twelve archived evidence items verified against text SHA-256, with `8 feed` labels, `2 podcast`, `2 YouTube`.
- [x] Seven independent organizations in the editorial corpus (counting MIT and MIT Sloan together).
- [x] Timestamped podcast and YouTube evidence preserved; VTT cues may overlap.
- [x] Editorial policy V1, a proposed V2, and human-approved V2 with historical records preserved.
- [x] Human selection under V2: 9 ACCEPT and 3 DEFER. Publication NOT authorized.
- [x] Two offline replay runs, with 12 newly indexed then 12 unchanged.
- [x] Two live collection runs. Run 1 has 52 items without YouTube; run 2 has 54 items with two YouTube videos. Run 2 recorded 52 unchanged and two new.
- [x] Two archived podcast transcripts matched against live RSS candidates without new paid transcription.
- [x] Three local evidence packets prepared (the first has a V2 timestamp repair).

## What remains to verify or deliver

- [ ] Resolve **discovery provenance**: several Harvard, MIT Sloan, and World Bank articles came from direct URLs while their normalized records say `kind=feed`. Do not claim all eight were discovered by RSS. Actual MIT RSS evidence supplies at least two genuinely RSS-derived articles. Consider a separate `discovery_method` annotation without rewriting historical versions.
- [ ] Confirm all publication dates and substantive source claims against original archived content, especially quantitative figures.
- [ ] Check article 1 and article 2 evidence packets for website navigation text mixed into extracts.
- [ ] Check YouTube VTT passages in video/audio context; they are not reliable direct quotations as currently segmented.
- [ ] Make sure each final published article meets the assignment's minimum of three independent publisher organizations.
- [ ] Finalize three Substack articles, review them, then obtain explicit human authorization. Record **real** publication URLs only after publication.
- [ ] Record, edit, and review three associated videos; obtain human authorization prior to YouTube uploads. Record actual video IDs and URLs.
- [ ] Record and review a technical demonstration video of collection, SQLite, replay, policy, failure/recovery, and human gate.
- [ ] Document actual OpenAI API model(s), transcription costs/usage and failure handling from receipts where available. Do not invent costs.
- [ ] Verify final packaging and `SUBMISSION.md` according to the PS04 rubric. Include actual deliverables and honest gaps; no fictional YouTube or Substack publication.
- [ ] Confirm git status and commit the intended source code/evidence manifest files; review `.gitignore` to avoid committing secrets and bulky media unintentionally.

## Truth-in-reporting distinctions

1. **Source selection approved** is not **article approved**. The three article files are drafts, not publications.
2. **Script written** is not **video recorded or published**.
3. **Replayed twice offline** is not **collected twice live**; both types of runs exist and have separate evidence.
4. **Workflow reports SUCCESS** is not sufficient evidence of full format coverage. Run 1 demonstrated this gap; run 2 repaired it.
5. **Seven organizations across archived editorial material** does not mean the live collector queried seven independent organizations. The live collection is predominantly MIT RSS plus two podcasts and two YouTube videos.
6. **Current sources contain no country-specific baseline** for Cabo Verde. Any country discussion is analytical rather than empirically validated.

## Suggested final project structure

```
ps04/
  run.sh
  config/
    editorial_policy.md
    active_editorial_policy.json
    active_sources.json
  editorial/
    article1_evidence_packet_v2.md
    article2_evidence_packet.md
    article3_evidence_packet.md
    drafts/
      01_ai_at_work.md
      02_who_should_decide.md
      03_ai_and_developing_economies.md
  writing/
    video_scripts/
      01_ai_at_work_video.md
      02_who_should_decide_video.md
      03_developing_economies_video.md
  docs/
    TECHNICAL_DEMO_RUNBOOK.md
    SUBMISSION_READINESS.md
  runs/
    ...
```
