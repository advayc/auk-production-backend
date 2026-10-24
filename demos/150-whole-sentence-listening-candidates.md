# AuK whole-sentence replacement - listening candidates (24 Oct 2026)

Three whole-sentence replacements from L4 run `retry3-20261024T215516Z` (pinned backend `41d211a`, seeds 42-44) that passed this run's automatic gates: exact transcript match (ASR) and speaker cosine >= 0.750. **Release gate is closed. None of these takes has human listening approval, and none is production-ready.** The automatic pass checks transcript text and speaker embedding only; it does not establish naturalness, pacing, absence of artifacts, or satisfaction of the edit request. Review binds to the exact file hashes below.

Provenance: all three takes are byte-verified (SHA-256) against the run's evidence archive (`bounded7-exfil-retry3-20261024T215516Z.tgz`, archive SHA-256 `1d6ee03f25006f13a98b8f628138b3719d8c72949ff0a10eb7c1f817200630a3`). Takes 1 and 3 are additionally byte-identical to the deterministic 21 Oct bundle outputs for the same cases and seed 42.

## Take 1 - case 02, seed 42

- Original: "It is believed he had been stabbed."
- Requested: "It is reported he had been released."
- ASR heard: "It is reported. He had been released."
- Transcript exact; speaker cosine 0.785 (threshold 0.750); pause flag 0.85 s; 16.2 s generation.
- Output SHA-256: `069a2506e1ae158bf8b6b2d8680639c21c56fd0fc5df577f061c579dc6a8f789`
- Listening checkpoints: ASR transcribes a period after "reported" that the request did not contain; transcript punctuation is not proof of an audible sentence split. The 0.85 s pause flag marks a point to check on listening. Neither is a pass/fail judgment - the human listen decides.
- Verdict: **not production-ready** - listening candidate only.

**Before**

https://github.com/user-attachments/files/33915441/1-take1-case02-before.wav

**After**

https://github.com/user-attachments/files/33915443/2-take1-case02-after.wav

## Take 2 - case 03, seed 43

- Original: "Last night, Mr Robertson said he was delighted."
- Requested: "This morning, Ms Robertson said she was relieved."
- ASR heard: "This morning, Ms. Robertson said she was relieved."
- Transcript exact, including "Ms" - the word this case failed to render at seed 42; speaker cosine 0.794; no pause flags at or above 0.25 s; 19.4 s generation. (This run's second attempt for the case; seed 42 did not pass the automatic gates.)
- Output SHA-256: `ceb3296a4b0e7da265f73100b2f8abb6471bde33d228c9bac8269e6217301c5b`
- Listening checkpoints: none flagged by the automatic screens beyond the standing requirement to hear the exact take.
- Verdict: **not production-ready** - listening candidate only.

**Before**

https://github.com/user-attachments/files/33915512/1-take2-case03-before.wav

**After**

https://github.com/user-attachments/files/33915513/2-take2-case03-after.wav

## Take 3 - case 07, seed 42

- Original: "Several other countries are also reported to be interested in the format."
- Requested: "Several other nations are also believed to be investing in the technology."
- ASR heard: "Several other nations are also believed to be investing in the technology."
- Transcript exact; speaker cosine 0.75027 against a 0.750 threshold; pause flag 0.51 s; 18.7 s generation.
- Output SHA-256: `baa66b8ddc1059e9d105e576a2b08cfcdf7c55e1c7a295155d4a353d2f40eb5c`
- Listening checkpoints: the speaker score cleared the threshold by 0.00027, a thin margin that makes voice identity a listening focus. A thin margin flags risk; it does not by itself rank one take against another.
- Verdict: **not production-ready** - listening candidate only.

**Before**

https://github.com/user-attachments/files/33915446/3-take3-case07-before.wav

**After**

https://github.com/user-attachments/files/33915448/4-take3-case07-after.wav

## Extensibility: can it change an entire sentence?

Mechanically, yes - all three takes are whole-sentence replacements with multi-phrase semantic changes, not single-word swaps, and each passed this run's speaker screen. The open question is consistency: in this run, 3 of 7 requests passed the automatic gates (4 failed speaker identity). That is one run's yield, not a measured production-wide reliability rate, and no take should be described as working without per-request verification and a human listen of the exact file.

## What "production-ready" still requires

1. Human listening approval of each exact take (naturalness, pacing, voice identity, intent satisfaction). Zero takes have it.
2. Evidence that whole-sentence replacement passes at a rate a user can rely on, beyond this run's 3/7 automatic yield.
3. The existing release items are unchanged: a held-out benchmark with at least ten real requests per operation with human intent ratings, and a commercial-use decision for the Qwen2.5-Omni-3B encoder license.

Evaluation-only; source audio LibriSpeech dev-clean (CC BY 4.0). Approval binds to the exact heard take, never to the case or the method.
