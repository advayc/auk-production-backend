# AuK voice editing backend



**Status: v0.3.1 candidate.** CPU-verified (181 tests pass). v0.3.1 fixes insert_transplant join handling: pads and cuts are clamped to both the generated and source neighbor words, and the clamps never truncate the anchor phrase itself (the v0.3.0 localized-replace path was already clamped). GPU-verified on a Colab L4 on 2026-10-18 against the canonical v0.3.1 tree (module hash recorded): all four stock insert cases passed automatic QA (one on the retry attempt), and the owner approved those exact insert outputs as natural after listening; the strict control failed closed as designed; the localized splice case produced audio but failed automatic QA on both attempts and stays fail-closed. Listening approvals are bound to the exact reviewed audio bytes; they are not broad reliability proof. v0.2.8 remains the last fresh-install tested baseline, with the known limits below.

## What this is

AI voice editing API used by the AuK pipeline. Three workflows:

- Voice editor: emotion, voice characteristics, whisper, speed, custom instruction
- Voice enhancer: enhance speech, denoise, dereverb
- Transcript editor: replace, insert, delete

## Run it

The supported path is the notebook:

1. Open the org Colab (link is inside the notebook docstring and the team drive).
2. Use a fresh T4 runtime with generation switches off.
3. Run production cells P1 to P4 in order to restore and install the pinned package.

CPU-only install for local inspection and tests:

```bash
python -m pip install ./backend          # python 3.11-3.13
python -m unittest discover -s backend/tests -v
```

The CLI has three commands: `validate-dataset`, `refresh-reviews`, `run-suite`.

```bash
python -m auk_reliability.cli run-suite --help
```

GPU generation runs through the Colab only. Model weights (~15 GB) download at runtime from pinned revisions.

## Known limits

- The 0.3.0 strict-scope fix is CPU-verified (175 tests). The GPU evidence comes from the mixed build described above (v0.2.9 base + apparent 0.3.0 transplant overlay, module hash unrecorded), not the canonical 0.3.0 tree. On that build, the current localized test case fails closed (transplant_duration_mismatch, 3 of 3 seeds, no output produced): the donor phrase (0.38s) is longer than the source span (0.22s) and the full donor window (0.96s) cannot fit the verified interval (0.86s) without touching neighboring words. Whether other localized cases pass is unknown. Longer-replacement localized edits are unsupported by the current transplant strategy; whole-clip inserts are unaffected. Word preservation, voice match, and naturalness at the splice remain unproven. Raw evidence: [three per-seed failure JSONs](https://drive.google.com/file/d/1fyIxABni7cuc4RiT092C-ed3VmSEgDIC/view) and a [word-timing diagnostic](https://drive.google.com/file/d/1J_kkfmoGWftzBowsPXfYbZM9U7qBw4mV/view).
- Bounded follow-up on the same case (driver-only duration conditioning, target 1.96s, seed 42, one attempt): the donor word was paced to 0.22s and the splice fit the strict cut [1.39, 1.61] with frame-exact duration and no tail shift reported (technical_success=true, speaker 0.956). Automatic QA still failed: ASR read the first word as "There" against the reference "They", outside the edited span - an unresolved ASR/reference label disagreement (the reference, an independent local transcription, and the original recording all read "They"; only the VM ASR read "There"), not an edit-quality pass, and the manifest was not corrected to force a pass. The output audio was not exported before the VM shut down, so the splice mechanics are reported in the run log, not externally byte-proven. Engineering's provenance reconcile confirms this run and the three failures above all used the same mixed v0.2.9-base + apparent-0.3.0-overlay build with the module hash unrecorded, so the strict-contract observations are consistent with 0.3.0 behavior on the exercised paths but are not canonical-0.3.0 GPU proof. The three failures above were unpaced; this paced attempt is the only run that produced a splice, and it did not pass QA. [Attempt bundle](https://drive.google.com/file/d/1R_m632W7m3H9GSDqOMo6pYZjUhg0G5Eo/view).
- 0.2.9's GPU evidence is historical and does not carry to 0.3.0. Its six L4 cases passed technical and automatic QA, but the localized one cut 8.4ms outside the verified interval and replaced parts of neighboring words - a scope failure, not a pass. The other five 0.2.9 cases (insert x2, replace, delete, insert) keep their narrow automatic-QA-pass status on 0.2.9 code only.
- Segment edits are fixed-duration: max 15s source interval, 20s output. Longer clips are unsupported, and inserts can sound rushed because the duration cannot change.
- One 23.88s long-humming removal stays blocked by policy because the clip exceeds the duration limits.
- Automatic QA can pass audio that still sounds off. `automatic_qa_pass` is not `semantic_success`; keep the human listening step.
- Licensing: the package uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution. Keep the `COMMERCIAL_USE=False` paths intact. See `backend/SOURCES.md`.

## What changed in 0.3.1 (candidate)

`transplant.py`: insert pads and cuts are now clamped to both the generated and the source neighbor words, and neighbor clamps never truncate the anchor phrase itself. The 0.3.0 localized-replace path already had this clamp; the insert path did not, and a source-side cut could amputate the onset of the following word. CPU 181 tests pass (175 plus 6 new regressions). GPU (Colab L4, 2026-10-18, canonical v0.3.1 tree, six bounded cases, seeds 42/43, max two attempts): INS-STOCK-1/2/3/4 passed automatic QA (INS-3 on attempt 2), and the owner approved all four exact insert outputs as natural after listening (hash-scoped); the strict control failed closed by design; the LOC-H1 localized splice fails automatic QA on both attempts, diagnostic artifacts only. The run also byte-reproduced two earlier hash-approved artifacts, confirming splice/insert determinism on those paths. Module identity: `transplant.py` sha256 `cdfc5ae6...`; full 14-module manifest in the run log. Localized-splice quality remains unproven; the known limits below still apply.

## What changed in 0.3.0 (candidate)

`transplant.py`: the localized cut is clamped strictly inside the owner-verified interval, with frame-exact duration and no tail shift; if the changed words cannot fit the interval exactly, the edit fails closed (transplant_duration_mismatch) instead of cutting outside. This fixes the 0.2.9 scope excursion above. Status: CPU 175 tests pass; on the mixed v0.2.9-base/0.3.0-overlay GPU build the unpaced case fails closed as described and the single paced attempt produced an in-interval splice that failed automatic QA; canonical-0.3.0 GPU proof and human listening review remain pending for any case that produces audio.

0.2.9 introduced the ASR-guided transplant for transcript inserts (keep only the clean [anchor + insert] span from a full-context generation and splice it into the original audio). Raw per-case results live in the L4 results export; all of it predates the 0.3.0 cut-policy change.

## Dataset

Evaluation manifest at `backend/datasets/bootstrap/manifest.candidate.json` (LibriSpeech dev-clean, CC BY 4.0). Attribution lives in `backend/SOURCES.md` and must stay with the package.
