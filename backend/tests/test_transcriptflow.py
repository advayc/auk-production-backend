import dataclasses, tempfile, unittest, wave
from pathlib import Path
from auk_reliability.core import EditorError
from auk_reliability.transcriptflow import TranscriptSession
from auk_reliability.segment import verify_alignment

WORDS = [
    {'word': 'The', 'start': 0.0, 'end': 0.2, 'probability': 0.99},
    {'word': 'visitors', 'start': 0.2, 'end': 0.8, 'probability': 0.98},
    {'word': 'are', 'start': 0.8, 'end': 1.0, 'probability': 0.97},
    {'word': 'however', 'start': 1.0, 'end': 1.5, 'probability': 0.96},
    {'word': 'in', 'start': 1.5, 'end': 1.7, 'probability': 0.97},
    {'word': 'strong', 'start': 1.7, 'end': 2.2, 'probability': 0.30},
    {'word': 'form', 'start': 2.2, 'end': 2.6, 'probability': 0.98},
]
TEXT = ' '.join(w['word'] for w in WORDS)


def fake_transcriber(path):
    return {'text': TEXT, 'words': [dict(w) for w in WORDS]}


def write_wav(path, seconds=4):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b'\x01\x00' * int(seconds * 24000))


@dataclasses.dataclass
class FakeResult:
    technical_success: bool
    automatic_qa_pass: bool
    output_path: str | None


def reviewed_params(session, span, edited):
    # Test-only simulated listening acknowledgement, never a human-review claim.
    token = session.confirm_span(session.review_candidates(span)[0])
    return session.span_params(span, edited, confirmation_token=token)


class TranscriptFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        write_wav(self.src)
        self.registry = root / '.flow-registry'
        self.session = TranscriptSession(self.src, fake_transcriber, root / 'session',
                                         flow_registry=self.registry)
        self.session.transcribe()

    def tearDown(self):
        self.tmp.cleanup()

    def test_transcribe_flags_low_confidence(self):
        out = self.session.transcript()
        self.assertEqual([w['word'] for w in out if w['needs_review']], ['strong'])
        self.assertTrue(all(w['timing_established'] for w in out))

    def test_transcribe_twice_refused(self):
        with self.assertRaises(EditorError) as ctx:
            self.session.transcribe()
        self.assertEqual(ctx.exception.code, 'already_transcribed')

    def test_correct_replace_keeps_anchor_timings(self):
        out = self.session.correct(TEXT.replace('strong', 'excellent'))
        by_word = {w['word']: w for w in out}
        self.assertFalse(by_word['excellent']['timing_established'])
        self.assertTrue(by_word['excellent']['needs_review'])
        self.assertEqual(by_word['visitors']['start'], 0.2)
        self.assertTrue(by_word['visitors']['timing_established'])

    def test_correct_identical_is_noop(self):
        out = self.session.correct(TEXT)
        self.assertTrue(all(w['timing_established'] for w in out))

    def test_correct_divergent_refused(self):
        with self.assertRaises(EditorError) as ctx:
            self.session.correct('completely unrelated other words here')
        self.assertEqual(ctx.exception.code, 'correction_too_divergent')

    def test_punctuation_only_change_is_noop(self):
        # Normalized tokens are unchanged, so measured timings stand and no review is forced.
        out = self.session.correct(TEXT + '.')
        self.assertTrue(all(w['timing_established'] for w in out))
        self.assertEqual(self.session.span_needs_review('form'), [])

    def test_number_word_change_flags_unestablished(self):
        self.session.correct(TEXT.replace('strong', '5'))
        self.assertIn('5', self.session.span_needs_review('5'))

    def test_span_must_be_unique(self):
        def repeated(path):
            return {'text': 'hello hello world', 'words': [
                {'word': 'hello', 'start': 0.0, 'end': 0.5, 'probability': 0.99},
                {'word': 'hello', 'start': 0.5, 'end': 1.0, 'probability': 0.99},
                {'word': 'world', 'start': 1.0, 'end': 1.6, 'probability': 0.99}]}
        s = TranscriptSession(self.src, repeated, Path(self.tmp.name) / 'session2',
                          flow_registry=Path(self.tmp.name) / '.flow-registry')
        s.transcribe()
        with self.assertRaises(EditorError) as ctx:
            s.span_params('hello', 'goodbye')
        self.assertEqual(ctx.exception.code, 'span_not_unique')

    def test_measured_confident_span_still_requires_listening(self):
        self.assertEqual(self.session.span_needs_review('visitors'), [])
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('visitors', 'guests')
        self.assertEqual(ctx.exception.code, 'span_review_required')
        params = reviewed_params(self.session, 'visitors', 'guests')
        self.assertEqual(params['alignment_source'], 'asr_accepted')
        self.assertEqual(params['segment_start_seconds'], '0.2')
        self.assertEqual(params['segment_end_seconds'], '0.8')

    def test_unestablished_span_fails_closed_without_review(self):
        self.session.correct(TEXT.replace('strong', 'excellent'))
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('excellent', 'superb')
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_review_candidates_are_real_audio_and_confirm_binds(self):
        self.session.correct(TEXT.replace('strong', 'excellent'))
        candidates = self.session.review_candidates('excellent')
        self.assertGreaterEqual(len(candidates), 5)  # both edges unestablished
        for c in candidates:
            self.assertTrue(Path(c['path']).is_file())
            self.assertEqual(c['slice_sha256'], __import__('auk_reliability.core', fromlist=['sha256_file']).sha256_file(c['path']))
        token = self.session.confirm_span(candidates[0])
        params = self.session.span_params('excellent', 'superb', confirmation_token=token)
        self.assertEqual(params['alignment_source'], 'user_corrected')
        self.assertTrue(params['span_confirmed'])
        self.assertEqual(params['segment_start_seconds'], repr(candidates[0]['start']))
        self.assertEqual(params['segment_end_seconds'], repr(candidates[0]['end']))

    def test_wrong_or_stale_token_refused(self):
        corrected = TEXT.replace('strong', 'excellent').replace('form', 'shape')
        self.session.correct(corrected)
        token = self.session.confirm_span(self.session.review_candidates('excellent')[0])
        with self.assertRaises(EditorError) as ctx:  # token bound to a different span
            self.session.span_params('shape', 'form', confirmation_token=token)
        self.assertEqual(ctx.exception.code, 'span_review_required')
        self.session.correct(TEXT.replace('strong', 'superb'))  # invalidates
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('superb', 'great', confirmation_token=token)
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_low_confidence_span_needs_confirmation(self):
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('strong', 'excellent')
        self.assertEqual(ctx.exception.code, 'span_review_required')
        candidates = self.session.review_candidates('strong')
        self.assertEqual(len(candidates), 1)  # measured edges: single measured candidate
        token = self.session.confirm_span(candidates[0])
        params = self.session.span_params('strong', 'excellent', confirmation_token=token)
        self.assertEqual(params['segment_start_seconds'], '1.7')

    def test_preview_then_finalize(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        artifact = Path(self.tmp.name) / 'preview.wav'
        artifact.write_bytes(b'RIFF-preview')

        def run_edit(src, mode, op, p):
            self.assertEqual(mode, 'transcript_editor')
            return FakeResult(True, True, str(artifact))

        pv = self.session.preview(run_edit, 'replace', params)
        dest = Path(self.tmp.name) / 'final.wav'
        record = self.session.finalize(pv['preview_id'], dest)
        self.assertEqual(dest.read_bytes(), b'RIFF-preview')
        self.assertEqual(record['listening_review'], 'unscored')

    def test_correction_invalidates_preview(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        artifact = Path(self.tmp.name) / 'preview.wav'
        artifact.write_bytes(b'x')
        pv = self.session.preview(lambda *a: FakeResult(True, True, str(artifact)), 'replace', params)
        self.session.correct(TEXT.replace('strong', 'excellent'))
        with self.assertRaises(EditorError) as ctx:
            self.session.finalize(pv['preview_id'], Path(self.tmp.name) / 'final.wav')
        self.assertEqual(ctx.exception.code, 'preview_unknown_or_stale')

    def test_finalize_failed_preview_refused(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        pv = self.session.preview(lambda *a: FakeResult(False, False, None), 'replace', params)
        with self.assertRaises(EditorError) as ctx:
            self.session.finalize(pv['preview_id'], Path(self.tmp.name) / 'final.wav')
        self.assertEqual(ctx.exception.code, 'preview_not_usable')

    def test_finalize_never_overwrites_source(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        artifact = Path(self.tmp.name) / 'preview.wav'
        artifact.write_bytes(b'x')
        pv = self.session.preview(lambda *a: FakeResult(True, True, str(artifact)), 'replace', params)
        with self.assertRaises(EditorError) as ctx:
            self.session.finalize(pv['preview_id'], self.src)
        self.assertEqual(ctx.exception.code, 'finalize_over_source')

    def test_session_log_written(self):
        self.assertTrue((Path(self.tmp.name) / 'session' / 'session-log.json').is_file())


class AcousticAlignment(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        write_wav(self.src)

    def tearDown(self):
        self.tmp.cleanup()

    def test_aligner_establishes_corrected_word_timings(self):
        def aligner(audio, text):
            return {'text': text, 'mean_alignment_score': 0.91, 'words': [
                {'word': w['word'] if w['word'] != 'strong' else 'excellent',
                 'start': w['start'], 'end': w['end'], 'alignment_score': 0.9} for w in WORDS]}
        s = TranscriptSession(self.src, fake_transcriber, Path(self.tmp.name) / 's', aligner=aligner,
                          flow_registry=Path(self.tmp.name) / '.flow-registry')
        s.transcribe()
        out = s.correct(TEXT.replace('strong', 'excellent'))
        by_word = {w['word']: w for w in out}
        self.assertTrue(by_word['excellent']['timing_established'])
        self.assertEqual(s.span_needs_review('excellent'), [])

    def test_aligner_mismatch_falls_back_to_manual_review(self):
        def bad_aligner(audio, text):
            return {'text': text, 'mean_alignment_score': 0.5, 'words': [
                {'word': 'zzz', 'start': 0.0, 'end': 0.1, 'alignment_score': 0.5} for _ in WORDS]}
        s = TranscriptSession(self.src, fake_transcriber, Path(self.tmp.name) / 's', aligner=bad_aligner,
                          flow_registry=Path(self.tmp.name) / '.flow-registry')
        s.transcribe()
        out = s.correct(TEXT.replace('strong', 'excellent'))
        by_word = {w['word']: w for w in out}
        self.assertFalse(by_word['excellent']['timing_established'])
        with self.assertRaises(EditorError) as ctx:
            s.span_params('excellent', 'superb')
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_poor_fit_alignment_cannot_auto_accept(self):
        # Silence, non-English audio, or any poor fit yields uniformly low alignment
        # scores; every word then requires human review and no span can be issued
        # without review-and-confirm. There is no automatic acceptance path.
        def aligner(audio, text):
            return {'text': text, 'mean_alignment_score': 0.02, 'words': [
                {'word': w['word'] if w['word'] != 'strong' else 'excellent',
                 'start': w['start'], 'end': w['end'], 'alignment_score': 0.02} for w in WORDS]}
        s = TranscriptSession(self.src, fake_transcriber, Path(self.tmp.name) / 's', aligner=aligner,
                          flow_registry=Path(self.tmp.name) / '.flow-registry')
        s.transcribe()
        out = s.correct(TEXT.replace('strong', 'excellent'))
        self.assertTrue(all(w['needs_review'] for w in out))
        with self.assertRaises(EditorError) as ctx:
            s.span_params('excellent', 'superb')
        self.assertEqual(ctx.exception.code, 'span_review_required')
        with self.assertRaises(EditorError) as ctx:
            s.span_params('visitors', 'guests')
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_aligner_low_score_words_flagged(self):
        def aligner(audio, text):
            return {'text': text, 'mean_alignment_score': 0.6, 'words': [
                {'word': w['word'] if w['word'] != 'strong' else 'excellent',
                 'start': w['start'], 'end': w['end'],
                 'alignment_score': 0.3 if w['word'] == 'strong' else 0.95} for w in WORDS]}
        s = TranscriptSession(self.src, fake_transcriber, Path(self.tmp.name) / 's', aligner=aligner,
                          flow_registry=Path(self.tmp.name) / '.flow-registry')
        s.transcribe()
        s.correct(TEXT.replace('strong', 'excellent'))
        self.assertIn('excellent', s.span_needs_review('excellent'))


class UserCorrectedAlignmentGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        write_wav(self.src)
        self.registry = root / '.flow-registry'
        self.session = TranscriptSession(self.src, fake_transcriber, root / 'session',
                                         flow_registry=self.registry)
        self.session.transcribe()

    def tearDown(self):
        self.tmp.cleanup()

    def _params(self):
        self.session.correct(TEXT.replace('strong', 'excellent'))
        candidates = self.session.review_candidates('excellent')
        containing = [c for c in candidates
                      if c['start'] <= WORDS[5]['start'] and c['end'] >= WORDS[5]['end']]
        self.assertTrue(containing)
        token = self.session.confirm_span(containing[0])
        return self.session.span_params('excellent', 'superb', confirmation_token=token)

    def test_confirmation_token_consumed_on_issue(self):
        self.session.correct(TEXT.replace('strong', 'excellent'))
        candidates = self.session.review_candidates('excellent')
        containing = [c for c in candidates
                      if c['start'] <= WORDS[5]['start'] and c['end'] >= WORDS[5]['end']]
        token = self.session.confirm_span(containing[0])
        self.session.span_params('excellent', 'superb', confirmation_token=token)
        # Replay of the same token is refused: a second param set needs a fresh review.
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('excellent', 'great', confirmation_token=token)
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_session_evidence_passes_gate_without_transcriber(self):
        verify_alignment(Path('/nonexistent.wav'), self._params(), None, flow_registry=self.registry)  # no raise

    def test_forged_flags_without_evidence_rejected(self):
        params = {'segment_text': 'corrected words', 'source_text': 'some corrected words here',
                  'alignment_source': 'user_corrected', 'span_confirmed': True}
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params, None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_tampered_range_rejected(self):
        params = self._params()
        params['segment_start_seconds'] = repr(float(params['segment_start_seconds']) + 0.5)
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params, None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_tampered_text_rejected(self):
        params = self._params()
        params['segment_text'] = 'visitors'
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params, None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_self_issued_key_from_caller_directory_rejected(self):
        # The attack the registry design closes: a caller mints its own key for a
        # session id in storage IT controls and MACs forged params. Verification only
        # ever looks inside the worker's registry, so this must fail closed.
        from auk_reliability.core import flow_key_create, flow_mac
        params = self._params()
        attacker_root = Path(self.tmp.name) / 'attacker-controlled'
        session_id = params['flow_evidence']['session_id']
        evil_key = flow_key_create(attacker_root, session_id)
        payload = {'span_text': 'attacker', 'source_text': params['source_text'],
                   'start': params['segment_start_seconds'], 'end': params['segment_end_seconds'],
                   'alignment_source': 'user_corrected'}
        forged = dict(params)
        forged['segment_text'] = 'attacker'
        forged['flow_mac'] = flow_mac(evil_key, payload)
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), forged, None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')
        # Unknown session id (no key in the worker registry at all) also fails.
        forged2 = dict(params)
        forged2['flow_evidence'] = {'session_id': 'beefbeefbeefbeef'}
        forged2['flow_mac'] = flow_mac(flow_key_create(attacker_root, 'beefbeefbeefbeef'),
                                       {'span_text': params['segment_text'], 'source_text': params['source_text'],
                                        'start': params['segment_start_seconds'], 'end': params['segment_end_seconds'],
                                        'alignment_source': 'user_corrected'})
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), forged2, None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_corrected_span_without_confirmation_refused(self):
        params = {'segment_text': 'corrected words', 'source_text': 'some corrected words here',
                  'alignment_source': 'user_corrected'}
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params, None)
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_legacy_path_unchanged(self):
        params = {'segment_text': 'alpha beta', 'source_text': 'alpha beta',
                  'segment_scope': 'whole_clip', 'segment_start_seconds': 0, 'segment_end_seconds': 1}
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params, None)
        self.assertEqual(ctx.exception.code, 'alignment_qa_unavailable')


class AcceptAsIsAlignmentGate(unittest.TestCase):
    """Unchanged-transcript lifecycle (the accept-ASR-as-is path). Session evidence
    is required exactly like the corrected path, AND the worker still re-verifies the
    segment ASR: a mismatch fails closed (the route is to correct the transcript)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        write_wav(self.src)
        self.registry = root / '.flow-registry'
        self.session = TranscriptSession(self.src, fake_transcriber, root / 'session',
                                         flow_registry=self.registry)
        self.session.transcribe()

    def tearDown(self):
        self.tmp.cleanup()

    def test_accept_as_is_carries_worker_registry_evidence(self):
        # The regression this covers: a normalized no-op correct() left corrected=False,
        # no evidence was issued, and nothing could set alignment_verified - the
        # accept-as-is path could never reach generation.
        params = reviewed_params(self.session, 'visitors', 'guests')
        self.assertEqual(params['alignment_source'], 'asr_accepted')
        self.assertIn('flow_evidence', params)
        self.assertTrue(params['flow_mac'])
        self.assertEqual(params['changed_span_words'],
                         [{'word': 'visitors', 'start': '0.2', 'end': '0.8', 'previous_word_end': '0.2', 'next_word_start': '0.8'}])
        # Segment ASR agrees with the selected words: the gate passes.
        verify_alignment(Path('/nonexistent.wav'), params,
                         lambda p: {'text': 'visitors'}, flow_registry=self.registry)

    def test_accept_as_is_segment_mismatch_fails_closed(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params,
                             lambda p: {'text': 'tourists'}, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'segment_transcript_mismatch')

    def test_accept_as_is_requires_transcriber(self):
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), reviewed_params(self.session, 'visitors', 'guests'),
                             None, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'alignment_qa_unavailable')

    def test_accept_as_is_tampered_range_rejected(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        params['segment_start_seconds'] = repr(float(params['segment_start_seconds']) + 0.25)
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params,
                             lambda p: {'text': 'visitors'}, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_accept_as_is_tampered_text_rejected(self):
        params = reviewed_params(self.session, 'visitors', 'guests')
        params['segment_text'] = 'however'
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), params,
                             lambda p: {'text': 'however'}, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_accept_as_is_flags_without_evidence_rejected(self):
        forged = {'segment_text': 'visitors', 'source_text': TEXT,
                  'alignment_source': 'asr_accepted', 'span_confirmed': True}
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(Path('/nonexistent.wav'), forged,
                             lambda p: {'text': 'visitors'}, flow_registry=self.registry)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_session_without_registry_issues_nothing(self):
        s = TranscriptSession(self.src, fake_transcriber, Path(self.tmp.name) / 'noreg')
        s.transcribe()
        with self.assertRaises(EditorError) as ctx:
            s.span_params('visitors', 'guests')
        self.assertEqual(ctx.exception.code, 'flow_registry_unavailable')


class SpanDurationFloor(unittest.TestCase):
    """The application segment floor (0.5s) is preserved. A shorter selection is
    refused with explicit wider context options; the session never widens silently."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        write_wav(self.src)
        self.registry = root / '.flow-registry'
        self.session = TranscriptSession(self.src, fake_transcriber, root / 'session',
                                         flow_registry=self.registry)
        self.session.transcribe()

    def tearDown(self):
        self.tmp.cleanup()

    def test_short_span_fails_with_explicit_context_options(self):
        with self.assertRaises(EditorError) as ctx:  # 'are' is 0.2s
            reviewed_params(self.session, 'are', 'were')
        self.assertEqual(ctx.exception.code, 'span_below_duration_floor')
        self.assertIn('"are however"', str(ctx.exception))

    def test_explicit_wider_selection_meets_floor(self):
        params = reviewed_params(self.session, 'are however', 'were however')
        self.assertEqual(params['segment_start_seconds'], '0.8')
        self.assertEqual(params['segment_end_seconds'], '1.5')
        self.assertEqual(params['alignment_source'], 'asr_accepted')
        self.assertEqual(params['changed_span_words'],
                         [{'word': 'are', 'start': '0.8', 'end': '1.0', 'previous_word_end': '0.8', 'next_word_start': '1.0'}])


class WorkerIntegration(unittest.TestCase):
    """Real ReliabilityWorker + fixture adapter: session-issued corrected params drive
    the actual pipeline (planning, gates, splice, preview artifact), and forged
    corrected params are rejected by the worker itself."""
    def setUp(self):
        import numpy as np
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / 'source.wav'
        sr = 24000
        t = np.arange(int(3 * sr)) / sr
        y = 0.3 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 440 * t)
        pcm = (y * 32767).astype(np.int16)
        with wave.open(str(self.src), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
        from auk_reliability.worker import ReliabilityWorker
        from auk_reliability.qa import SemanticQAGate
        from tests.test_backend import Adapter
        self.adapter = Adapter()
        corrected = TEXT.replace('strong', 'excellent')
        edited = TEXT.replace('strong', 'superb')
        # Path-aware fixture: the QA transcriber transcribes whatever audio it is
        # given, so the (normalized) source reads back the corrected transcript
        # and the generation reads back the edited transcript.
        def qa_transcriber(path):
            base = corrected if 'normalized-source' in str(path) else edited
            words = [{'word': w, 'start': WORDS[i]['start'], 'end': WORDS[i]['end'],
                      'probability': 0.95} for i, w in enumerate(base.split())]
            return {'text': base, 'words': words}
        self.gate = SemanticQAGate(qa_transcriber, lambda a, b: .9)
        self.worker = ReliabilityWorker(self.adapter, root / 'runs', semantic_gate=self.gate,
                                        runtime_profile={'simulation': True})
        self.registry = self.worker.flow_registry
        self.session = TranscriptSession(self.src, fake_transcriber, root / 'session',
                                         flow_registry=self.registry)

    def tearDown(self):
        self.worker.close()
        self.tmp.cleanup()

    def test_session_params_run_real_pipeline_to_preview_and_finalize(self):
        self.session.transcribe()
        self.session.correct(TEXT.replace('strong', 'excellent'))
        candidates = self.session.review_candidates('excellent')
        containing = [c for c in candidates
                      if c['start'] <= WORDS[5]['start'] and c['end'] >= WORDS[5]['end']]
        self.assertTrue(containing)
        token = self.session.confirm_span(containing[0])
        params = self.session.span_params('excellent', 'superb',
                                          confirmation_token=token)
        params.update({'rights_confirmed': True, 'seed': 9})
        pv = self.session.preview(self.worker.edit_audio, 'replace', params)
        self.assertTrue(pv['technical_success'])
        self.assertIsNotNone(pv['output_path'])
        self.assertTrue(Path(pv['output_path']).is_file())
        dest = Path(self.tmp.name) / 'final.wav'
        record = self.session.finalize(pv['preview_id'], dest)
        self.assertTrue(dest.is_file())
        self.assertEqual(record['listening_review'], 'unscored')
        # finalize is idempotent: repeating it yields byte-identical output.
        first = dest.read_bytes()
        self.session.finalize(pv['preview_id'], dest)
        self.assertEqual(dest.read_bytes(), first)

    def test_accept_as_is_params_run_real_pipeline(self):
        # Unchanged transcript: no correct() call, measured confident span. Session
        # evidence is MAC-verified, then the worker's segment ASR re-verification and
        # every downstream gate still run. Ends at a saved, unscored preview.
        edited = TEXT.replace('visitors', 'guests')
        from auk_reliability.worker import ReliabilityWorker
        from auk_reliability.qa import SemanticQAGate
        def qa_transcriber(path):
            p = str(path)
            if p.endswith('input.wav'):  # the prepared segment slice
                return {'text': 'visitors', 'words': [{'word': 'visitors', 'start': 0.0,
                                                       'end': 0.6, 'probability': 0.95}]}
            base = TEXT if 'normalized-source' in p else edited
            words = [{'word': w, 'start': WORDS[i]['start'], 'end': WORDS[i]['end'],
                      'probability': 0.95} for i, w in enumerate(base.split())]
            return {'text': base, 'words': words}
        gate = SemanticQAGate(qa_transcriber, lambda a, b: .9)
        worker = ReliabilityWorker(self.adapter, Path(self.tmp.name) / 'runs-asis',
                                   semantic_gate=gate, runtime_profile={'simulation': True})
        try:
            session = TranscriptSession(self.src, fake_transcriber,
                                        Path(self.tmp.name) / 'session-asis',
                                        flow_registry=worker.flow_registry)
            session.transcribe()
            params = reviewed_params(session, 'visitors', 'guests')
            params.update({'rights_confirmed': True, 'seed': 9})
            pv = session.preview(worker.edit_audio, 'replace', params)
            self.assertTrue(pv['technical_success'])
            self.assertTrue(Path(pv['output_path']).is_file())
            dest = Path(self.tmp.name) / 'final-asis.wav'
            record = session.finalize(pv['preview_id'], dest)
            self.assertTrue(dest.is_file())
            self.assertEqual(record['listening_review'], 'unscored')
        finally:
            worker.close()

    def test_forged_accept_as_is_params_rejected_by_worker(self):
        forged = {'source_text': TEXT, 'rights_confirmed': True, 'seed': 9,
                  'segment_start_seconds': '0.2', 'segment_end_seconds': '0.8',
                  'segment_text': 'visitors', 'edited_segment_text': 'guests',
                  'original_text': 'visitors', 'replacement_text': 'guests',
                  'alignment_source': 'asr_accepted', 'span_confirmed': True}
        with self.assertRaises(EditorError) as ctx:
            self.worker.edit_audio(self.src, 'transcript_editor', 'replace', forged)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')

    def test_forged_corrected_params_rejected_by_worker(self):
        forged = {'source_text': TEXT, 'rights_confirmed': True, 'seed': 9,
                  'segment_start_seconds': '1.7', 'segment_end_seconds': '2.2',
                  'segment_text': 'strong', 'edited_segment_text': 'excellent',
                  'original_text': 'strong', 'replacement_text': 'excellent',
                  'alignment_source': 'user_corrected', 'span_confirmed': True}
        with self.assertRaises(EditorError) as ctx:
            self.worker.edit_audio(self.src, 'transcript_editor', 'replace', forged)
        self.assertEqual(ctx.exception.code, 'flow_evidence_invalid')


if __name__ == '__main__':
    unittest.main()


class UniversalCutReview(unittest.TestCase):
    """No acoustic accuracy claim: require an exact rendered-cut acknowledgement."""
    setUp = TranscriptFlow.setUp
    tearDown = TranscriptFlow.tearDown
    def test_confident_timing_fault_cannot_issue_without_listening(self):
        self.session.words[1].start += 0.35  # controlled upstream timing fault
        self.assertEqual(self.session.span_needs_review('visitors'), [])
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('visitors', 'guests')
        self.assertEqual(ctx.exception.code, 'span_review_required')

    def test_confident_candidate_modified_range_refused(self):
        entry = self.session.review_candidates('visitors')[0]
        entry['start'] += .1
        with self.assertRaises(EditorError) as ctx:
            self.session.confirm_span(entry)
        self.assertEqual(ctx.exception.code, 'confirmation_unbound')

    def test_unissued_candidate_refused(self):
        entry = self.session.review_candidates('visitors')[0]
        entry['id'] = 'not-issued'
        with self.assertRaises(EditorError) as ctx:
            self.session.confirm_span(entry)
        self.assertEqual(ctx.exception.code, 'confirmation_unbound')

    def test_explicit_adjustment_is_rendered_bound_and_usable(self):
        entries = self.session.review_candidates('visitors', start_adjust_seconds=-.1,
                                                  end_adjust_seconds=.2)
        self.assertEqual(len(entries), 1)
        token = self.session.confirm_span(entries[0])  # simulated acknowledgement
        params = self.session.span_params('visitors', 'guests', confirmation_token=token)
        self.assertAlmostEqual(float(params['segment_start_seconds']), .1)
        self.assertAlmostEqual(float(params['segment_end_seconds']), 1.0)
        with wave.open(entries[0]['path']) as w:
            self.assertAlmostEqual(w.getnframes()/24000, .9)

    def test_nonfinite_adjustment_refused(self):
        for value in (float('nan'), float('inf')):
            with self.assertRaises(EditorError) as ctx:
                self.session.review_candidates('visitors', start_adjust_seconds=value)
            self.assertEqual(ctx.exception.code, 'invalid_boundary_adjustment')

    def test_outside_recording_adjustment_refused(self):
        with self.assertRaises(EditorError) as ctx:
            self.session.review_candidates('visitors', start_adjust_seconds=-2)
        self.assertEqual(ctx.exception.code, 'candidate_out_of_range')

    def test_changed_source_invalidates_confirmation(self):
        entry = self.session.review_candidates('visitors')[0]
        write_wav(self.src, seconds=5)
        with self.assertRaises(EditorError) as ctx:
            self.session.confirm_span(entry)
        self.assertEqual(ctx.exception.code, 'source_changed')

    def test_confident_token_is_single_use(self):
        entry = self.session.review_candidates('visitors')[0]
        token = self.session.confirm_span(entry)
        self.session.span_params('visitors', 'guests', confirmation_token=token)
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('visitors', 'guests', confirmation_token=token)
        self.assertEqual(ctx.exception.code, 'span_review_required')


class ReviewedEdgePropagation(unittest.TestCase):
    setUp = TranscriptFlow.setUp
    tearDown = TranscriptFlow.tearDown

    def test_adjusted_changed_edge_reaches_actual_transplant(self):
        from auk_reliability.transplant import localized_transplant
        import math, array
        # Actual PCM splice, deterministic donor and recognizer fixture, no AI
        # generation or human-listening claim.
        for name, freq in [('source-tone.wav', .08), ('donor-tone.wav', .11)]:
            path = Path(self.tmp.name) / name
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                w.writeframes(array.array('h', (int(6000*math.sin(i*freq))
                                                for i in range(4*24000))).tobytes())
        src = Path(self.tmp.name) / 'source-tone.wav'
        donor = Path(self.tmp.name) / 'donor-tone.wav'
        session = TranscriptSession(src, fake_transcriber, Path(self.tmp.name)/'tone-session',
                                    flow_registry=self.registry)
        session.transcribe()
        session.words[0].end = .1
        session.words[2].start = 1.0
        entry = session.review_candidates('visitors', start_adjust_seconds=-.1,
                                          end_adjust_seconds=.2)[0]
        params = session.span_params('visitors', 'guests',
                                     confirmation_token=session.confirm_span(entry))
        self.assertEqual(float(params['changed_span_words'][0]['start']), .1)
        self.assertEqual(float(params['changed_span_words'][0]['end']), 1.0)
        def donor_asr(path):
            self.assertEqual(Path(path), donor)  # stale source ASR not used
            return {'text': TEXT.replace('visitors', 'guests'), 'words': [
                dict(w, word='guests', start=.3, end=.7) if w['word']=='visitors' else
                dict(w, end=.1) if w['word']=='The' else
                dict(w, start=1.2, end=1.3) if w['word']=='are' else dict(w)
                for w in WORDS]}
        out = Path(self.tmp.name)/'actual-splice.wav'
        record = localized_transplant(src, donor, donor_asr, .1, 1.0, TEXT,
                                      TEXT.replace('visitors', 'guests'), out,
                                      measured_span=params['changed_span_words'])
        self.assertEqual(record['source_cut_seconds'], [.1, 1.0])
        with wave.open(str(src)) as w: original = w.readframes(w.getnframes())
        with wave.open(str(out)) as w: result = w.readframes(w.getnframes())
        self.assertEqual(len(original), len(result))
        self.assertEqual(original[:4800], result[:4800])
        self.assertEqual(original[48000:], result[48000:])

    def test_wider_phrase_edge_does_not_move_internal_changed_word(self):
        entry = self.session.review_candidates('The visitors are',
                                               end_adjust_seconds=.1)[0]
        p = self.session.span_params('The visitors are', 'The guests are',
                                     confirmation_token=self.session.confirm_span(entry))
        self.assertEqual(p['changed_span_words'], [dict(word='visitors', start='0.2', end='0.8', previous_word_end='0.2', next_word_start='0.8')])

    def test_reviewed_edge_cannot_invert_changed_word(self):
        entry = self.session.review_candidates('visitors are however',
                                               start_adjust_seconds=.7)[0]
        with self.assertRaises(EditorError) as ctx:
            self.session.span_params('visitors are however', 'guests are however',
                                     confirmation_token=self.session.confirm_span(entry))
        self.assertEqual(ctx.exception.code, 'reviewed_word_range_invalid')

    def test_neighbor_metadata_is_bound_to_worker_evidence(self):
        params=reviewed_params(self.session,'visitors','guests')
        params['changed_span_words'][0]['next_word_start']='2.0'
        with self.assertRaises(EditorError) as ctx:
            verify_alignment(self.src,params,lambda p:{'text':'visitors'},flow_registry=self.registry)
        self.assertEqual(ctx.exception.code,'flow_evidence_invalid')
