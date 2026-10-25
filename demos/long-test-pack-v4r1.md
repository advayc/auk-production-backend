# Long audio test pack v4r1 (24 Oct 2026)

Source-only test inputs for the voice editor and transcript editor operations: 9 public operations plus 1 whole-sentence workflow case (the replace operation with `segment_scope=whole_clip`), 10 cases total.

**Download:** [`long-test-pack-v4r1-20261024.zip` (release testpack-v4r1)](https://github.com/advayc/auk-production-backend/releases/tag/testpack-v4r1) - 10 source WAVs, `test-matrix.json` (per-case request, transcript, signal facts, planner targets), `planner-evidence-v4.json` (full structured `plan_request()` payloads and returned plans), and the full README.

## Status

- **Source-only inputs.** No generated outputs exist for these cases.
- **Planner-tested:** `plan_request()` from current-main backend code was run CPU-side for all 10 cases and accepted each one; full request/result payloads preserved in the zip. `target_seconds` is the planner-derived requested target, not an output-duration guarantee.
- **Not runner-ready:** VM-side alignscreen on the owning runner environment has not been executed.
- **Perceptual quality unverified:** nobody has listened to these recordings; quality evidence is provenance, double-transcript agreement, and signal measurements only.

## Case limitations

- **replace / insert / delete** are phrase-level edits expressed with full-clip segment context. They are NOT tests of narrow localized preservation; the localized-splice path is not exercised.
- **nonverbal_remove** is a stress case, not a normal-path-qualified one: a 4-speaker meeting mix with overlapping laughter. The meaningful preservation expectation is word-level (QA compares output words against the source transcript); speaker-identity preservation is not meaningfully defined for a multi-speaker mix. Its target 17.6s is an annotation-union-duration hypothesis only - speech overlaps laughter in-window, so there is no guarantee the target removes only laughter without affecting overlapping speech.
- **whole_sentence** tokenization evidence (planner-side, `str.split()`): 40 words before, 37 after, ratio 0.925, target 13.4s; rerun from the archived payload reproduces the stored plan.

## Sources and licenses

- Nine sources: **LibriSpeech dev-clean** (12.7-15.0s), CC BY 4.0. Panayotov et al., "Librispeech: An ASR corpus based on public domain audio books", ICASSP 2015. https://www.openslr.org/12
- nonverbal_remove source: **AMI Meeting Corpus** ES2002a, Mix-Headset channel, 254.3-279.0s, CC BY 4.0. Carletta et al., "The AMI Meeting Corpus: A Pre-announcement", MLMI 2005. http://groups.inf.ed.ac.uk/ami/corpus/ - laughter events grounded in AMI manual annotations v1.6.2.
