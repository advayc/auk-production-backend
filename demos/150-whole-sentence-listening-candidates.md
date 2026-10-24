# AuK whole-sentence replacement - listening candidates (24 Oct 2026)

Three whole-sentence replacements from L4 run `retry3-20261024T215516Z` (pinned backend `41d211a`, seeds 42-44) that passed the unchanged automatic gates: exact transcript match (ASR) and speaker cosine >= 0.750. **Release gate is closed. None of these takes has human listening approval, and none is production-ready.** The automatic pass checks transcript text and speaker embedding only; it does not establish naturalness, pacing, absence of artifacts, or satisfaction of the edit request. Review binds to the exact file hashes below.

Provenance note: take 1 (case 02) and take 3 (case 07) are byte-identical to the deterministic 21 Oct bundle outputs for the same cases and seed 42 (SHA-256 verified against the review card). Take 2 (case 03, seed 43) is a new take whose exact bytes currently exist only in the run's runtime-local evidence archive (SHA-256 prefix `ceb3296a4b0e7da2`); its audio is not re-attached here until that archive is recovered.

## Take 1 - case 02, seed 42

- Original: "It is believed he had been stabbed."
- Requested: "It is reported he had been released."
- ASR heard: "It is reported. He had been released."
- Transcript exact; speaker cosine 0.785 (threshold 0.750); pause flag 0.85 s; 16.2 s generation.
- Output SHA-256: `069a2506e1ae158bf8b6b2d8680639c21c56fd0fc5df577f061c579dc6a8f789`
- Assessment: the requested words are all present and exact. Two concerns for listening: ASR inserts a sentence break after "reported" and the measured 0.85 s pause is longer than any natural pause in this corpus's source speech (max 0.62 s) - a user asking for one fluent replacement sentence may hear two choppy sentences instead.
- Verdict: **not production-ready** - listening candidate only.

**Before**

https://github.com/user-attachments/files/33915441/1-take1-case02-before.wav

**After**

https://github.com/user-attachments/files/33915443/2-take1-case02-after.wav

## Take 2 - case 03, seed 43

- Original: "Last night, Mr Robertson said he was delighted."
- Requested: "This morning, Ms Robertson said she was relieved."
- ASR heard: "This morning, Ms. Robertson said she was relieved."
- Transcript exact; speaker cosine 0.794; no pause flags at or above 0.25 s; 19.4 s generation.
- Output SHA-256 prefix: `ceb3296a4b0e7da2` (full hash in the review card; audio pending archive recovery, see provenance note).
- Assessment: the strongest automatic profile of the three - a multi-attribute change (time, title, pronoun, emotion) rendered with an exact transcript including "Ms", the word this case failed on at seed 42. Card metrics only; nothing here is heard or independently re-verified.
- Verdict: **not production-ready** - listening candidate only.

## Take 3 - case 07, seed 42

- Original: "Several other countries are also reported to be interested in the format."
- Requested: "Several other nations are also believed to be investing in the technology."
- ASR heard: "Several other nations are also believed to be investing in the technology."
- Transcript exact; speaker cosine 0.75027 - only 0.00027 above the 0.750 threshold; pause flag 0.51 s; 18.7 s generation.
- Output SHA-256: `baa66b8ddc1059e9d105e576a2b08cfcdf7c55e1c7a295155d4a353d2f40eb5c`
- Assessment: the requested multi-phrase change is delivered exactly at the text level. The borderline speaker score means voice identity is the specific risk: listen for drift away from the source speaker before anything else.
- Verdict: **not production-ready** - listening candidate only.

**Before**

https://github.com/user-attachments/files/33915446/3-take3-case07-before.wav

**After**

https://github.com/user-attachments/files/33915448/4-take3-case07-after.wav

## Extensibility: can it change an entire sentence?

Mechanically, yes - all three takes are whole-sentence replacements with multi-phrase semantic changes, not single-word swaps, and each preserves the source speaker well enough to pass the speaker screen. Consistency is the open gap: in this run only 3 of 7 requests passed the automatic gates (4 failed speaker identity), so a single request cannot yet be trusted without per-request verification, and every take still needs a human listen before it is shown as working.

## What "production-ready" still requires

1. Human listening approval of each exact take (naturalness, pacing, voice identity, intent satisfaction). Zero takes have it.
2. Reliability above the current 3/7 automatic pass rate for whole-sentence replacement.
3. The existing release items are unchanged: a held-out benchmark with at least ten real requests per operation with human intent ratings, and a commercial-use decision for the Qwen2.5-Omni-3B encoder license.

Evaluation-only; source audio LibriSpeech dev-clean (CC BY 4.0). Approval binds to the exact heard take, never to the case or the method.
