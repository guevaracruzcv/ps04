# Three evidence-grounded briefs

Return {"output": [...]} with exactly three records, piece_id 01, 02, 03.
Every brief has distinct title, question, argument, synthesis, limitations,
claims. Piece 01 explains developments; 02 scrutinizes competing claims and
interpretations; 03 develops implications and what the audience should watch.

Each claim has claim_id (e.g. 01-c1), statement, type (reported_fact/source_claim/
inference), and evidence array. Each evidence reference has item_id, version_id,
locator. Written locators use the bound-passages-v1 selector contract:
{"type":"text","start_passage_id":"exact bound ID","end_passage_id":"exact bound ID"}.
Select existing IDs from the referenced item's written_passages catalogue.
Equal endpoints select one passage; ordered endpoints select a contiguous range
including every intervening character and newline. IDs are bound to that exact
item and evidence version. Bare local IDs such as p0016 are invalid.
Do not supply quote text, offsets, alternative passages, or extra locator keys.
Python resolves selected passages directly from immutable archived evidence.
Never reconstruct author lists, flatten bullets, insert ellipses, or repair
extraction artifacts. Invalid, cross-source or stale selectors fail explicitly.
Put paraphrases and interpretations in claim statements with the appropriate
type. A paraphrase must never be labelled an exact quotation. If no exact
passage supports a claim, omit or qualify the claim and state the limitation.
All written locators are checked against the full immutable source version;
plausible wording and Unicode normalization do not satisfy that check.
Media locators: {"type":"segment","segment_id":"actual archived segment ID"}.
Use only accepted items assigned to that piece. Each piece needs at least three
independent organizations, counting MIT and MIT Sloan together. Explain how
evidence connects rather than list summaries. Include real limitations and
counterarguments. YouTube captions are navigation markers, never automatically
verified quotations. Distinguish country-specific evidence from hypotheses.
Do not silently promote deferred items or manufacture evidence to meet coverage.
If requirements cannot be met, explain failure; do not return invented briefs.
