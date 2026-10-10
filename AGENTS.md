# AGENTS.md

AuK voice editing backend, distribution copy of the org Colab build. The notebook is canonical; do not treat this repo as an editing destination.

## Layout

- `AI_Voice_Editor_Production_Colab.ipynb`: supported runner. Open the org Colab, run cells P1 to P4 in order on a T4. The notebook restores the same 0.3.0 package this repo carries (embedded archive sha-verified against the repo code).
- `backend/auk_reliability/`: the `auk-reliability` package. Entry point: `edit_audio()` in `worker.py`. Acceptance harness in `acceptance.py`.
- `backend/tests/`: unittest suite, 175 tests.
- `backend/datasets/bootstrap/manifest.candidate.json`: checksum-pinned evaluation manifest (LibriSpeech dev-clean, CC BY 4.0).
- `backend/reports/`: dataset audit and per-operation profile recommendations (currently `not_qualified`).

## Commands

- Install (CPU only): `python -m pip install ./backend` (Python 3.11-3.13)
- Test: `python -m unittest discover -s backend/tests -v`
- CLI: `python -m auk_reliability.cli validate-dataset | refresh-reviews | run-suite`
- GPU generation runs through the Colab only; model weights (~15 GB) download at runtime from pinned revisions.

## Rules for changes

- Do not change `edit_audio` semantics without adding a regression test. Every production bug becomes a test.
- The owner-verified interval is a hard preservation boundary for localized edits. Never let a cut, pad, or crossfade touch samples outside it, and never shift the tail: frame-exact duration or fail closed.
- Fixed-duration segment policy: max 15s source interval, 20s output. Longer clips are unsupported.
- Automatic QA passing is not naturalness. Keep the human listening step in any acceptance flow.
- Qwen2.5-Omni-3B ships under a research noncommercial evaluation license; commercial use requires a separate license and redistribution requires attribution. Keep `COMMERCIAL_USE=False` paths intact. See `backend/SOURCES.md`.
- `backend/SOURCES.md` attribution must stay with the dataset.
- v0.3.0 is a candidate: CPU 175 tests pass. GPU evidence so far comes from a mixed v0.2.9-base + apparent-0.3.0-overlay build (module hash unrecorded), not the canonical 0.3.0 tree; on that build the current localized test case fails closed by design and the one paced attempt failed automatic QA. Do not describe localized edits as working until a contract-preserving pass on the canonical 0.3.0 build and human listening review exist. v0.2.9's L4 results apply to 0.2.9 code only.
