# Deliverable 5: recommended production config per operation + known failure cases

Status: **draft, 2026-11-17**. Assembled from existing measured evidence; no new GPU runs.
Companion data file: `recommended_config.json` (schema in place, all operations
currently `not_qualified` - see below).

## Part 1 - Recommended production config per operation

**No operation is qualified yet.** `recommended_config.json` carries every
operation as `not_qualified` with zero measured profile runs: the per-operation
Base F32 / Base Q8 / Flash benchmark required by the spec was never collected.
This document does not guess recommendations from unmeasured profiles.

What exists today:

- The acceptance harness records per-attempt model/profile, seed, latency and
  failure reason, so the data path needed to qualify a profile already exists.
- Measured latency context only (not a profile comparison): roughly 2 minutes
  per request on a Colab T4 for editor operations, and L4 measured at
  ~1.54 credits/hour. These say nothing about Q8 or Flash quality/speed.
- All production runs to date used Base F32. That is history, not a
  recommendation.

To qualify a recommendation, per operation: run the acceptance set on each
profile (Base F32, Base Q8, Flash), then pick the fastest profile meeting the
quality bar, per the spec's priority order (correctness > failure detection >
reliability > quality > latency > GPU cost). Requires GPU runs; not started.

## Part 2 - Known failure cases (from measured runs)

Category pass counts below are automatic gates (exact transcript match +
speaker voice-match >= 0.75 + success gate). They are not listening verdicts;
human listening review is pending across the board. Per the owner's rule, a
category needs at least 10 examples with minimum 9/10 to count as proven.

### Voice editor / transcript editor (scale-up state Nov 3, overall 83/90)

1. **Speed change: 12/15, clip-specific.** Clip p336_034 fails at both 1.4x
   (speaker 0.66-0.71) and 1.35x (best 0.713), below the 0.75 speaker gate.
   1.4x is the stated rate limit; it passed on all three newer clips tried, so
   the failures are clip-specific, not a rate ceiling. Fix approach (verbatim
   prompting, per the delete-category precedent) not yet run on speed.
2. **Voice change: 10/12, clip-specific** transcript or borderline-speaker
   failures. Same untried fix approach as speed.
3. **Replace: 7/7 and emotion: 5/5 pass observed but under-sampled** - both
   below the 10-example minimum, so neither counts as proven under the rule.
   Top-up batches needed.
4. **Whole-sentence replace: speaker identity fails the gate** (0.567-0.728 vs
   0.75). The full-segment divert to the custom template (v0.2.9) fixed the
   transcript blending (12/12 exact on the L4 validation run) but speaker
   identity at whole-sentence scope still fails closed - the gate returns
   review_required rather than shipping a bad output.
5. **Insert: 9/10 only after the pipeline's surgical repair pass** (3/10 raw
   first-pass). Repair pass is load-bearing for this category.
6. **Delete: 10/10 only via trim + best-of-N cut selection** (6/10 before the
   fix; verbatim prompting fallback covers mid-sentence deletes). Fix is in
   production code; the category depends on it.
7. **Custom instructions and humming removal reached 10/10 only via dedicated
   approaches** (style-donor generation with pitch-contour transplant;
   surgical hum removal). The Oct 31 scale-up measured the un-fixed pipeline
   at 3/17 on both - these are solved by specific machinery, and regressions
   there are the risk to watch.

### Voice enhancer

8. **Discrete sounds survive where Adobe removes them.** On the client
   recording's 10 measured inter-word windows, the supplied Adobe output is
   cleaner in 5, the AuK candidate in 3, 2 tied (>0.5 dB rule); Adobe's wins
   are windows holding breaths and movement, by 2.5-8 dB. Strength settings do
   not close this (two more variants tested Nov 16, no change) - it needs
   discrete-event handling, not more strength.
9. **Automatic strength selection picks light on 6 of 12 real inputs** (noise
   estimates 15.6-20.0 dB vs the default threshold of 12). Measured pause
   evidence (full vs light within 1.1 dB in 15 of 25 windows, max 2.5 dB)
   raises no red flag against one global full-strength mode, but adoption is
   gated on the owner's listening verdict (pages 130/131, unscored).
10. **Level anomalies observed in the Nov 9 cleanup batch** (one output very
    quiet, one at full volume) - level handling after cleanup needs the
    mastering checks exercised on every output, not only the validation set.
11. **Motorcycle residual**: on the owner-flagged clip the standard output
    leaves engine sound 10-18 dB below the original in the engine-demo windows
    (owner feedback: motorcycle still audible); the full-strength candidate
    measures near silence there, unreviewed by ear.

### Platform / scope

12. **Voice only.** The model cannot edit music or SFX (0/5 non-voice tests);
    voice extraction from a music mix works. Frame the product as a voice
    editor.
13. **License risk, not cleared**: Qwen2.5-Omni-3B is non-commercial. The
    owner said to ignore it and finish; it is recorded here, not resolved.
14. **Spec's >=99% over >=1,000 requests is undemonstrated** - the
    1,000-request acceptance run was deliberately skipped per the recorded
    decision; if the formal bar is wanted, the run is outstanding (GPU).

## What would close this deliverable

- Per-operation profile benchmark runs (GPU) populating
  `recommended_config.json`, replacing every `not_qualified`.
- Owner listening verdicts on the enhancer comparisons (pages 130/131) to
  settle the one-mode question.
- Top-up batches: replace and emotion to n>=10; speed and voice-change fix
  attempts (verbatim prompting / selection approaches).
