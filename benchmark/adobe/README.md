# Adobe Enhance Speech head-to-head inputs

Drop Adobe-enhanced versions of the 20 `benchmark/eval-v1/` clips here (or into
`/content/adobe_in` on Colab) and the ENH-A cells in the production Colab
notebook score them with the exact harness that produced the 2026-11-03 eval
page: same ASR (faster-whisper base.en), same references (`benchmark/clean-vctk/`),
same WER/ESTOI/band math (`benchmark/score_eval.py`).

## Naming

Each filename must identify its eval-v1 clip. Either works:

- the full clip stem: `enh-eval-p363_029-mic1-noisy-cafe-10db.wav`
- the speaker-mic token plus a condition hint: `p363_029-mic1 cafe enhanced.wav`

Matching is case-insensitive and ignores separators. A file that matches zero
or several clips is listed and skipped, never guessed. Adobe's own download
names (e.g. `... (Enhanced).wav`) match as long as the token survives.

## What the harness emits

- per-clip WER vs the clean reference, aligned ESTOI, and band stats
  (energy above 8 kHz + 95% rolloff) documenting Adobe's ~9.5 kHz bandwidth cap
- a side-by-side table against the pinned 2026-11-03 numbers
  (AuK 16/1.0/-1.0: 0.130 mean WER; MossFormer2: 0.203; input: 0.262)
- blind A-B listening pairs (`pair-NN-A/B.wav`, level-matched to -16 LUFS)
  with the key sealed in `ab/mapping.json`

Published Adobe reference point (third-party, different corpus - context only,
not comparable to our WER): cleanvoice.ai speech-enhancement benchmark lists
Adobe Podcast Enhance at 17.1% WER, DNSMOS 3.08, speaker similarity 0.945.
