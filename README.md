# AuK voice editing backend

Upload a voice recording, choose cleanup, a transcript edit or a voice instruction, then preview and download the result as an MP3. The project brings these three modes into one Python backend and Colab workflow.

## Run it

Open the included notebook (AI_Voice_Editor_Production_Colab.ipynb) in Colab. Run setup steps 1-3 once, upload a recording in step 4 and choose an operation. For transcript edits, use steps 4b/4c to check the wording and cut, preview, then save. Disconnect and delete the runtime when finished.

For local backend setup and CPU tests (Python 3.11, FFmpeg and NumPy):

```bash
python -m pip install ./backend
python -m unittest discover -s backend/tests -v
```

## Model and modes

Tencent AuK GGUF models, with Whisper transcript checks and SpeechBrain speaker checks. The Colab uses pinned backend v0.6.6.

- **Voice Enhancer:** enhance, denoise and dereverb. Cleanup is the default and most-tested path.
- **Transcript Editor:** replace, insert or delete words. Check and correct the transcript before choosing a cut.
- **AI Voice Editor:** change emotion, voice characteristics, whisper or speed, or give a custom instruction.

## Inputs and outputs

- **Input:** a voice recording, up to 64 MB. Transcript edits also need checked wording; prompt edits need an instruction.
- **Output:** mono 48 kHz MP3 at 320 kbps. Editing and QA use an internal lossless 24 kHz WAV; resampling adds no source detail.
- **Limits:** cleanup up to 10 minutes; transcript/prompt spans up to 15 seconds in, 20 seconds out and 30 seconds combined. These span limits are application policy. Nonverbal removal is probe-bounded at 25 seconds.

## Runtime and examples

A measured 38.5-second enhance took about 6 minutes on T4 and 1.2 minutes on L4, using about 7.5/7.2 GiB peak sampled VRAM. Observed Colab rates were 1.2-1.5 compute units/hour on T4 and 1.94 on L4; rates vary. Other operations were not timed in that session.

See [test cases](demos/TEST_CASES.md) and [detailed results and limits](backend/reports/77-STATUS_DETAIL_2026-11-20.md).

## Recovery paths (2026-11-27, CPU-tested only)

- **Emotion edits:** if the raw result fails the transcript or speaker check, the worker also tries the source speech with only the raw result's pitch movement (`stylefix.py`), through the same checks. Intonation only: no whisper, no voice change. A raw result that passes the checks can still sound like the wrong emotion; only listening review catches that. Not yet tested on GPU or by listening.
- **Dependency:** the fallback needs `pyworld==0.3.5` and `setuptools<81` (pyworld imports `pkg_resources`); `pip install ./backend` installs both, the Colab notebook installs with `--no-deps` and must add them. `auk_reliability.stylefix.prosody_transplant_health()` reports whether it imports; without it the fallback fails safe and the original failure stands.
- **Localized inserts and replacements:** if the new audio does not fit the fixed interval, the worker retries with another seed. Widening the interval or switching to whole-clip scope is never automatic; the attempt record lists both as options.
- **Readback of short selections:** an experimental wider-context readback exists in code but is disabled in the production worker (constructor switch `experimental_context_readback`, default off; requests that pass `readback_context_seconds` are refused). ASR word times are approximate and it has no real-audio validation. Use the human-confirmed wider-window flow instead.
- Whole-sentence replacement words and speaker identity are still unresolved.

## Notes

This is a voice-editing prototype, not a general music/SFX editor or a production-ready service. Automatic checks and retries do not replace listening review. Quiet-source edits, whole-sentence voice preservation and broader reliability remain unresolved.

Qwen2.5-Omni-3B has a research noncommercial evaluation license; commercial use remains unresolved. Keep the attribution in [backend/SOURCES.md](backend/SOURCES.md) and the `COMMERCIAL_USE=False` safeguards.
