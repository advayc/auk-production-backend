# AuK voice editing backend



**Status: v0.3.3 scoped-nvdel candidate.** CPU-verified (222 tests pass, fresh repo checkout). v0.3.3 adds the voice-editor `nonverbal_remove` operation (vendor cookbook 4.4 prompt shape: explicit target_seconds required, output must shorten, expected transcript = source) with scoped duration limits of 25s input / 25s output / 50s combined for that operation only - an app-tested bound from the 23.88s-to-22.0s probe envelope, not a vendor-proven maximum; all other operations keep the 15s/20s/30s limits. GPU-verified on a Colab L4 on 2026-10-18: one production-path `nonverbal_remove` case (NVDEL-01, 23.88s vendor fixture, target 22.0s, seed 42) passed technical checks and automatic QA on the first attempt (output 22.0s, sha256 `7e09f9aa...`, speaker ECAPA 0.9650, ASR WER-0); human listening review of that output is pending. v0.3.1 fixes insert_transplant join handling: pads and cuts are clamped to both the generated and source neighbor words, and the clamps never truncate the anchor phrase itself (the v0.3.0 localized-replace path was already clamped). GPU-verified on a Colab L4 on 2026-10-18 against the canonical v0.3.1 tree (module hash recorded): all four stock insert cases passed automatic QA (one on the retry attempt), and the owner approved those exact insert outputs as natural after listening; the strict control failed closed as designed; the localized splice case produced audio but failed automatic QA on both attempts and stays fail-closed. Listening approvals are bound to the exact reviewed audio bytes; they are not broad reliability proof. v0.2.8 remains the last fresh-install tested baseline, with the known limits below.

## What this is

AI voice editing API used by the AuK pipeline. Three workflows:

- Voice editor: emotion, voice characteristics, whisper, speed, custom instruction
- Voice enhancer: enhance speech, denoise, dereverb
- Transcript editor: replace, insert, delete

## Run it

The supported path is the notebook:

1. Open the org Colab (link is inside the notebook docstring and the team drive).
2. Use a fresh T4 runtime with generation switches off.
3. Run production cells P1 and P1b, then P0 to P4 in order to restore and install the pinned package.

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
- Segment edits are fixed-duration: max 15s source interval, 20s output (30s combined). `nonverbal_remove` has scoped limits of 25s/25s/50s (app-tested bound, see status). Longer clips are otherwise unsupported, and inserts can sound rushed because the duration cannot change.
- The 23.88s long-humming case now runs under the scoped `nonverbal_remove` limits and passed automatic QA once on L4 (see status); broader long-form coverage and the human listening verdict remain open.
- Automatic QA can pass audio that still sounds off. `automatic_qa_pass` is not `semantic_success`; keep the human listening step.
- Licensing: the package uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution. Keep the `COMMERCIAL_USE=False` paths intact. See `backend/SOURCES.md`.

## What changed in 0.3.3 (candidate)

`policy.py`: voice_editor gains `nonverbal_remove` (vendor cookbook 4.4 prompt shape; explicit target_seconds required, output must shorten, expected transcript = source). `core.py`: `scoped_limits` gives `nonverbal_remove` 25s/25s/50s (app-tested bound); other operations unchanged at 15/20/30. `worker.py`: scoped limits thread per-request, fixing the 15s span cap and the ffmpeg 21s decode-cap truncation on the 23.88s path. Includes the v0.3.1 transplant joinfix (`transplant.py` sha256 `cdfc5ae6...`). CPU 222 tests pass (fresh repo checkout, unittest discover, Python 3.10.12). GPU (Colab L4, 2026-10-18): NVDEL-01 production-path case passed technical checks + automatic QA on attempt 1 (output 22.0s sha256 `7e09f9aa...`, speaker ECAPA 0.9650, ASR WER-0); human listening pending. Module identity: `core.py` `1dbd718c...`, `policy.py` `6adcc072...`, `worker.py` `3f6ee8f3...`, `transplant.py` `cdfc5ae6...`. Regression test: `backend/tests/test_v033_nvdel.py`. Localized-splice quality, broader reliability, robotic detection, and enhancer scope remain unresolved.

## What changed in 0.3.1 (candidate)

`transplant.py`: insert pads and cuts are now clamped to both the generated and the source neighbor words, and neighbor clamps never truncate the anchor phrase itself. The 0.3.0 localized-replace path already had this clamp; the insert path did not, and a source-side cut could amputate the onset of the following word. CPU 181 tests pass (175 plus 6 new regressions). GPU (Colab L4, 2026-10-18, canonical v0.3.1 tree, six bounded cases, seeds 42/43, max two attempts): INS-STOCK-1/2/3/4 passed automatic QA (INS-3 on attempt 2), and the owner approved all four exact insert outputs as natural after listening (hash-scoped); the strict control failed closed by design; the LOC-H1 localized splice fails automatic QA on both attempts, diagnostic artifacts only. The run also byte-reproduced two earlier hash-approved artifacts, confirming splice/insert determinism on those paths. Module identity: `transplant.py` sha256 `cdfc5ae6...`; full 14-module manifest in the run log. Localized-splice quality remains unproven; the known limits below still apply.

## What changed in 0.3.0 (candidate)

`transplant.py`: the localized cut is clamped strictly inside the owner-verified interval, with frame-exact duration and no tail shift; if the changed words cannot fit the interval exactly, the edit fails closed (transplant_duration_mismatch) instead of cutting outside. This fixes the 0.2.9 scope excursion above. Status: CPU 175 tests pass; on the mixed v0.2.9-base/0.3.0-overlay GPU build the unpaced case fails closed as described and the single paced attempt produced an in-interval splice that failed automatic QA; canonical-0.3.0 GPU proof and human listening review remain pending for any case that produces audio.

0.2.9 introduced the ASR-guided transplant for transcript inserts (keep only the clean [anchor + insert] span from a full-context generation and splice it into the original audio). Raw per-case results live in the L4 results export; all of it predates the 0.3.0 cut-policy change.

## Dataset

Evaluation manifest at `backend/datasets/bootstrap/manifest.candidate.json` (LibriSpeech dev-clean, CC BY 4.0). Attribution lives in `backend/SOURCES.md` and must stay with the package.

## v0.3.4 diagnostics (candidate, 2026-10-18, diagnostic-only)

Adds seam and failure-classification diagnostics on top of the runtime-qualified v0.3.3 build. Pass/fail is unchanged: nothing new passes, qa_failed attempts stay failed and still need human review.

- `auk_reliability/seam.py` (new): splice-join jump-peak and spectral-flux diagnostics, recorded per localized attempt. Uncalibrated; not a robotic/naturalness detector.
- `auk_reliability/diagnostics.py` (new): outside-interval PCM byte re-verification plus transcript-disagreement classification. The `unedited_span` label requires word-timed proof that the mismatch is outside the cut; without timings the disagreement is labeled `unlocated` (uncertain), and a mismatch timed inside the cut is labeled `edited_span`.
- `auk_reliability/qa.py`: retains transcriber word-timings as diagnostic metadata when the transcriber provides them; the gate itself is unchanged.
- `tests/test_v034_diagnostics.py`: 44 tests. Full suite 266/266 (sandbox Python 3.10.12) plus a fresh-install proof (v0.3.0 base + overlay in a clean tree, module SHAs verified, 266/266).
- Real-byte check on the run3 LOC-H1-T1.9 output (sha256 `2e71b6ae...`): outside-interval byte-exactness verified on the actual bytes; seam jump peaks 3e-05/0.00037, spectral-flux ratios 1.60/2.28 vs clip baseline 0.626. First real diagnostic observations, not calibration.

v0.3.3 qualification evidence stands unchanged: NVDEL-01 L4 automatic QA PASS (output sha256 `7e09f9aa...`), human listening pending. Qwen2.5-Omni-3B conditioner remains non-commercial until a license is confirmed.

## v0.3.5 multi-word donor span (UNQUALIFIED candidate, 2026-10-18, offline-tested only)

Extends the localized replace path so a changed word that cannot fit the interval cut alone can be spliced together with trailing EQUAL neighbor words that sit fully inside the verified interval. The text never changes (trailing words are token-identical), the cut never crosses the interval, duration is preserved, outside-interval PCM stays byte-exact, and the smallest fitting span wins. Anything that still cannot fit fails closed with `transplant_duration_mismatch`, unchanged.

- `auk_reliability/transplant.py`: fit search over span width (changed words first, then +1 trailing equal word at a time, capped by the equal-word run and the interval edge). Return metadata gains `span_strategy` (`changed_only` / `changed_plus_trailing_equal_words` / `deletion` / `insertion`) and `regenerated_neighbor_words`; both flow into run records through the existing splice dict. Also fixes a pad-distribution edge where `pad_pre` could exceed the slack and silently clip the donor word tail.
- Tradeoff, stated plainly: when the wider span is used, the included neighbor words are re-generated donor audio of the SAME words inside the interval. Original PCM is only guaranteed outside the cut, as before; the guarantee boundary is unchanged (the verified interval), but within it more words can now carry donor audio. Every candidate still faces the unchanged full QA gate and human review.
- `tests/test_v035_multiword.py`: 5 tests (base fit keeps changed-only behavior, +1-word fit with byte-exact outside PCM and preserved duration, no-fitting-span fail-closed, interval-crossing refusal, deletion/insertion strategy metadata). Full suite 272/272 (sandbox Python 3.10.12).
- Offline assessment on real run3 artifacts: the recorded `transplant_duration_mismatch` donor realization (request `89c591e4`, donor "stronger team" 0.82s vs max in-interval cut 0.75s) still fails closed under the widened search; the strategy rescues near-miss realizations, not arbitrary donor pacing. The other recorded LOC-H1 realization (request `01d24be3`) spliced successfully and failed QA only on an unedited-span ASR disagreement ("There"/"They") that the pristine source itself exhibits. End-to-end rescue rate across donor seeds is unmeasured; no runtime run has been executed for v0.3.5.

v0.3.4 diagnostics and v0.3.3 qualification evidence stand unchanged. Qwen2.5-Omni-3B conditioner remains non-commercial until a license is confirmed.

## v0.3.6 borrowed-room donor assembly (EXPERIMENTAL, UNQUALIFIED, opt-in, 2026-10-18, offline-tested only)

Isolated experimental extension of the v0.3.5 span search for packed donors whose words fit the interval cut lengthwise (alone or with re-generated trailing equal words) but carry no natural room tone around the words. Default behavior is byte-identical to v0.3.5: the path activates only when `localized_transplant(..., allow_borrowed_room=True)` is passed explicitly; no shipped caller (worker, CLI, notebook) passes it.

- `auk_reliability/transplant.py`: `_borrowed_room_fit` assembles patch = verified_room(pre) + donor words + verified_room(post). Donor word audio is copied byte-exact (never faded or clipped); every crossfade sits inside the room segments. Room is verified low-energy donor audio: the longest contiguous run of 25 ms windows at <= 5% of donor speech rms, digital silence never accepted, tiled with internal crossfades when shorter than needed. Refuses (returns None, then fails closed with `transplant_duration_mismatch` as before) when the span does not fit lengthwise, when slack is too small to keep external crossfades out of the words, or when no verified room exists. `span_strategy` gains `changed_only_borrowed_room` / `changed_plus_trailing_equal_words_borrowed_room`.
- `tests/test_v036_borrowed_room.py`: 5 tests (packed-donor rescue with donor word bytes exact + outside PCM byte-exact + duration preserved, flag-off identical-to-v0.3.5 fail-closed regression, refusal when no verified room, changed-only borrowed variant, natural room still preferred over borrowed). Full suite 277/277 (sandbox Python 3.10.12).
- Offline assessment on the recorded v0.3.2 duration-failure donor realizations (3 observed): 2 of 3 rescue mechanically (output sha256 `7ce38374299a...` via `changed_plus_trailing_equal_words_borrowed_room`, output sha256 `6c51aa9d78b6...` via `changed_only_borrowed_room`; both word-bytes-exact, outside-PCM byte-exact, duration-preserved, local-ASR correct). The third remains impossible on length (donor span 1.04s vs max in-interval cut 0.66s), unchanged. These are 2 of 3 observed donors, not a measured rescue rate.
- Honest status: mechanically viable on the observed cases; audibility of the deliberate onset-preserving hard cuts at the word boundaries is UNRESOLVED - no listening evaluation has happened. Measured join transients are recordings, not perceptual verdicts. No runtime run, no default adoption, no QA-gate change. Human listening review is the next gate before any further claim.

v0.3.5 candidate status, v0.3.4 diagnostics and v0.3.3 qualification evidence stand unchanged. Qwen2.5-Omni-3B conditioner remains non-commercial until a license is confirmed.
