"""Correctable-transcript editing session: transcribe once, correct, align, review, preview, save.

Why this exists: a Descript-style transcript editor cannot treat ASR output as
ground truth - a repeatable transcription can be repeatably WRONG, and an edit
driven by a wrong word cuts the wrong audio. The older flow required the supplied
text and the ASR readout to agree exactly before editing; that blocks edits when
they disagree but cannot prove correctness (correlated errors: if the supplied
text came from the same ASR, the same wrong word passes on both sides).

This module flips the authority to the human, without pretending the machine can
locate corrected words it never recognized:

- The clip is transcribed ONCE with the pinned ASR (same model revision, pinned
  decode settings - repeatable, not guaranteed correct). Matched words keep the
  measured ASR word timings.
- The user corrects the text. Changed or inserted words get NO measured timing.
  The session proposes candidate span boundaries (from neighbouring measured
  anchors) and renders each candidate as an actual PCM slice of the source for
  the user to hear. Confirming a candidate issues a one-time token bound to the
  exact span text, transcript state, byte hash of the reviewed audio slice and
  the confirmed range. Every selected span requires a valid token, even when its timestamps
  are measured and its words have high fit scores; otherwise it fails closed. Interpolation proposes candidates -
  it is never treated as established timing.
- Low-confidence ASR words inside a span (probability below LOW_CONFIDENCE) also
  force review, because the words themselves may be wrong.
- The application segment duration floor (core.Limits.min_audio_seconds) is
  preserved: a shorter selection is refused with explicit wider context options
  to choose from. The session never widens a selection on its own.
- Preview and save are separate steps. Any correction invalidates every
  confirmation token and every preview. finalize() never overwrites the source.

Honesty contract:
- Repeatability is not correctness. The user's corrected text is the authority
  for WHAT the words are; measured ASR timings say WHERE recognized words are;
  anything else is reviewed by a human against real audio slices or refused.
- Acoustic forced alignment of the corrected text (wav2vec2 CTC, word timings
  from a KNOWN transcript) is implemented in forcedalign.py and used whenever an
  aligner is supplied: corrected words get timings measured against the audio
  itself. With no aligner, corrected words keep no measured timing and the
  manual audio-slice review above is the labeled fallback. Alignment scores are
  uncalibrated fit scores: they route words to human review and are never
  correctness probabilities. This module itself performs no model inference
  (PCM slicing only); the aligner model runs where the session is hosted.
- This module performs no audio generation. It derives verified parameters for
  the existing worker pipeline; all splice, duration, output and
  outside-interval PCM gates still run in the worker.
"""
from __future__ import annotations
import dataclasses, difflib, hashlib, json, math, shutil, uuid, wave
from pathlib import Path
from .core import EditorError, Limits, atomic_json, normalized_tokens, sha256_file, utc_now, flow_key_create, flow_mac

# Words below this ASR probability are flagged for review before their span can
# be edited. Documented heuristic, not a calibrated confidence measure.
LOW_CONFIDENCE = 0.5
# Edge offsets (seconds) for candidate span boundaries the user listens to.
EDGE_OFFSETS = (0.0, -0.1, 0.1, -0.2, 0.2)
SR = 24000
# Application segment duration floor, enforced authoritatively by the worker
# (core.Limits.min_audio_seconds). PRESERVED, not widened: a shorter selection is
# refused here with explicit wider context options - never silently extended.
_MIN_SEGMENT_SECONDS = Limits().min_audio_seconds


def _median(values: list[float]) -> float:
    if not values:
        return 0.25
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@dataclasses.dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float
    needs_review: bool = False
    timing_established: bool = True  # measured by ASR; False for corrected/inserted words


class TranscriptSession:
    """One source clip, one transcription, user corrections, reviewed span edits."""

    def __init__(self, source_audio, transcriber, workdir, *, aligner=None, flow_registry=None):
        self.source = Path(source_audio).resolve()
        if not self.source.is_file():
            raise EditorError('missing_source', 'Session source audio does not exist.')
        self._source_sha256 = sha256_file(self.source)
        self._issued_candidates: dict[str, dict] = {}
        self.transcriber = transcriber
        # aligner: forcedalign.setup_aligner callable (audio, text) -> measured word
        # timings for KNOWN text. None = acoustic alignment unavailable; corrected
        # words then require the manual audio-slice review (labeled fallback).
        self.aligner = aligner
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / 'candidates').mkdir(exist_ok=True)
        self.words: list[Word] = []
        self.corrected = False
        self._previews: dict[str, dict] = {}
        self._confirmations: dict[str, dict] = {}
        self._log: list[dict] = []
        # flow_registry: the WORKER-CONTROLLED directory where this session's HMAC key
        # is created (the verifying worker's runs root / '.flow-registry'). Required for
        # the corrected path; without it, corrected-span params cannot be issued at all.
        self.flow_registry = Path(flow_registry) if flow_registry else None
        self.session_id = uuid.uuid4().hex[:16]

    # -- step 1: transcribe once ----------------------------------------------------
    def transcribe(self) -> list[dict]:
        if self.words:
            raise EditorError('already_transcribed', 'This clip was already transcribed; start a new session to re-transcribe.')
        observed = self.transcriber(self.source)
        text = observed.get('text', '') if isinstance(observed, dict) else str(observed)
        raw = (observed.get('words') if isinstance(observed, dict) else None) or []
        if not raw:
            raise EditorError('asr_no_words', 'ASR returned no word timings; alignment needs word-level output.')
        for w in raw:
            prob = float(w.get('probability', 0.0))
            self.words.append(Word(word=str(w.get('word', '')).strip(), start=float(w.get('start', 0.0)),
                                   end=float(w.get('end', 0.0)), probability=prob,
                                   needs_review=prob < LOW_CONFIDENCE, timing_established=True))
        self.words = [w for w in self.words if w.word]
        if not self.words:
            raise EditorError('asr_no_words', 'ASR returned no usable words.')
        self._record('transcribe', {'text': text, 'word_count': len(self.words),
                                    'low_confidence': sum(1 for w in self.words if w.needs_review)})
        return self.transcript()

    def transcript(self) -> list[dict]:
        return [dataclasses.asdict(w) for w in self.words]

    @property
    def text(self) -> str:
        return ' '.join(w.word for w in self.words)

    def _transcript_digest(self) -> str:
        return hashlib.sha256(json.dumps(self.transcript(), sort_keys=True).encode()).hexdigest()

    # -- step 2: user corrections ----------------------------------------------------
    def correct(self, corrected_text: str) -> list[dict]:
        """Apply the user's corrected words. Corrected/inserted words lose measured
        timing (timing_established=False); matched words keep measured timings."""
        if not self.words:
            raise EditorError('not_transcribed', 'Transcribe before correcting.')
        old_tokens = normalized_tokens(self.text)
        new_words = corrected_text.split()
        new_tokens = normalized_tokens(corrected_text)
        if not new_tokens or len(new_tokens) != len(new_words):
            raise EditorError('correction_tokens', 'Corrected text must be plain words separated by spaces.')
        if new_tokens == old_tokens:
            self._record('correct', {'changed': 0})
            return self.transcript()
        matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)
        if not any(tag == 'equal' for tag, *_ in matcher.get_opcodes()):
            raise EditorError('correction_too_divergent',
                              'Corrected text shares no words with the transcription; there is nothing measured to align it against. Review the clip manually.')
        durations = [w.end - w.start for w in self.words if w.end > w.start]
        med = _median(durations)
        out: list[Word] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                out.extend(self.words[i1:i2])
                continue
            if tag == 'delete':
                continue  # user says these ASR words are not real speech; nothing to place
            prev_end = out[-1].end if out else None
            next_start = None
            for w2 in self.words[i2:]:
                next_start = w2.start
                break
            if prev_end is None and next_start is None:
                raise EditorError('correction_too_divergent', 'No anchor words to align the correction against.')
            # PROPOSED window only: candidate boundaries are rendered as audio slices
            # for human review; these values never become an edit's timing on their own.
            if prev_end is None:
                end = next_start
                start = max(0.0, end - med * (j2 - j1))
            elif next_start is None:
                start = prev_end
                end = start + med * (j2 - j1)
            else:
                start, end = prev_end, next_start
            step = (end - start) / (j2 - j1)
            for k, j in enumerate(range(j1, j2)):
                out.append(Word(word=new_words[j], start=start + step * k, end=start + step * (k + 1),
                                probability=0.0, needs_review=True, timing_established=False))
        self.words = out
        self.corrected = True
        self._previews.clear()
        self._confirmations.clear()  # stale confirmations must never survive a correction
        self._issued_candidates.clear()
        aligned = 0
        if self.aligner is not None and any(not w.timing_established for w in self.words):
            # Preferred path: measure the corrected words against the audio itself.
            try:
                # The aligner fails closed on punctuation (unsupported chars are
                # meaningful content it must not silently drop). The session feeds it
                # its normalized token stream - the exact words being placed - while
                # the displayed transcript keeps the ASR's original casing/punctuation.
                aligned_text = ' '.join(normalized_tokens(self.text))
                observed = self.aligner(self.source, aligned_text)
                measured = observed.get('words') or []
                if len(measured) != len(self.words):
                    raise EditorError('alignment_count_mismatch', 'Aligned word count differs from the corrected transcript.')
                merged = []
                for w, m in zip(self.words, measured):
                    if normalized_tokens(w.word) != normalized_tokens(m.get('word', '')):
                        raise EditorError('alignment_word_mismatch', 'Aligned words diverge from the corrected transcript.')
                    # alignment_score: uncalibrated CTC fit score from the aligner
                    # (exp of mean frame log-prob). It routes words to human review;
                    # it is NOT a correctness probability and proves nothing by itself.
                    prob = float(m.get('alignment_score', m.get('probability', 0.0)))
                    merged.append(Word(word=w.word, start=float(m['start']), end=float(m['end']),
                                       probability=prob, needs_review=prob < LOW_CONFIDENCE,
                                       timing_established=True))
                self.words = merged
                aligned = len(merged)
                self._record('acoustic_align', {'words': aligned,
                                                'mean_alignment_score': observed.get('mean_alignment_score'),
                                                'score_semantics': 'uncalibrated fit score; review decides'})
            except Exception as exc:
                self._record('acoustic_align_fallback',
                             {'reason': getattr(exc, 'code', type(exc).__name__),
                              'fallback': 'manual_audio_slice_review'})
        self._record('correct', {'unestablished': sum(1 for w in self.words if not w.timing_established),
                                 'acoustically_aligned': aligned, 'word_count': len(self.words)})
        return self.transcript()

    # -- step 3: span selection -------------------------------------------------------
    def _locate_span(self, span_text: str) -> list[Word]:
        if not self.words:
            raise EditorError('not_transcribed', 'Transcribe before editing.')
        full = self.text
        if not span_text.strip():
            raise EditorError('span_empty', 'Select a non-empty span.')
        if full.count(span_text) != 1:
            raise EditorError('span_not_unique', 'The selected span must occur exactly once in the current transcript.')
        before, _, _ = full.partition(span_text)
        first = len(before.split())
        count = len(span_text.split())
        span = self.words[first:first + count]
        if len(span) != count:
            raise EditorError('span_alignment', 'Span does not map cleanly onto aligned words.')
        return span

    def _context_options(self, span_text: str, limit: int = 3) -> list[str]:
        """Wider contiguous selections (the span plus neighbouring words) that meet
        the segment duration floor. Offered for the user to pick EXPLICITLY; the
        chosen wider span then goes through the same review gates as any other
        selection. The session never widens a selection on its own."""
        span = self._locate_span(span_text)
        first = next(i for i, w in enumerate(self.words) if w is span[0])
        last = first + len(span)  # exclusive
        reach = 6
        options = []
        for lo in range(max(0, first - reach), first + 1):
            for hi in range(last, min(len(self.words), last - 1 + reach) + 1):
                if lo == first and hi == last:
                    continue
                duration = self.words[hi - 1].end - self.words[lo].start
                if duration >= _MIN_SEGMENT_SECONDS:
                    options.append((duration, ' '.join(w.word for w in self.words[lo:hi])))
        options.sort()
        return [text for _, text in options[:limit]]

    def span_needs_review(self, span_text: str) -> list[str]:
        """Words forcing human review: unestablished (corrected) edge words that locate
        the span, plus any low-confidence ASR words inside it."""
        span = self._locate_span(span_text)
        flagged = {w.word for w in span if w.needs_review}
        if not span[0].timing_established:
            flagged.add(span[0].word)
        if not span[-1].timing_established:
            flagged.add(span[-1].word)
        return sorted(flagged)

    # -- step 4: review surface - real audio slices of candidate boundaries -----------
    def _duration(self) -> float:
        with wave.open(str(self.source), 'rb') as w:
            if w.getsampwidth() != 2 or w.getframerate() != SR:
                raise EditorError('unsupported_source_format', 'Session review needs PCM16 24kHz source audio.')
            return w.getnframes() / SR

    def _slice(self, start: float, end: float, path: Path) -> None:
        with wave.open(str(self.source), 'rb') as w:
            params = w.getparams()
            frames = w.readframes(w.getnframes())
        first, last = round(start * SR) * 2, round(end * SR) * 2
        if not (0 <= first < last <= len(frames)):
            raise EditorError('candidate_out_of_range', 'Candidate boundary lands outside the clip.')
        with wave.open(str(path), 'wb') as w:
            w.setparams(params)
            w.writeframes(frames[first:last])

    def review_candidates(self, span_text: str, *, start_adjust_seconds: float = 0.0,
                          end_adjust_seconds: float = 0.0) -> list[dict]:
        """Render candidate span boundaries as real audio slices for human listening.
        Spans with fully measured, confident edges return a single measured candidate."""
        span = self._locate_span(span_text)
        duration = self._duration()
        if sha256_file(self.source) != self._source_sha256:
            raise EditorError('source_changed', 'Source changed since transcription; start a new session.')
        if not all(isinstance(v, (float, int)) and math.isfinite(v)
                   for v in (start_adjust_seconds, end_adjust_seconds)):
            raise EditorError('invalid_boundary_adjustment', 'Boundary adjustments must be finite seconds.')
        base_start = span[0].start + start_adjust_seconds
        base_end = span[-1].end + end_adjust_seconds
        if not 0 <= base_start < base_end <= duration:
            raise EditorError('candidate_out_of_range', 'Adjusted boundaries must stay inside the recording.')
        starts = {round(min(max(base_start + off, 0.0), duration), 6) for off in
                  (EDGE_OFFSETS if not span[0].timing_established else (0.0,))}
        ends = {round(min(max(base_end + off, 0.0), duration), 6) for off in
                (EDGE_OFFSETS if not span[-1].timing_established else (0.0,))}
        combos = sorted((s, e) for s in starts for e in ends if e - s >= 0.05)
        if not combos:
            raise EditorError('candidate_out_of_range', 'No usable candidate boundary inside the clip.')
        manifest = []
        for n, (s, e) in enumerate(combos):
            path = self.dir / 'candidates' / f'span-{uuid.uuid4().hex[:8]}-{n}.wav'
            self._slice(s, e, path)
            manifest.append({'id': path.stem, 'start': s, 'end': e, 'path': str(path),
                             'slice_sha256': sha256_file(path),
                             'span_text': span_text, 'transcript_sha256': self._transcript_digest()})
        for entry in manifest:
            self._issued_candidates[entry['id']] = dict(entry)
        self._record('review_candidates', {'span': span_text, 'candidates': len(manifest)})
        return manifest

    def confirm_span(self, manifest_entry: dict) -> str:
        """Bind the human's choice to the exact audio slice, text and range reviewed."""
        if sha256_file(self.source) != self._source_sha256:
            raise EditorError('source_changed', 'Source changed since transcription; start a new session.')
        if manifest_entry.get('transcript_sha256') != self._transcript_digest():
            raise EditorError('confirmation_stale', 'The transcript changed after these candidates were rendered; re-review.')
        issued = self._issued_candidates.get(manifest_entry.get('id', ''))
        if issued is None or issued != manifest_entry:
            raise EditorError('confirmation_unbound', 'Candidate was not issued by this session or was changed; render it again.')
        if not Path(manifest_entry.get('path', '')).is_file() or \
           sha256_file(manifest_entry['path']) != manifest_entry.get('slice_sha256'):
            raise EditorError('confirmation_unbound', 'Reviewed audio slice is missing or changed; re-review.')
        token = uuid.uuid4().hex
        self._confirmations[token] = {'span_text': manifest_entry['span_text'],
                                      'start': manifest_entry['start'], 'end': manifest_entry['end'],
                                      'slice_sha256': manifest_entry['slice_sha256'],
                                      'transcript_sha256': manifest_entry['transcript_sha256'],
                                      'confirmed_at': utc_now()}
        self._record('confirm_span', {'span': manifest_entry['span_text'],
                                      'range': [manifest_entry['start'], manifest_entry['end']],
                                      'slice_sha256': manifest_entry['slice_sha256']})
        return token

    # -- step 5: verified edit parameters ----------------------------------------------
    def span_params(self, span_text: str, edited_span_text: str, *, operation: str = 'replace',
                    confirmation_token: str | None = None) -> dict:
        # Both session paths (user_corrected and asr_accepted) issue worker-registry-
        # bound evidence; without the worker's registry a session cannot issue span
        # edits at all. Checked first so no confirmation token is consumed on failure.
        if self.flow_registry is None:
            raise EditorError('flow_registry_unavailable',
                              'This session has no worker flow registry; session span edits cannot be issued.')
        span = self._locate_span(span_text)
        flagged = self.span_needs_review(span_text)
        conf = self._confirmations.get(confirmation_token or '')
        if conf is None or conf['span_text'] != span_text or \
           conf['transcript_sha256'] != self._transcript_digest():
            raise EditorError('span_review_required',
                              'Every selected span needs a listening confirmation, including confident timings. '
                              'Listen to the rendered cut, adjust boundaries if needed, then confirm.')
        if sha256_file(self.source) != self._source_sha256:
            raise EditorError('source_changed', 'Source changed since transcription; start a new session.')
        start, end = conf['start'], conf['end']
        if end - start < _MIN_SEGMENT_SECONDS:
            options = self._context_options(span_text)
            hint = (' Wider selections that meet the floor and contain this span: '
                    + '; '.join(f'"{o}"' for o in options)) if options else \
                   ' No neighbouring-word window containing this span reaches the floor, so this edit is not supported as a local segment.'
            raise EditorError('span_below_duration_floor',
                              f'The selected span is {end - start:.2f}s; the application segment floor is '
                              f'{_MIN_SEGMENT_SECONDS:g}s (preserved, never silently widened). Select a wider '
                              'span explicitly - it goes through the same review gates as any selection.' + hint)
        del self._confirmations[confirmation_token or '']
        params = {'segment_start_seconds': repr(round(start, 6)),
                  'segment_end_seconds': repr(round(end, 6)),
                  'segment_text': span_text, 'source_text': self.text,
                  'edited_segment_text': edited_span_text,
                  'original_text': span_text, 'replacement_text': edited_span_text,
                  'alignment_source': 'user_corrected' if self.corrected else 'asr_accepted',
                  'span_confirmed': True}
        # Measured changed-word timings, both paths: for user_corrected these are the
        # session's aligner-measured timings for the tokens that actually CHANGE inside
        # the span (an ASR misrecognition is often the very reason for the correction);
        # for asr_accepted they are the measured ASR timings themselves. The worker
        # uses them instead of re-running ASR on the source. Absent established
        # timings (manual-review fallback path), this stays None and the transplant
        # narrows the cut with its legacy source-ASR search.
        span_tokens = normalized_tokens(span_text)
        edited_tokens = normalized_tokens(edited_span_text)
        pre = 0
        while pre < min(len(span_tokens), len(edited_tokens)) and span_tokens[pre] == edited_tokens[pre]:
            pre += 1
        suf = 0
        while (suf < min(len(span_tokens), len(edited_tokens)) - pre
               and span_tokens[len(span_tokens) - 1 - suf] == edited_tokens[len(edited_tokens) - 1 - suf]):
            suf += 1
        changed_words = span[pre:len(span) - suf] if suf else span[pre:]
        measured = None
        if changed_words and all(w.timing_established for w in changed_words):
            measured = [{'word': w.word, 'start': repr(round(w.start, 6)), 'end': repr(round(w.end, 6))}
                        for w in changed_words]
            # A listener-adjusted selected edge overrides the stale acoustic edge
            # only when the changed words touch that edge. Internal unchanged
            # words never become part of the changed span merely by reviewing a
            # wider phrase. These reviewed values remain MAC-bound below.
            if pre == 0 and abs(start - span[0].start) > 0.000001:
                measured[0]['start'] = repr(round(start, 6))
            if suf == 0 and abs(end - span[-1].end) > 0.000001:
                measured[-1]['end'] = repr(round(end, 6))
            if not all(start <= float(w['start']) < float(w['end']) <= end for w in measured):
                raise EditorError('reviewed_word_range_invalid',
                                  'Reviewed edges do not contain the changed words in order. '
                                  'Select the changed phrase and review its boundaries again.')
        params['changed_span_words'] = measured
        # Bound session evidence: HMAC over the exact parameters the worker will see.
        # The key lives in the worker's own flow registry (never in this session's
        # caller-visible directory), so a caller cannot self-issue evidence from an
        # arbitrary path; the worker looks the session id up in its registry only.
        # Accept-as-is edits are session work too - the human read the transcript and
        # selected the span - so they carry the same evidence, and the worker still
        # re-verifies their segment ASR on top (see segment.verify_alignment).
        key = flow_key_create(self.flow_registry, self.session_id)
        payload = {'span_text': params['segment_text'], 'source_text': params['source_text'],
                   'start': params['segment_start_seconds'], 'end': params['segment_end_seconds'],
                   'alignment_source': params['alignment_source'],
                   'changed_span_words': measured}
        params['flow_evidence'] = {'session_id': self.session_id}
        params['flow_mac'] = flow_mac(key, payload)
        self._record('span', {'span': span_text, 'flagged_words': flagged,
                              'range': [start, end], 'alignment_source': params['alignment_source'],
                              'confirmed': True})
        return params

    # -- step 6: preview, then save ------------------------------------------------------
    def preview(self, run_edit, operation: str, params: dict) -> dict:
        """Run the existing worker pipeline into the session preview area.

        run_edit is ReliabilityWorker.edit_audio (or a test double). The result is
        stored as a named preview; finalize() is the only way to turn it into a
        saved output, and any later correction invalidates it.
        """
        if params.get('span_confirmed') is not True:
            raise EditorError('span_review_required', 'Every selected span must be confirmed before preview.')
        result = run_edit(str(self.source), 'transcript_editor', operation, dict(params))
        pid = uuid.uuid4().hex[:12]
        out = getattr(result, 'output_path', None) or (result.get('output_path') if isinstance(result, dict) else None)
        technical = bool(getattr(result, 'technical_success', None) if not isinstance(result, dict)
                         else result.get('technical_success'))
        qa = bool(getattr(result, 'automatic_qa_pass', None) if not isinstance(result, dict)
                  else result.get('automatic_qa_pass'))
        if technical and not out:
            raise EditorError('preview_missing_artifact', 'Preview succeeded but produced no output path.')
        self._previews[pid] = {'transcript_sha256': self._transcript_digest(), 'output_path': out,
                               'technical_success': technical, 'automatic_qa_pass': qa,
                               'created_at': utc_now()}
        self._record('preview', {'id': pid, 'technical_success': technical, 'automatic_qa_pass': qa})
        return {'preview_id': pid, 'output_path': out, 'technical_success': technical,
                'automatic_qa_pass': qa}

    def finalize(self, preview_id: str, destination) -> dict:
        entry = self._previews.get(preview_id)
        if entry is None or entry['transcript_sha256'] != self._transcript_digest():
            raise EditorError('preview_unknown_or_stale',
                              'Unknown or invalidated preview. Re-run preview after the latest transcript state.')
        if not entry['technical_success']:
            raise EditorError('preview_not_usable', 'Preview did not complete technically; it cannot be saved.')
        dest = Path(destination).resolve()
        if dest == self.source:
            raise EditorError('finalize_over_source', 'Refusing to overwrite the session source audio.')
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry['output_path'], dest)
        record = {'saved_to': str(dest), 'preview_id': preview_id,
                  'automatic_qa_pass': entry['automatic_qa_pass'],
                  'listening_review': 'unscored'}
        self._record('finalize', record)
        return record

    # -- audit log ------------------------------------------------------------------------
    def _record(self, action: str, detail: dict) -> None:
        self._log.append({'action': action, 'at': utc_now(), **detail})
        atomic_json(self.dir / 'session-log.json', self._log)
