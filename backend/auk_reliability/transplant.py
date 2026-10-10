"""ASR-guided generative transplant for transcript_editor inserts.

Why this exists: whole-clip insert generations often speak the edited phrase
correctly and then restart the sentence from the anchor ("I managed really,
I managed to take her ... by surprise, by surprise."). The words the user
asked for are present and cleanly spoken; the defect is the duplicated
restart. The transplant keeps only the cleanly spoken [anchor + insert]
phrase span from the full-context generation and splices it into the
original recording in place of the anchor, so the rest of the sentence
stays the original audio.

Honesty contract:
- Outside the replaced span the original PCM is preserved byte-exact. The
  tail may shift in time when the patch length differs from the source
  span; its samples are identical, only their position moves.
- Word spans come from ASR word timestamps with explicit padding. A span
  that is missing or occurs more than once fails closed with an
  EditorError; nothing is guessed.
- A transplant candidate must pass the same automatic QA gates as a direct
  generation before it is selected. An exact ASR transcript match on the
  candidate proves word correctness only, never naturalness, join
  inaudibility, or phrase-level voice match; human listening review is
  still required (the result remains review-pending).
"""
from __future__ import annotations
import array, wave
from pathlib import Path
from .core import EditorError, Limits, normalized_tokens, measure_signal, sha256_file

SAMPLE_RATE = 24000
DEFAULT_PAD_PRE_SECONDS = 0.06
DEFAULT_PAD_POST_SECONDS = 0.12
DEFAULT_CROSSFADE_MS = 25


def _read_mono(path: Path) -> array.array:
    with wave.open(str(path)) as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2 or stream.getframerate() != SAMPLE_RATE:
            raise EditorError('wrong_output_format', 'Transplant needs mono PCM16 24kHz audio.')
        return array.array('h', stream.readframes(stream.getnframes()))


def _write_mono(path: Path, samples) -> None:
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(SAMPLE_RATE)
        stream.writeframes(array.array('h', samples).tobytes())


def _word_tokens(observed: dict) -> list[dict]:
    words = observed.get('words') if isinstance(observed, dict) else None
    if not isinstance(words, list):
        raise EditorError('transplant_alignment_unavailable', 'ASR did not return word timestamps; cannot align a transplant safely.')
    out = []
    for entry in words:
        tokens = normalized_tokens(str(entry.get('word', '')))
        if not tokens:
            continue
        start, end = entry.get('start'), entry.get('end')
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not end > start >= 0:
            raise EditorError('transplant_alignment_unavailable', 'ASR word timestamps are missing or invalid.')
        out.append({'token': ' '.join(tokens), 'start': float(start), 'end': float(end)})
    if not out:
        raise EditorError('transplant_alignment_unavailable', 'ASR returned no words.')
    return out


def _find_unique_span(tokens: list[str], phrase: list[str], label: str) -> tuple[int, int]:
    n = len(phrase)
    hits = [i for i in range(len(tokens) - n + 1) if tokens[i:i + n] == phrase]
    if len(hits) != 1:
        raise EditorError('transplant_span_ambiguous',
                          f'{label} must occur exactly once for a safe transplant; found {len(hits)}.')
    return hits[0], hits[0] + n


def _ramp_join(head_last: int, segment: list[int], tail_first: int, crossfade: int) -> list[int]:
    """Smooth the patch edges toward the boundary sample values. Only patch
    samples are modified, so the kept original audio stays byte-exact."""
    segment = list(segment)
    m = min(crossfade, len(segment) // 2)
    for k in range(m):
        t = (k + 1) / (m + 1)
        segment[k] = round(head_last * (1 - t) + segment[k] * t)
        segment[len(segment) - 1 - k] = round(tail_first * (1 - t) + segment[len(segment) - 1 - k] * t)
    return segment


def _flat_word_tokens(observed: dict) -> list[dict]:
    """One entry per normalized token; multi-token ASR words are split with
    linearly interpolated timestamps so indices align with
    normalized_tokens(full text)."""
    flat = []
    for entry in _word_tokens(observed):
        parts = entry['token'].split(' ')
        if len(parts) == 1:
            flat.append(entry)
            continue
        step = (entry['end'] - entry['start']) / len(parts)
        for k, part in enumerate(parts):
            flat.append({'token': part, 'start': entry['start'] + k * step,
                         'end': entry['start'] + (k + 1) * step})
    return flat


def _splice_replace(source_samples, cut0: int, cut1: int, patch: list[int],
                    crossfade: int, output: Path) -> None:
    """Replace source[cut0:cut1] with patch (length may differ). Audio outside
    the span stays byte-exact; the tail is time-shifted, never altered."""
    head = source_samples[:cut0].tolist()
    tail = source_samples[cut1:].tolist()
    patch = _ramp_join(head[-1] if head else 0, list(patch), tail[0] if tail else 0, crossfade)
    _write_mono(output, head + patch + tail)
    saved = _read_mono(output).tolist()
    if saved[:cut0] != head:
        raise EditorError('outside_segment_changed', 'Transplant altered audio before the replaced span.')
    if tail and saved[len(saved) - len(tail):] != tail:
        raise EditorError('outside_segment_changed', 'Transplant altered audio after the replaced span.')


def insert_transplant(source: Path, generation: Path, transcriber, anchor: str, text: str,
                      position: str, output: Path, *, pad_pre: float = DEFAULT_PAD_PRE_SECONDS,
                      pad_post: float = DEFAULT_PAD_POST_SECONDS,
                      crossfade_ms: int = DEFAULT_CROSSFADE_MS) -> dict:
    """Build an insert candidate: generation's [anchor+text] (after) or
    [text+anchor] (before) span replaces source's [anchor] span.

    Fails closed with EditorError on any ambiguity. Returns span metadata
    for the attempt record."""
    if position not in ('before', 'after'):
        raise EditorError('transplant_span_ambiguous', 'Insert transplant needs position before|after.')
    anchor_tokens = normalized_tokens(anchor)
    insert_tokens = normalized_tokens(text)
    if not anchor_tokens or not insert_tokens:
        raise EditorError('transplant_span_ambiguous', 'Anchor and insert text must be nonempty.')
    source_observed = transcriber(Path(source))
    generation_observed = transcriber(Path(generation))
    source_words = _word_tokens(source_observed)
    generation_words = _word_tokens(generation_observed)
    source_tokens = [w['token'] for w in source_words]
    generation_tokens = [w['token'] for w in generation_words]
    phrase = anchor_tokens + insert_tokens if position == 'after' else insert_tokens + anchor_tokens
    gs = _find_unique_span(generation_tokens, phrase, 'The anchor+insert phrase in the generation')
    ss = _find_unique_span(source_tokens, anchor_tokens, 'The anchor in the source')
    duration = len(_read_mono(generation)) / SAMPLE_RATE
    prev_end = generation_words[gs[0] - 1]['end'] if gs[0] else 0.0
    next_start = generation_words[gs[1]]['start'] if gs[1] < len(generation_words) else duration
    # Join padding carries room tone only - never a neighboring generation
    # word's audio. A sentence-restart onset inside pad_post contaminated a
    # salvage join and the following source word was lost at the seam.
    # ...but never let a neighbor clamp truncate the phrase words themselves
    # (overlapping ASR word times): the anchor+insert span stays fully covered.
    g0 = min(max(0.0, generation_words[gs[0]]['start'] - pad_pre, prev_end), generation_words[gs[0]]['start'])
    g1 = max(min(duration, generation_words[gs[1] - 1]['end'] + pad_post, next_start), generation_words[gs[1] - 1]['end'])
    src_dur = len(_read_mono(source)) / SAMPLE_RATE
    s_prev_end = source_words[ss[0] - 1]['end'] if ss[0] else 0.0
    s_next_start = source_words[ss[1]]['start'] if ss[1] < len(source_words) else src_dur
    # The cut never eats a neighboring source word: when words run together,
    # pad_post would otherwise amputate the next word's onset (the /t/ burst
    # of a following 'to' was lost this way in a run-3 salvage candidate).
    # The anchor words themselves are always fully cut: a neighbor clamp only
    # shrinks padding, never the anchor span (overlapping ASR word times).
    s0 = min(max(0.0, source_words[ss[0]]['start'] - pad_pre, s_prev_end), source_words[ss[0]]['start'])
    s1 = max(min(src_dur, source_words[ss[1] - 1]['end'] + pad_post, s_next_start), source_words[ss[1] - 1]['end'])
    source_samples = _read_mono(source)
    generation_samples = _read_mono(generation)
    cut0, cut1 = int(s0 * SAMPLE_RATE), int(s1 * SAMPLE_RATE)
    patch = generation_samples[int(g0 * SAMPLE_RATE):int(g1 * SAMPLE_RATE)].tolist()
    if not patch:
        raise EditorError('transplant_span_ambiguous', 'Aligned patch is empty.')
    _splice_replace(source_samples, cut0, cut1, patch, int(SAMPLE_RATE * crossfade_ms / 1000), output)
    signal = measure_signal(output, Limits())
    if signal['rms_dbfs'] <= -100:
        raise EditorError('silent_output', 'Transplant candidate is effectively silent.')
    if signal['peak'] > 1.001:
        raise EditorError('out_of_range_output', 'Transplant candidate exceeds full scale.')
    info = {'method': 'asr_guided_transplant', 'operation': 'insert',
            'generation_span_seconds': [round(g0, 3), round(g1, 3)],
            'source_span_seconds': [round(s0, 3), round(s1, 3)],
            'pad_pre_seconds': pad_pre, 'pad_post_seconds': pad_post,
            'crossfade_ms': crossfade_ms,
            'outside_pcm': 'byte-exact outside replaced span; tail time-shifted by patch delta',
            'candidate_sha256': sha256_file(output),
            'note': 'Word correctness gated by ASR exact match; naturalness and joins need human listening review.'}
    return info


def localized_transplant(source: Path, generation: Path, transcriber, start: float, end: float,
                         source_text: str, edited_text: str, output: Path, *,
                         pad_pre: float = DEFAULT_PAD_PRE_SECONDS,
                         pad_post: float = DEFAULT_PAD_POST_SECONDS,
                         crossfade_ms: int = DEFAULT_CROSSFADE_MS) -> dict:
    """Localized edit with a full-context donor.

    The generation is produced from the WHOLE clip (speaker context intact);
    only the changed phrase region - found by diffing the human-checked
    source and edited transcripts, then ASR-aligned on the source - is
    transplanted inside the caller's verified [start, end] interval.
    Unchanged words that share the interval keep their original PCM. The
    checked interval is fixed-duration: the donor patch must fit the source
    cut frame-exact (no time stretch, no padding of speech, no tail shift),
    and the cut itself - changed words plus join padding - is clamped
    strictly inside [start, end] so everything outside the interval remains
    the original PCM, byte-exact and unmoved. A patch that cannot fit fails
    closed ('transplant_duration_mismatch'): a longer localized edit needs a
    wider verified interval or whole_clip scope. Fails closed when the
    generation's ASR transcript is
    not already an exact match for the edited text (the unchanged QA gate
    requires that anyway) or the diff is degenerate."""
    source_tokens = normalized_tokens(source_text)
    edited_tokens = normalized_tokens(edited_text)
    if not source_tokens or source_tokens == edited_tokens:
        raise EditorError('transplant_span_ambiguous', 'Localized transplant needs a real text change.')
    prefix = 0
    while prefix < min(len(source_tokens), len(edited_tokens)) and source_tokens[prefix] == edited_tokens[prefix]:
        prefix += 1
    suffix = 0
    while (suffix < min(len(source_tokens), len(edited_tokens)) - prefix
           and source_tokens[len(source_tokens) - 1 - suffix] == edited_tokens[len(edited_tokens) - 1 - suffix]):
        suffix += 1
    if prefix == 0 and suffix == 0:
        raise EditorError('transplant_span_ambiguous', 'Changed span touches both edges; use whole_clip scope.')
    observed = transcriber(Path(generation))
    gen_words = _flat_word_tokens(observed)
    gen_tokens = [w['token'] for w in gen_words]
    if gen_tokens != edited_tokens:
        raise EditorError('transplant_generation_mismatch',
                          'Generation transcript does not exactly match the edited text; no safe transplant span.')
    m = len(edited_tokens)
    duration = len(_read_mono(generation)) / SAMPLE_RATE
    if m - suffix > prefix:
        g0 = max(0.0, gen_words[prefix]['start'] - pad_pre)
        g1 = min(duration, gen_words[m - suffix - 1]['end'] + pad_post)
    else:
        # Pure deletion: the patch is the generation's natural gap between the
        # kept words, so the join carries room tone instead of a hard cut.
        left = gen_words[prefix - 1]['end'] if prefix else 0.0
        right = gen_words[prefix]['start'] if prefix < m else duration
        g0 = max(0.0, left - pad_pre)
        g1 = min(duration, right + pad_post)
    source_samples = _read_mono(source)
    generation_samples = _read_mono(generation)
    total = len(source_samples)
    if not (0 <= start < end <= total / SAMPLE_RATE):
        raise EditorError('transplant_span_ambiguous', 'Verified interval is outside the recording.')
    changed_source = source_tokens[prefix:len(source_tokens) - suffix]
    crossfade = int(SAMPLE_RATE * crossfade_ms / 1000)
    if changed_source:
        # The verified interval authorizes the edit region; the cut is
        # narrowed to the ASR-aligned changed words inside it so unchanged
        # words that share the interval (e.g. 'team' next to 'better') keep
        # their original PCM. The cut - words plus join padding - is clamped
        # strictly inside the interval and never clips a neighboring word.
        # Any ambiguity fails closed.
        source_words = _flat_word_tokens(transcriber(Path(source)))
        stokens = [w['token'] for w in source_words]
        s0i, s1i = _find_unique_span(stokens, changed_source, 'The changed source words')
        w0, w1 = source_words[s0i], source_words[s1i - 1]
        if w0['start'] < start - 0.05 or w1['end'] > end + 0.05:
            raise EditorError('transplant_span_ambiguous',
                              'Changed words are not inside the verified interval.')
        prev_end = source_words[s0i - 1]['end'] if s0i else 0.0
        next_start = source_words[s1i]['start'] if s1i < len(source_words) else total / SAMPLE_RATE
        lo_f, hi_f = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        prev_f, next_f = int(prev_end * SAMPLE_RATE), int(next_start * SAMPLE_RATE)
        w0f, w1f = int(w0['start'] * SAMPLE_RATE), int(w1['end'] * SAMPLE_RATE)
        cut0 = max(w0f - int(pad_pre * SAMPLE_RATE), lo_f, prev_f)
        cut1 = min(w1f + int(pad_post * SAMPLE_RATE), hi_f, next_f)
        if cut0 > w0f or cut1 < w1f or cut1 <= cut0:
            raise EditorError('transplant_span_ambiguous',
                              'No room for the changed words inside the verified interval.')
        cut_frames = cut1 - cut0
        if m - suffix > prefix:
            # Replace: the donor patch must fit the cut frame-exact. Only the
            # amount of surrounding donor room tone flexes; the donor's spoken
            # words are never trimmed, stretched or padded. When the donor
            # words are longer than the default cut, the cut grows into the
            # room tone left inside the interval (never into neighbor words,
            # never past the interval) before failing closed.
            dw0, dw1 = gen_words[prefix], gen_words[m - suffix - 1]
            d0, d1 = int(dw0['start'] * SAMPLE_RATE), int(dw1['end'] * SAMPLE_RATE)
            word_frames = d1 - d0
            if word_frames > cut_frames:
                grow = word_frames - cut_frames
                add = min(grow, min(hi_f, next_f) - cut1)
                cut1 += add; grow -= add
                add = min(grow, cut0 - max(lo_f, prev_f))
                cut0 -= add; grow -= add
                cut_frames = cut1 - cut0
                if grow > 0:
                    raise EditorError('transplant_duration_mismatch',
                                      'Replacement words are longer than the source span inside the verified interval; widen the interval or use whole_clip scope.')
            slack = cut_frames - word_frames
            prev_g_end = int(gen_words[prefix - 1]['end'] * SAMPLE_RATE) if prefix else 0
            next_g_start = int(gen_words[m - suffix]['start'] * SAMPLE_RATE) if m - suffix < m else len(generation_samples)
            room_pre = d0 - prev_g_end
            room_post = next_g_start - d1
            if slack > room_pre + room_post:
                raise EditorError('transplant_duration_mismatch',
                                  'Not enough donor room tone around the replacement words for a frame-exact fit; widen the interval or use whole_clip scope.')
            pad_pre_f = min(int(pad_pre * SAMPLE_RATE), room_pre)
            if slack - pad_pre_f > room_post:
                pad_pre_f = slack - room_post
            pad_post_f = slack - pad_pre_f
            p0 = d0 - pad_pre_f
            patch = generation_samples[p0:p0 + cut_frames].tolist()
            g_span = [round(p0 / SAMPLE_RATE, 3), round((p0 + cut_frames) / SAMPLE_RATE, 3)]
        else:
            # Pure localized deletion: the removed words' span is replaced by
            # exactly the same number of frames of the generation's natural
            # gap (room tone, never digital silence).
            left = gen_words[prefix - 1]['end'] if prefix else 0.0
            right = gen_words[prefix]['start'] if prefix < m else len(generation_samples) / SAMPLE_RATE
            g0f, g1f = int(left * SAMPLE_RATE), int(right * SAMPLE_RATE)
            if g1f - g0f < cut_frames:
                raise EditorError('transplant_duration_mismatch',
                                  'The generation gap is shorter than the deleted span; cannot keep the verified interval at fixed duration.')
            off = (g1f - g0f - cut_frames) // 2
            patch = generation_samples[g0f + off:g0f + off + cut_frames].tolist()
            g_span = [round((g0f + off) / SAMPLE_RATE, 3), round((g0f + off + cut_frames) / SAMPLE_RATE, 3)]
    else:
        # Pure localized insertion at the natural gap between the kept words.
        # The inserted donor words plus join padding replace an equal number
        # of frames of source room tone around the insertion point, all inside
        # the verified interval. A longer localized insert needs a wider
        # interval; it never shifts the tail.
        source_words = _flat_word_tokens(transcriber(Path(source)))
        stokens = [w['token'] for w in source_words]
        kept = source_tokens[:prefix] + source_tokens[len(source_tokens) - suffix:]
        if stokens != kept:
            raise EditorError('transplant_span_ambiguous',
                              'Source ASR transcript does not match the source text; no safe insertion point.')
        left_end = source_words[prefix - 1]['end'] if prefix else 0.0
        right_start = source_words[prefix]['start'] if prefix < len(source_words) else total / SAMPLE_RATE
        dw0, dw1 = gen_words[prefix], gen_words[m - suffix - 1]
        prev_g_end = gen_words[prefix - 1]['end'] if prefix else 0.0
        next_g_start = gen_words[m - suffix]['start'] if m - suffix < m else len(generation_samples) / SAMPLE_RATE
        # Same room-tone-only rule as the replace path: join padding never
        # absorbs a neighboring generation word.
        g0 = min(max(0.0, dw0['start'] - pad_pre, prev_g_end), dw0['start'])
        g1 = max(min(len(generation_samples) / SAMPLE_RATE, dw1['end'] + pad_post, next_g_start), dw1['end'])
        patch_frames = int(g1 * SAMPLE_RATE) - int(g0 * SAMPLE_RATE)
        gap0, gap1 = int(left_end * SAMPLE_RATE), int(right_start * SAMPLE_RATE)
        if gap1 - gap0 < patch_frames:
            raise EditorError('transplant_duration_mismatch',
                              'Inserted words are longer than the room tone inside the verified interval; widen the interval or use whole_clip scope.')
        point = (gap0 + gap1) // 2
        cut0 = point - patch_frames // 2
        cut1 = cut0 + patch_frames
        lo, hi = int(start * SAMPLE_RATE), int(end * SAMPLE_RATE)
        if cut0 < lo:
            cut0, cut1 = lo, lo + patch_frames
        if cut1 > hi:
            cut1, cut0 = hi, hi - patch_frames
        if cut0 < gap0 or cut1 > gap1 or cut0 < lo or cut1 > hi or hi - lo < patch_frames:
            raise EditorError('transplant_duration_mismatch',
                              'Inserted words do not fit inside the verified interval at fixed duration; widen the interval or use whole_clip scope.')
        patch = generation_samples[int(g0 * SAMPLE_RATE):int(g0 * SAMPLE_RATE) + patch_frames].tolist()
        g_span = [round(g0, 3), round(g1, 3)]
    if not patch:
        raise EditorError('transplant_span_ambiguous', 'Aligned patch is empty.')
    if not (0 <= cut0 <= cut1 <= total):
        raise EditorError('transplant_span_ambiguous', 'Aligned source span is outside the recording.')
    if len(patch) != cut1 - cut0:
        raise EditorError('transplant_duration_mismatch', 'Donor patch is not frame-exact; refusing to shift the tail.')
    _splice_replace(source_samples, cut0, cut1, patch, crossfade, output)
    signal = measure_signal(output, Limits())
    if signal['rms_dbfs'] <= -100:
        raise EditorError('silent_output', 'Transplant candidate is effectively silent.')
    if signal['peak'] > 1.001:
        raise EditorError('out_of_range_output', 'Transplant candidate exceeds full scale.')
    return {'method': 'localized_context_transplant',
            'generation_span_seconds': g_span,
            'source_interval_seconds': [round(start, 3), round(end, 3)],
            'source_cut_seconds': [round(cut0 / SAMPLE_RATE, 3), round(cut1 / SAMPLE_RATE, 3)],
            'changed_source_words': ' '.join(source_tokens[prefix:len(source_tokens) - suffix]),
            'changed_edited_words': ' '.join(edited_tokens[prefix:m - suffix]),
            'pad_pre_seconds': pad_pre, 'pad_post_seconds': pad_post, 'crossfade_ms': crossfade_ms,
            'cut_clamped_to_interval': True,
            'duration_preserved': True,
            'outside_pcm': 'byte-exact and unmoved outside the verified interval; cut clamped inside the interval; output duration identical to source (frame-exact donor fit)',
            'candidate_sha256': sha256_file(output),
            'note': 'Word correctness gated by ASR exact match; naturalness, joins and phrase voice need human listening review.'}
