# AuK voice editing backend

One shared backend for AI voice editing and transcript editing: a single `edit_audio(input, mode, operation, parameters)` interface with automatic output checks, bounded retries, and full attempt logging. Install with `python -m pip install ./backend`, then run the CPU regression suite with `python -m unittest discover -s backend/tests -v` (Linux, Python 3.11, FFmpeg, NumPy). CI runs the same suite plus a generated-catalog consistency check on every push.

## Showcase tests

[Browse all ten cases per operation](demos/TEST_CASES.md), with exact inputs, expected outputs, durations, and commands to run all 90 tests, one operation, or an individual case. [Download the test recipes as JSON](demos/showcase_test_cases.json).

[90 operation scenarios and a one-shot audio batch](demos/SHOWCASE.md): ten code tests for each of the nine operations, plus twelve batch-runner tests. Coverage includes all supported emotions, ten voice descriptions, ten speed factors, ten custom delivery styles, humming-removal targets, and varied transcript insert/replace/delete edits. Code tests use simulated inference; real demos require Colab generation and human listening. The batch runner selects ten reviewed cases per operation, records every failure, checkpoints progress, and displays before/after players.

[CPU validation](backend/reports/SHOWCASE_CPU_RESULTS.md): the suite now holds 534 tests; latest verification 534/534 passed locally on 2026-11-20 (Linux, per-module unittest with the repo on PYTHONPATH). The dated report records the 2026-10-19 [Ubuntu CI run](https://github.com/advayc/auk-production-backend/actions/runs/39309582098) (393 tests at the time; the local macOS run passed 392 with one Linux-only test skipped).

## Status

Working and tested: the editing backend, humming removal, inserts, and localized word replacement (a word or short phrase inside a segment).

Transcript editor (correctable-transcript flow): transcribe once, correct the words, align, review, preview, save. v0.6.0 (2026-11-20) issues worker-registry-bound evidence for both corrected and accept-ASR-as-is spans, re-checks accept-as-is cuts against ASR, and keeps the 0.5s segment floor with explicit wider-context options. Measured on Colab L4: forced alignment 14/14 words on real speech. NOT yet verified: one real representative edit through actual GPU generation - until that passes, this is not a finished feature.

Reported editor results (3 Nov 2026, backend v0.4.0, automatic gates - exact transcript plus speaker match >= 0.75 - not listening verdicts): replace 7/7, insert 9/10 (3/10 first-pass, the repair pass carries it), delete 10/10 first-pass (local trim around the deleted span with join selection; verbatim prompting covers mid-sentence deletes), emotion 5/5, speed 12/15, voice change 10/12, whisper 10/11, humming removal 10/10, custom instructions 10/10; overall 83/90 (92%). Full record: [23-w4-assessment](https://advayc.github.io/auk-production-backend/23-w4-assessment.html). Caveats: replace and emotion sit below the 10-case sampling bar; speed and voice change below the 90% bar; per the 2026-11-08 correction on the record page, the speaker-match scores predate the 16k-resampling fix and speed predates rate-adherence measurement, and the runs are two backend versions behind v0.6.0. Non-voice editing (music/SFX) scored 0/10 as reported 1 Nov 2026, so the product is framed as a voice editor; pulling voice out of a music mix works.

Known limits: whole-sentence replacement still fails the strict speaker-similarity gate (12/12 attempts, so it correctly produces no output); the correctable-transcript flow has no verified GPU generation pass. Not production-ready.

Detailed run evidence: [backend/reports/77-STATUS_DETAIL_2026-11-20.md](backend/reports/77-STATUS_DETAIL_2026-11-20.md) and [backend/reports/76-W3_SCALEUP_2026-10-31.md](backend/reports/76-W3_SCALEUP_2026-10-31.md).

## Licensing

Uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution; keep the `COMMERCIAL_USE=False` paths intact. Evaluation audio: LibriSpeech dev-clean, CC BY 4.0. Attribution lives in `backend/SOURCES.md` and must stay with the package.
