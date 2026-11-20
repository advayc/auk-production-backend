"""Acoustic forced alignment of a KNOWN (user-corrected) transcript to audio.

This is the real alignment path the correctable-transcript flow prefers: given
text the user has confirmed, derive word timings from the AUDIO ITSELF with a
CTC forced-alignment model, instead of trusting ASR words or interpolating.
It mirrors the ASR helper's isolation contract: a separate CPU-only venv with
pinned packages, a pinned model revision, a fingerprint lock, and a subprocess
script - Torch never enters the main process.

Licensing (verified 2026-11-19, sources recorded in the lock):
- Model weights: facebook/wav2vec2-base-960h, Apache-2.0 (HF model card).
  Commercial use permitted. Replaces the earlier MMS_FA candidate, whose
  CC-BY-NC-4.0 license is incompatible with Magic Hour production use.
- Code stack: transformers 4.57.3 (Apache-2.0, PyPI), torchaudio 2.9.1
  (BSD-2-Clause, pytorch/audio LICENSE), torch (BSD-style, pytorch LICENSE).
- Alignment math: torchaudio.functional.forced_align (BSD-2-Clause code).

Scope: wav2vec2-base-960h is English-only (LibriSpeech-960h). Multilingual
corrected alignment remains open; Montreal Forced Aligner (code MIT, pretrained
English acoustic models CC-BY-4.0, commercial OK with attribution; heavier
Kaldi/conda deployment) is the documented fallback, and multilingual HF
wav2vec2 checkpoints with permissive licenses are a future extension. Do NOT
reintroduce MMS_FA or the fairseq CC-BY-NC wav2vec2 bundles here.

Everything here is CPU and runs within existing compute grants; no GPU and no
paid services.
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path
from .core import EditorError, atomic_bytes, atomic_json, command, sha256_file, canonical_hash, Limits
from .core import make_venv

ALIGN_MODEL = 'facebook/wav2vec2-base-960h'
ALIGN_REVISION = '101761d6a2faad5f94e7b45b619fae09371a8ab4'
# soundfile replaces torchaudio.load: torchaudio 2.9 requires TorchCodec (+FFmpeg) for
# file decoding, verified 2026-11-19 by running this exact pinned stack. soundfile reads
# the wav/flac inputs this pipeline produces with no extra system libraries.
ALIGN_REQUIREMENTS = ['torch==2.9.1', 'torchaudio==2.9.1', 'transformers==4.57.3', 'soundfile==0.14.0']
ALIGN_LICENSE = ('Apache-2.0 model weights (facebook/wav2vec2-base-960h HF model card); '
                 'code: transformers Apache-2.0, torchaudio BSD-2-Clause, torch BSD-style. '
                 'English-only; recheck before model or scope changes.')

ALIGN_SCRIPT = r'''
import json, os, re, sys
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
import soundfile as sf
import torch, torchaudio
from transformers import Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer
torch.set_num_threads(2)

audio_path, transcript_path, output_path, model_id, revision = sys.argv[1:6]
tokenizer = Wav2Vec2CTCTokenizer.from_pretrained(model_id, revision=revision or None)
model = Wav2Vec2ForCTC.from_pretrained(model_id, revision=revision or None).eval()

data, sr = sf.read(audio_path, dtype='float32', always_2d=True)
waveform = torch.from_numpy(data.T[0:1].copy())
waveform = torchaudio.functional.resample(waveform, sr, 16000)

original = open(transcript_path, encoding='utf-8').read().strip()
# Reversible normalization only: casefold to the model's uppercase vocab and squeeze
# whitespace. Nothing is deleted. Any other character (digits, punctuation, symbols)
# is meaningful content this English char-vocab cannot place; fail closed and name it.
text = re.sub(r'\s+', ' ', original.upper()).strip()
if not text:
    print(json.dumps({'error': 'empty_transcript_after_normalization'}))
    sys.exit(3)
unsupported = sorted(set(re.findall(r"[^A-Z' ]", text)))
if unsupported:
    print(json.dumps({'error': 'unsupported_characters_for_model_vocab',
                      'unsupported': unsupported, 'original': original, 'normalized': text}))
    sys.exit(4)
ids = tokenizer(text, add_special_tokens=False)['input_ids']
unk = tokenizer.unk_token_id
if unk is not None and unk in ids:
    print(json.dumps({'error': 'unsupported_characters_for_model_vocab'}))
    sys.exit(4)

import math
with torch.inference_mode():
    logits = model(waveform).logits
log_probs = logits.log_softmax(-1).cpu()  # (1, T, C)
targets = torch.tensor([ids], dtype=torch.int32)  # (1, L)
# torchaudio 2.9 forced_align: batched in, per-frame alignment path out (label id per
# frame plus its log-probability). TokenSpan returns were removed with the 2.9 refactor.
try:
    path, frame_scores = torchaudio.functional.forced_align(log_probs, targets, blank=0)
except Exception as exc:
    print(json.dumps({'error': 'forced_align_failed', 'detail': str(exc)[:200]}))
    sys.exit(5)
path, frame_scores = path[0].tolist(), frame_scores[0].tolist()
ratio = waveform.size(1) / len(path) / 16000  # seconds per frame

words, current, scores = [], [], []
c0 = c1 = 0.0
prev_id = 0
for t, (tok_id, score) in enumerate(zip(path, frame_scores)):
    if tok_id == 0:  # CTC blank between tokens
        prev_id = 0
        continue
    label = tokenizer.convert_ids_to_tokens(tok_id)
    if label == '|':  # word delimiter
        if current:
            words.append({'word': ''.join(current), 'start': round(c0, 6), 'end': round(c1, 6),
                          'alignment_score': round(min(1.0, math.exp(sum(scores) / max(1, len(scores)))), 4)})
            current, scores = [], []
        prev_id = tok_id
        continue
    # The path holds one target token across consecutive frames; append on a token
    # RUN, not per frame. Genuine double letters return as two runs split by a blank.
    if not current:
        c0 = t * ratio
    c1 = (t + 1) * ratio
    if tok_id != prev_id:
        current.append(label)
    scores.append(score)
    prev_id = tok_id
if current:
    words.append({'word': ''.join(current), 'start': round(c0, 6), 'end': round(c1, 6),
                  'alignment_score': round(min(1.0, math.exp(sum(scores) / max(1, len(scores)))), 4)})
result = {'text': text, 'words': words, 'original': original,
          'score_semantics': 'alignment_score is an uncalibrated CTC fit score (exp of mean frame log-prob), not a correctness probability',
          'mean_alignment_score': round(sum(w['alignment_score'] for w in words) / max(1, len(words)), 4) if words else 0.0}
with open(output_path, 'w', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, allow_nan=False)
'''


def setup_aligner(root: Path, limits: Limits):
    """Isolated CPU venv holding the pinned alignment stack. Returns (align, fingerprint):
    align(audio_path, transcript_text) -> {'text', 'words': [{word,start,end,probability}], 'mean_score'}."""
    qa_root = Path(root) / 'forced-align'
    qa_root.mkdir(parents=True, exist_ok=True)
    env = qa_root / 'venv'
    py = env / 'bin/python'
    freeze_path = qa_root / 'requirements.lock.txt'
    fresh = not py.is_file()
    py = make_venv(env)
    if fresh and freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', '-r', str(freeze_path)], timeout=1800)
    if not freeze_path.is_file():
        command([str(py), '-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', *ALIGN_REQUIREMENTS], timeout=1800)
        freeze = command([str(py), '-m', 'pip', 'freeze'], timeout=120)
        freeze_path.write_text(freeze)
    script = qa_root / 'align_local.py'
    atomic_bytes(script, ALIGN_SCRIPT.encode())
    fingerprint = canonical_hash({'model': ALIGN_MODEL, 'revision': ALIGN_REVISION,
                                  'requirements': freeze_path.read_text(),
                                  'script': sha256_file(script)})
    atomic_json(qa_root / 'align.lock.json', {'model': ALIGN_MODEL, 'revision': ALIGN_REVISION,
                                              'fingerprint': fingerprint, 'license': ALIGN_LICENSE})

    def align(audio_path, transcript_text: str) -> dict:
        fd, name = tempfile.mkstemp(suffix='.txt', dir=qa_root)
        os.close(fd)
        text_path = Path(name)
        out = qa_root / (name + '.json')
        try:
            text_path.write_text(transcript_text)
            command([str(py), str(script), str(Path(audio_path).resolve()), str(text_path), str(out),
                     ALIGN_MODEL, ALIGN_REVISION], timeout=limits.asr_timeout)
            value = json.loads(out.read_text())
            if not isinstance(value.get('words'), list) or not value['words']:
                raise EditorError('alignment_failed', 'Forced alignment returned no words.')
            return value
        finally:
            text_path.unlink(missing_ok=True)
            out.unlink(missing_ok=True)

    return align, fingerprint
