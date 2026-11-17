---
id: rb7-recovery-20261117
type: recovery-record
---

# RB7 run recovery and artifact provenance (2026-11-17)

## What RB7 is
Matched full-strength (wet 1.0) vs light-strength (wet 0.35) enhance pairs on the 5
previously unmeasured light-band inputs (cr7 15.71, quote 16.19, happy 18.78,
tucci 19.98, 2min 15.61 est_snr dB). The 6th light-band input (client recording,
15.65) was already covered by earlier runs. Exploratory evidence for the
strength-selection retune hypothesis; no threshold decision implied. Quality
status: UNSCORED - user listening gate pending.

## Run
- GPU run 2026-11-17 04:39-05:14 UTC on Colab T4. 10/10 technical_success
  (5 inputs x 2 strengths). All signal-integrity checks passed.
- The Drive-upload cell failed pre-auth (modal not clicked in time), so the run
  completed Drive-free with artifacts only on the VM disk.

## Crash and recovery
- ~00:46 EST a "session crashed" dialog appeared. Initial read: artifacts lost.
  That read was WRONG: the crash killed only the kernel. Terminal (tmux) evidence:
  uptime 1:35 continuous, disk 12G used, `/content/rbench7/` fully intact
  (10 WAVs, manifest, measurements, outputs zip, 10 request dirs).
- Recovery path: Runtime > Restart session (fresh kernel, same VM, /content
  persists), re-ran the idempotent RB7-UPLOAD cell. Drive auth completed with no
  popup - the 00:44 account-level OAuth consent is remembered. Cell finished in
  47 s.
- Lesson recorded: a Colab crash dialog is NOT evidence of VM death or billing
  stop; verify via Terminal (df/uptime/ls) and Manage sessions.

## Durable artifacts (Drive folder 13KWWt2cqMKZVLbR6JR51_4Qz63zS95LM, verified via API listing 00:55 EST)
- rb7-{2min,cr7,happy,quote,tucci}-enh-{full-w100,light-w035}.wav (10 files, 1.86-6.12 MB)
- rb7-manifest.json (128,094 bytes) - committed here verbatim
- rb7-window-measurements.json (2,356 bytes) - committed here verbatim
- 10 per-request attempts.json (hash-named, 14-30 KB)

## Teardown
Runtime > Disconnect and delete runtime, then Manage sessions showed
"No active sessions" (screenshot-verified 00:55 EST). GPU billing stopped.
No rerun needed ($0). Had one been needed: ~35 min T4 + setup, within the
owner's existing-credits authority (Oct 28, "as many credits as needed").

## Provenance note on the measurements JSON
The committed rb7-window-measurements.json is the Drive-original 2,356-byte file.
An earlier 1,183-byte terminal-screenshot transcription (whitespace-stripped for
screen fitting) was reconciled against it: identical except one misread digit
(happy full-strength window 5: -22.2 in the original, transcribed as -22.7).
The Drive original is authoritative; the transcription is superseded.

## Save-path repair (validated pattern, now wired)
Drive-free GPU run + separate idempotent upload cell (240 s bounded auth thread,
per-file printed IDs) + independent Drive API listing verification. For future
runs: auth-first inside the run cell with per-output upload as each WAV finishes,
this upload cell as the safety net, and a dummy-artifact CPU preflight of the
upload cell before any GPU work.

Wired 2026-11-17 (no GPU): `benchmark/colab_durable_save.py` implements the
pattern as reusable code - `require_drive()` (auth or raise; no Drive-free
continuation, unlike the RB6/RB7 cells where upload() silently no-opped when
auth failed), `DurableSaver.upload()` (immediate per-artifact upload with
Drive-side size read-back, retry x3, raise on failure), and
`DurableSaver.preflight()` (upload + verify + delete a tiny probe before heavy
compute). Module logic unit-verified locally (success / size-mismatch-retry /
transient-retry / preflight-delete, 4/4). The same Drive API path was
live-validated on a fresh CPU-only runtime (PREFLIGHT_UPLOAD_OK above). The
exec notebook carries a DURABLE SAVE TEMPLATE cell that future run cells use;
RB5/RB6/RB7 cells are left untouched as historical record.
