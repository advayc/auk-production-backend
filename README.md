# AuK voice editing backend

One shared backend for AI voice editing and transcript editing: a single `edit_audio(input, mode, operation, parameters)` interface with automatic output checks, bounded retries, and full attempt logging. Run the CPU regression suite with `PYTHONPATH=backend python -m unittest discover -s backend/tests -v` (Linux, Python 3.11, FFmpeg, NumPy).

## Showcase tests

[Browse all ten cases per operation](demos/TEST_CASES.md), with exact inputs, expected outputs, durations, and commands to run all 90 tests, one operation, or an individual case. [Download the test recipes as JSON](demos/showcase_test_cases.json).

[90 operation scenarios and a one-shot audio batch](demos/SHOWCASE.md): ten code tests for each of the nine operations, plus twelve batch-runner tests. Coverage includes all supported emotions, ten voice descriptions, ten speed factors, ten custom delivery styles, humming-removal targets, and varied transcript insert/replace/delete edits. Code tests use simulated inference; real demos require Colab generation and human listening. The batch runner selects ten reviewed cases per operation, records every failure, checkpoints progress, and displays before/after players.

[CPU validation](backend/reports/SHOWCASE_CPU_RESULTS.md): all 393 tests passed on [Ubuntu CI](https://github.com/advayc/auk-production-backend/actions/runs/39309582098). The local macOS run passed 392 with one Linux-only test skipped.

## Demo players

Voice editor - outputs approved by listening:

Emotion (calm):

https://github.com/user-attachments/assets/6ecd95f1-9053-4961-b010-b7d854435151

Whisper:

https://github.com/user-attachments/assets/4222c092-3e2f-4a99-8fca-22edcd3d0c8b

Custom (bored/monotone):

https://github.com/user-attachments/assets/fcf3671c-7c9a-426c-8cea-d51ea8520f74

Speed (1.5x):

https://github.com/user-attachments/assets/9c2db0c2-f16c-4259-9944-bae354e3d172

Voice (deeper delivery):

https://github.com/user-attachments/assets/d8c59d7a-d3c3-40e6-9dd1-ddf72449e957

Humming removal - tested end to end on the real runtime; automatic checks passed (final human listening check pending):

Original (hum around 12.5s):

https://github.com/user-attachments/assets/b5149dc1-c56b-4006-806c-02a0074bf707

Backend output:

https://github.com/user-attachments/assets/7d1a2b41-08a2-4bc2-b532-27d634242596

Transcript editor:

Insert - "really" after "i managed" (approved by listening):

https://github.com/user-attachments/assets/4c072330-a5d3-4885-af13-e415b552c6eb

Word replace - "better" becomes "stronger" (sound approved by listening; automatic transcript check flagged "they/there" outside the edited span):

Before:

https://github.com/user-attachments/assets/1c058fde-8229-4cf8-9936-4a8195d2087b

After:

https://github.com/user-attachments/assets/de8733a3-2d58-4616-b87a-31de54e4b989

Transcript delete is implemented but has no verified demo clip yet.

## Demo WAVs

Lossless originals of the humming, insert and replace clips, plus the other listening-approved inserts:

- ["really" after "i managed"](demos/INS1_really_after_I_managed.wav)
- ["really" after "you"](demos/INS3_really_after_you.wav)
- ["really" after "it is"](demos/INS4_really_after_it_is.wav)
- ["truly" after "accepting"](demos/INS2_truly_after_accepting.wav)
- [Humming original](demos/10-NVDEL01_original.wav) / [backend output](demos/NVDEL01_output_backend.wav)
- [Replace original](demos/LOC_before.wav) / [edited](demos/LOC_after_better_to_stronger.wav)

## Status

Implemented and tested: the editing backend, humming removal, inserts, and the word replacement above.
Still open: broader localized-replace reliability (the v0.3.5/v0.3.6 fixes are experimental and off by default), a verified transcript-delete demo, and the remaining benchmarks. Not production-ready.

## Licensing

Uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution; keep the `COMMERCIAL_USE=False` paths intact. Evaluation audio: LibriSpeech dev-clean, CC BY 4.0. Attribution lives in `backend/SOURCES.md` and must stay with the package.
