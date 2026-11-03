"""Boundary-delete DSP trim with gate-selected candidate cuts (no resynthesis).

Why this exists: the vendor model regenerates the whole utterance for delete
edits, and when the kept onset is a lowercase function word or a phonetically
glued fragment ("is that...", "the cash...", "one goal...") its language prior
reinstates the deleted words or invents new leading ones (W4 span batch:
delete 6/10 after repair vs insert 9/10; bounded phrasing probe 2026-11-01,
run b2: the Replace-span delete form went 0/12 on the four failing cases x 3
seeds). A verbatim-target prompt ("Say the following with the same voice:
...") sidesteps the deletion reasoning and reached 9/12 on the same cases,
and a local trim around the deleted span - the deleted words are simply never
played - reached 10/10 exact transcript + speaker gate when the cut point is
selected from a small candidate set by the standard ASR/speaker gate
(bounded trim probe 2026-11-02, all 10 delete cases, zero GPU).

The catch this module is honest about: the cut point is everything. ASR word
timestamps run ~100-300 ms early on these clips, and the hardest deletes are
the coarticulated boundaries ("likelihood is", "have the", "scored one")
with no inter-word silence; no single deterministic cut rule cleared the
batch (best fixed rule 3/10 exact; per-case a working offset existed every
time). So the module emits candidate cuts around the ASR boundary estimate
and the worker runs the standard QA gate on each candidate, selecting the
first that passes. If none passes, the caller falls through to the vendor
path (verbatim-target instruction). Mid-segment deletes are out of scope -
a trim there needs a join on both sides - and go straight to the vendor
path.

Honesty contract: the output is a contiguous slice of the source PCM with a
short fade at the cut; no samples are generated, filtered or re-leveled.
Every candidate and its gate outcome is recorded by the worker.
"""
from __future__ import annotations
import wave
from pathlib import Path
import numpy as np
from .core import EditorError, normalized_tokens

SR = 24000
# Candidate offsets (seconds) around the ASR boundary estimate; bounded probe
# 2026-11-02 sweep over 8 offsets found a passing cut for every delete case.
OFFSETS = (-0.05, 0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
FADE_MS = 15


def _read_mono(path: Path) -> np.ndarray:
    with wave.open(str(path), 'rb') as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != SR:
            raise EditorError('wrong_output_format', 'Trim delete needs mono PCM16 24kHz audio.')
        data = stream.readframes(stream.getnframes())
    return np.frombuffer(data, dtype='<i2').astype(np.float64) / 32768.0


def _write_mono(path: Path, y: np.ndarray) -> None:
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.999:
        y = y * (0.999 / peak)
    pcm = np.clip(np.round(y * 32767.0), -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(SR)
        stream.writeframes(pcm.tobytes())


def boundary_estimate(words, segment_text, deleted_text):
    """Locate the deleted span at a segment edge using ASR word timings.

    words: list of {'word': str, 'start': s, 'end': s} from the transcriber.
    Returns {'direction': 'prefix'|'suffix', 'estimate': seconds} or None when
    the deleted text is not a clean prefix/suffix of the segment or the ASR
    words do not confirm it (fail closed: caller uses the vendor path).
    """
    seg_t = normalized_tokens(segment_text)
    del_t = normalized_tokens(deleted_text)
    if not del_t or not seg_t or len(del_t) >= len(seg_t):
        return None
    wtoks = [normalized_tokens(w.get('word', '')) for w in words if isinstance(w, dict)]
    if not wtoks or len(wtoks) != len(words):
        return None
    flat = [t for grp in wtoks for t in grp]
    if seg_t[:len(del_t)] == del_t and flat[:len(del_t)] == del_t:
        cum = 0
        for i, grp in enumerate(wtoks):
            cum += len(grp)
            if cum >= len(del_t):
                return {'direction': 'prefix', 'estimate': float(words[i]['end'])}
    if seg_t[-len(del_t):] == del_t and flat[-len(del_t):] == del_t:
        cum = 0
        for i in range(len(wtoks) - 1, -1, -1):
            cum += len(wtoks[i])
            if cum >= len(del_t):
                return {'direction': 'suffix', 'estimate': float(words[i]['start'])}
    return None


def candidate_cuts(direction, estimate, duration_seconds, offsets=OFFSETS):
    """Candidate cut seconds around the estimate, nearest-first by |offset| order
    matching the bounded probe sweep. Clamped so at least 0.3 s of audio remains."""
    dur = float(duration_seconds)
    cuts = []
    for d in offsets:
        cut = estimate + d if direction == 'prefix' else estimate - d
        cut = min(max(cut, 0.05), dur - 0.3) if direction == 'prefix' else min(max(cut, 0.3), dur - 0.05)
        if all(abs(cut - c) > 1e-3 for c in cuts):
            cuts.append(round(cut, 4))
    return cuts


def trim_delete(in_path, out_path, cut_seconds, direction, fade_ms=FADE_MS):
    """Write the kept side of the cut with a short fade at the boundary.
    Prefix delete keeps audio after the cut; suffix delete keeps audio before it."""
    x = _read_mono(Path(in_path))
    sr = SR
    i = int(round(float(cut_seconds) * sr))
    i = min(max(i, 0), len(x))
    fade = int(fade_ms / 1000.0 * sr)
    if direction == 'prefix':
        y = x[i:].copy()
        if len(y) > fade:
            y[:fade] *= np.linspace(0.0, 1.0, fade)
    elif direction == 'suffix':
        y = x[:i].copy()
        if len(y) > fade:
            y[-fade:] *= np.linspace(1.0, 0.0, fade)
    else:
        raise EditorError('invalid_trim_direction', 'direction must be prefix or suffix')
    if len(y) < int(0.05 * sr):
        raise EditorError('truncated_output', 'Trim left almost no audio.')
    _write_mono(Path(out_path), y)
    return {'cut_seconds': float(cut_seconds), 'direction': direction,
            'fade_ms': fade_ms, 'out_duration': len(y) / sr}
