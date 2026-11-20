# Status detail (historical run evidence, as of 2026-11-20)

This file holds the detailed run history that used to live inline in the README.
The README keeps the current short status; this file is the evidence behind it.

## Transcript editor (correctable-transcript flow)

Transcribe once, correct the words, align, review, preview, save.

v0.6.0 (2026-11-20): the session issues worker-registry-bound evidence for both
corrected and accept-ASR-as-is spans; the worker verifies the MAC and, on the
accept-as-is path, still re-checks the cut segment against ASR (a mismatch fails
closed - correct the transcript instead). Forced alignment (pinned
wav2vec2-base-960h) measures corrected words against the audio itself; manual
audio-slice review is the labeled fallback. The 0.5s segment duration floor is
preserved: shorter selections are refused with explicit wider context options,
never silently widened. Measured-timing transplants now fit against the base cut
(previously always failed closed).

Measured on Colab L4 (2026-11-20): forced alignment 14/14 words on real speech
(mean uncalibrated fit 0.9054). That same run exposed - and v0.6.0 fixes - two
lifecycle gaps: accept-as-is spans could never reach generation, and
measured-timing transplants always failed closed.

NOT yet verified: one real representative edit through actual GPU generation.
Until that passes, the transcript editor is not a finished feature.

## Whole-segment replacement (vendor zero-shot TTS template, v0.2.9)

Bounded validation on L4 (27 Oct 2026, run w2v6-20261027T150204Z, 4 cases x 3
seeds) decoded the exact target transcript in 12/12 attempts (WER 0.0), but
speaker identity still failed the strict 0.75 similarity gate in 12/12 attempts
(0.567-0.728) under both the template and the Replace phrasing, so those runs
correctly produced no output (review_required). Scope precisely: these four
tested full-sentence cases failed speaker QA under two phrasings; whole-clip
generation is not generally unsupported (the whole-clip insert demo passed the
same gate).

## W3 scale-up evaluation (31 Oct 2026)

72 cases, L4, pinned runner, same gate as the site: speed 12/15, voice change
10/12, whisper 10/11 passing after repair; custom instructions 3/17 (systemic
speaker-identity collapse below the 0.75 gate across every phrasing tried) and
humming removal 3/17 (transcript breaks whether the hum overlaps speech or sits
in appended silence) are documented product limitations. Speed at 1.4x is
clip-specific, not a hard ceiling. Full evidence:
backend/reports/76-W3_SCALEUP_2026-10-31.md.

## Still open

Speaker fidelity at whole-sentence scope, broader localized-replace reliability
(the v0.3.5/v0.3.6 fixes are experimental and off by default), a verified
transcript-delete demo, and the remaining benchmarks. Not production-ready.
