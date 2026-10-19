# AuK voice editing backend

One shared backend for AI voice editing and transcript editing: a single `edit_audio(input, mode, operation, parameters)` interface with automatic output checks, bounded retries, and full attempt logging. 291 code tests passing (`cd backend && python -m unittest discover`).

## Audio demos

**Humming removal** - tested end to end on the real runtime; automatic checks passed (final human listening check pending):

- [Original](demos/10-NVDEL01_original.wav) (hum around 12.5s) / [Backend output](demos/NVDEL01_output_backend.wav)

**Inserts** - a word added mid-sentence; all four outputs approved by listening:

- ["really" after "i managed"](demos/INS1_really_after_I_managed.wav)
- ["really" after "you"](demos/INS3_really_after_you.wav)
- ["really" after "it is"](demos/INS4_really_after_it_is.wav)
- ["truly" after "accepting"](demos/INS2_truly_after_accepting.wav)

**Word replacement** - "better" replaced with "stronger"; sound approved by listening (automatic transcript check flagged "they/there" outside the edited span):

- [Original](demos/LOC_before.wav) / [Edited](demos/LOC_after_better_to_stronger.wav)

## Status

Implemented and tested: the editing backend, humming removal, inserts, and the word replacement above.
Still open: broader localized-replace reliability (the v0.3.5/v0.3.6 fixes are experimental and off by default) and the remaining benchmarks. Not production-ready.

## Licensing

Uses Qwen2.5-Omni-3B under a research noncommercial evaluation license. Commercial use requires a separate license and is unresolved. Redistribution requires attribution; keep the `COMMERCIAL_USE=False` paths intact. Evaluation audio: LibriSpeech dev-clean, CC BY 4.0. Attribution lives in `backend/SOURCES.md` and must stay with the package.
