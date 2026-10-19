# One-shot showcase batch

[Browse all ten cases for every operation](TEST_CASES.md), including exact test
requests, expected outputs, duration targets, and commands to run them.

The showcase covers ten cases for each operation, using the normal backend and
unchanged QA gates. Each case gets one model attempt. Failed cases stay in the
report; automatic checks never replace human listening.

| Mode | Operation | Cases | Examples covered by code tests |
|---|---|---:|---|
| Voice | Emotion | 10 | Calm, happy, sad, angry, fearful, surprised, disgusted, excited |
| Voice | Voice characteristics | 10 | Low, airy, raspy, resonant, breathy, crisp, rounded, light, full, nasal |
| Voice | Whisper | 10 | Different checked transcripts, content and identity preservation |
| Voice | Speed | 10 | 0.5x, 0.6x, 0.75x, 0.8x, 0.9x, 1.1x, 1.25x, 1.5x, 1.75x, 2x |
| Voice | Custom | 10 | Confident, monotone, gentle, energetic, hesitant, reassuring, formal, conversational, dramatic, understated |
| Voice | Nonverbal removal | 10 | Humming removal with different shortened duration targets |
| Transcript | Replace | 10 | Single words, multiword phrases, beginning and end of utterance, longer replacement |
| Transcript | Insert | 10 | Before/after anchors, single words, multiword phrases, sentence boundaries |
| Transcript | Delete | 10 | Single words, multiword phrases, beginning/middle/end of utterance |

The 90 automated scenarios exercise real FFmpeg preparation, duration checks,
semantic-QA routing, and saved result artifacts with a simulated model and canned
ASR. They do **not** generate voice demos or establish model quality. Twelve
additional tests cover selection, missing coverage, source diversity, immutable
manifests, and one-shot execution rules.

Run locally from the repository root (Python 3.11, FFmpeg/FFprobe):

```sh
python -m pip install ./backend numpy==2.2.6
python -m unittest discover -s backend/tests -v
```

The complete process-ownership suite targets Linux (`/proc`). GitHub Actions runs
the full suite on Ubuntu. The showcase operation tests also run on macOS.

## Generate the real audio batch

1. Restore the reviewed corpus and prepare the model, ASR and speaker QA in the
   canonical Colab. For an L4, select the existing `source_build` runtime path;
   the T4 prebuilt is restricted to SM75. Preserve `COMMERCIAL_USE=False`.
2. Install this checkout's `backend`, which includes `auk_reliability.showcase`.
   The notebook's embedded archive predates this helper; running P1 alone will
   not install it. No embedded package or editing semantics changed here.
3. Supply a schema-version-1 manifest with checksum-pinned recordings, verified
   rights and transcripts, audited labels, and at least ten distinct requests
   per operation. Use `backend/auk_reliability/workflow.py` for the normal corpus
   format. Nonverbal removal needs actual annotated sounds and explicit shorter
   targets; do not invent these from clean speech. The general dataset validator
   currently restricts this showcase to sources up to 15 seconds, including
   nonverbal sources; the longer NVDEL demo is outside this manifest workflow.
4. Set `SHOWCASE_MANIFEST` and a fresh `SHOWCASE_ROOT` in
   [showcase_colab.py](showcase_colab.py), then run it in the prepared notebook:

   ```python
   %run -i /content/auk-production-backend/demos/showcase_colab.py
   ```

The helper freezes exactly 90 requests before generation. Selection prefers
different recordings and speakers, then different edits; seed/profile-only
copies do not count. A missing operation or insufficient cases stops the batch
before inference. The supplied manifest controls the actual demo wording and
style settings; the table describes the separate automated scenario coverage.

`cases.json`, the output WAVs, per-attempt logs, `requests.csv`, `summary.json`,
and `REPORT.md` are checkpointed to Drive. The final cell renders before/after
players. Failed requests keep diagnostic artifacts and never get an approved
output substituted. This is a small showcase, not the 1,000-request acceptance
benchmark; its acceptance gate always remains false.

For an interrupted batch, restore the same source files, `cases.json`, requests,
and run directory and set `RESUME_SHOWCASE=True`. The existing acceptance
harness verifies runtime/configuration and artifact hashes before resuming.
Completed failures remain recorded rather than being silently retried.

Listen to every selected output for correct words, the requested effect, speaker
identity where applicable, naturalness, and seams. Save reviews with the existing
`workflow.save_review` helper; reviews are bound to the exact output hash.
Run `acceptance.refresh_reviews` to update the report after listening.

Generation of a new 90-clip batch is pending; the WAV links in the main README
refer to earlier runs. Test fixtures are not portfolio audio demos.
