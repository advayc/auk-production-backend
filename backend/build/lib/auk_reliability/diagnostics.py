"""Failure-classification diagnostics.

Classification labels a failure so review is actionable. It never changes
pass/fail: a classified attempt stays failed and still requires human
review. Nothing here weakens the QA gate.
"""
from __future__ import annotations
import sys, wave
from .core import normalized_tokens, edit_distance

MAX_VARIANCE_TOKENS = 2


def outside_interval_pcm_exact(source_path, output_path, start_s, end_s, sample_rate=24000):
    """Byte-compare two mono PCM16 wavs outside [start_s, end_s)."""
    def frames(p):
        with wave.open(str(p)) as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                return None, None
            return w.getframerate(), w.readframes(w.getnframes())
    ra, a = frames(source_path); rb, b = frames(output_path)
    if ra != sample_rate or rb != sample_rate or a is None or b is None or len(a) != len(b):
        return False
    first = round(float(start_s) * sample_rate) * 2
    last = round(float(end_s) * sample_rate) * 2
    return a[:first] == b[:first] and a[last:] == b[last:]


def locate_transcript_disagreement(expected, observed, timed_words):
    """Map differing observed tokens to time ranges. timed_words: list of
    {'word','start','end'} from a word-timed transcription of the output.
    Returns a list of {'token','start','end'} for differing observed tokens,
    or None when timing cannot be aligned (no timings, count mismatch, or a
    deletion diff with no observed token to time)."""
    import difflib
    if not timed_words:
        return None
    a, b = normalized_tokens(expected), normalized_tokens(observed)
    if len(b) != len(timed_words):
        return None
    located = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        if tag == 'delete':  # expected token missing from output: no observed audio to time
            return None
        for j in range(j1, j2):
            w = timed_words[j]
            try:
                located.append({'token': b[j], 'start': float(w['start']), 'end': float(w['end'])})
            except (KeyError, TypeError, ValueError):
                return None
    return located


def classify_transcript_disagreement(qa, *, outside_exact, cut=None, timed_words=None,
                                     max_differing_tokens=MAX_VARIANCE_TOKENS):
    """Label a qa_failed attempt whose ONLY failing check is a small transcript
    disagreement while every PCM byte outside the edited interval is provably
    unchanged. The unedited_span label additionally requires word-timed proof
    that every differing observed token lies OUTSIDE the cut; without located
    proof the disagreement is 'unlocated' (uncertain), and a disagreement
    located inside the cut is labeled edited_span (consistent with a real edit
    defect). Heuristic classification only: the attempt stays qa_failed and
    still needs human review; pass/fail is unchanged."""
    if not outside_exact:
        return None
    checks = qa.get('checks') or {}
    tx = checks.get('transcript')
    if not isinstance(tx, dict) or tx.get('passed') is not False:
        return None
    for name, chk in checks.items():
        if name == 'transcript':
            continue
        if not isinstance(chk, dict) or chk.get('passed') is not True:
            return None
    expected = tx.get('expected'); observed = tx.get('observed')
    if not isinstance(expected, str) or not isinstance(observed, str):
        return None
    a, b = normalized_tokens(expected), normalized_tokens(observed)
    if not a:
        return None
    diff = edit_distance(a, b)
    if diff == 0 or diff > max_differing_tokens:
        return None
    base = {'differing_token_count': diff,
            'note': ('Heuristic classification only: the attempt stays qa_failed and still needs '
                     'human review; pass/fail is unchanged. ')}
    located = locate_transcript_disagreement(expected, observed, timed_words)
    if located is None or cut is None:
        return {**base, 'failure_class': 'transcript_disagreement_unlocated_candidate',
                'note': base['note'] + ('No word-timed transcription available to locate the '
                                        'disagreement; it may or may not be inside the edited span.')}
    c0, c1 = float(cut[0]), float(cut[1])
    if all(w['end'] <= c0 or w['start'] >= c1 for w in located):
        return {**base, 'failure_class': 'transcript_disagreement_unedited_span_candidate',
                'located_tokens': located,
                'note': base['note'] + ('All differing tokens are word-timed OUTSIDE the cut and outside '
                                        'PCM is byte-identical, consistent with transcriber variance on '
                                        'unedited audio.')}
    return {**base, 'failure_class': 'transcript_disagreement_edited_span_candidate',
            'located_tokens': located,
            'note': base['note'] + ('At least one differing token is word-timed INSIDE the cut, '
                                    'consistent with a real edit defect rather than transcriber variance.')}
