# AuK voice editing backend

One shared backend for AI voice editing and transcript editing: a single `edit_audio(input, mode, operation, parameters)` interface with automatic output checks, bounded retries, and full attempt logging. Install with `python -m pip install ./backend`, then run the CPU regression suite with `python -m unittest discover -s backend/tests -v` (Linux, Python 3.11, FFmpeg, NumPy). CI runs the same suite plus a generated-catalog consistency check on every push.

## Showcase tests

[Browse all ten cases per operation](demos/TEST_CASES.md), with exact inputs, expected outputs, durations, and commands to run all 90 tests, one operation, or an individual case. [Download the test recipes as JSON](demos/showcase_test_cases.json).

[90 operation scenarios and a one-shot audio batch](demos/SHOWCASE.md): ten code tests for each of the nine operations, plus twelve batch-runner tests. Coverage includes all supported emotions, ten voice descriptions, ten speed factors, ten custom delivery styles, humming-removal targets, and varied transcript insert/replace/delete edits. Code tests use simulated inference; real demos require Colab generation and human listening. The batch runner selects ten reviewed cases per operation, records every failure, checkpoints progress, and displays before/after players.

[CPU validation](backend/reports/SHOWCASE_CPU_RESULTS.md): the suite now holds 472 tests; latest verification 472/472 passed locally on 2026-11-16 (Linux, NumPy 2.2.6). The dated report records the 2026-10-19 [Ubuntu CI run](https://github.com/advayc/auk-production-backend/actions/runs/39309582098) (393 tests at the time; the local macOS run passed 392 with one Linux-only test skipped).

## Status

Implemented and tested: the editing backend, humming removal, inserts, and localized word replacement.
Supported replacement scope: localized span replacement (a word or short phrase inside a segment) is the demonstrated path. A replacement spanning the entire segment diverts to the vendor zero-shot TTS template (v0.2.9): bounded validation on L4 (27 Oct 2026, run w2v6-20261027T150204Z, 4 cases x 3 seeds) decoded the exact target transcript in 12/12 attempts (WER 0.0), but speaker identity still failed the strict 0.75 similarity gate in 12/12 attempts (0.567-0.728) under both the template and the Replace phrasing, so those runs correctly produced no output (review_required). Scope precisely: these four tested full-sentence cases failed speaker QA under two phrasings; whole-clip generation is not generally unsupported (the whole-clip insert demo passed the same gate).
W3 scale-up evaluation (31 Oct 2026, 72 cases, L4, pinned runner, same gate as the site): speed 12/15, voice change 10/12, whisper 10/11 passing after repair; custom instructions 3/17 (systemic speaker-identity collapse below the 0.75 gate across every phrasing tried) and humming removal 3/17 (transcript breaks whether the hum overlaps speech or sits in appended silence) are documented product limitations. Speed at 1.4x is clip-specific, not a hard ceiling. Full evidence: backend/reports/76-W3_SCALEUP_2026-10-31.md.
Still open: speaker fidelity at whole-sentence scope, broader localized-replace reliability (the v0.3.5/v0.3.6 fixes are experimental and off by default), a verified transcript-delete demo, and the remaining benchmarks. Not production-ready.

## Licensing

Uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution; keep the `COMMERCIAL_USE=False` paths intact. Evaluation audio: LibriSpeech dev-clean, CC BY 4.0. Attribution lives in `backend/SOURCES.md` and must stay with the package.
