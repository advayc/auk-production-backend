# AuK real90 demo

Two before/after examples from the real90 test set. Both were heard and approved in the user's listening review on Oct 20. The After players are playback encodes (AAC) of the exact approved takes. Nothing else is presented as working: all broader results are held in the test records until they qualify.

## Approved by user listening review (Oct 20)

### 1. Replace 'sold out' with 'available'.
`replace-01` · target transcript: "The show is available, like the others in the run."
CPU repair v8 (Oct 20): low-frequency thump removed (140 Hz zero-phase filter on the event span) and the flagged 0.23 s dead-air gap cut (10 ms crossfades; tail time-shifted 0.24 s). Output transcript matches the target exactly; speaker cosine 0.922; defect screen clean. Approved take; player is a playback encode as noted above.

**Before**

https://github.com/user-attachments/assets/34165c68-3942-4bd0-b614-874a9aac6f85

**After**

https://github.com/user-attachments/assets/fd82f044-f62c-4bc1-91e7-40935e0ad3ed

### 2. Replace 'Several other' with 'Many other'.
`replace-06` · target transcript: "Many other countries are also reported to be interested in the format."
Regenerated Oct 20 (Phase C, seed 44): the duplicated "other" is gone. Output transcript matches the target exactly; speaker cosine 0.909; defect screen clean. Approved take; the After player is a playback encode (AAC) of the reviewed file, with decoded correspondence verified (PCM correlation 0.999884, lossy encode).

**Before**

https://github.com/user-attachments/assets/99b8064c-32e3-48ac-af6e-62458aae0c42

**After**

https://github.com/user-attachments/assets/6a3eb5d2-dba6-4fae-84a4-81cf75e33c7f

## Not shown

**Whole-sentence replacement - unproven.** A bounded 7-case test on Oct 21 (L4, vendor zero-shot same-voice template per AuK cookbook 1.1, one attempt per case, seed 42) generated all 7 clips technically; 2 of 7 passed both automated gates (exact transcript match and speaker cosine >= 0.75; one pass sits at 0.750270009, effectively at the threshold). Four cases missed the speaker-similarity gate and one missed the transcript gate. No human has heard these clips, and they are not production candidates.

**Style transfer (whisper, custom style, voice characteristics).** Current evidence does not establish that outputs match the requested style; screening cannot judge that.

**Everything else.** Screen-flagged repair candidates (replace-03, insert-03, emotion-05, nonverbal_remove-09, replace-08, nonverbal_remove-01, nonverbal_remove-05, replace-05, delete-01, delete-05, insert-06) and the remaining screened entries stay in the test records. Most entries previously shown here had not been heard by a human.

## Method note

Automated screens flag possible gaps, clicks, clipping, and repeated words; ASR transcripts and speaker-embedding scores are heuristics. Current evidence does not establish naturalness or intent satisfaction for unheard clips. Approval binds to the exact heard take, not to the case or the method. Evaluation-only, noncommercial; source audio LibriSpeech dev-clean (CC BY 4.0).
