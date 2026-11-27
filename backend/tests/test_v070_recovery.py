"""2026-11-27 recovery fixes from the 2026-11-27 staging report: emotion prosody fallback,
localized duration-mismatch retry, opt-in wider-context readback. Fixtures are synthetic
tones with scripted ASR/speaker callables: they test routing and gates, not model quality."""
import importlib.util, unittest, tempfile, wave, array, math, base64, shutil
from pathlib import Path
from unittest import mock
from auk_reliability.worker import ReliabilityWorker
from auk_reliability.qa import SemanticQAGate
from auk_reliability.core import EditorError, Limits
from auk_reliability.segment import verify_alignment, verify_segment_in_context

def tone(path, seconds, freq_step=.057, amp=6000):
    a = array.array('h', (int(amp * math.sin(i * freq_step)) for i in range(round(seconds * 24000))))
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(a.tobytes())
    return path

class ToneAdapter:
    def __init__(self):
        self.calls = []
    def run(self, profile, input_audio, plan):
        self.calls.append(dict(plan))
        out = Path(input_audio).parent / ('vendor-%d.wav' % len(self.calls))
        tone(out, float(plan.get('target_seconds') or 3.0), freq_step=.05 + .01 * len(self.calls))
        return {'audio': base64.b64encode(out.read_bytes()).decode()}, {'fixture': True}
    def stop(self):
        pass

def _fake_transplant(prepared, donor, out):
    shutil.copy(prepared, out)
    return {'fixture': 'fake_transplant'}

class EmotionFallbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.src = tone(self.root / 'src.wav', 3.0)
        self.p = {'source_text': 'hello world', 'rights_confirmed': True, 'seed': 9, 'emotion': 'excited'}
    def tearDown(self):
        self.temp.cleanup()
    def _run(self, fallback_text, speaker=.9, op='emotion', attempts=1):
        def tx(path):
            return {'text': fallback_text if Path(path).name == 'emotion-prosody.wav' else 'hello whirled'}
        w = ReliabilityWorker(ToneAdapter(), self.root / 'runs', semantic_gate=SemanticQAGate(tx, lambda a, b: speaker),
                              max_attempts=attempts)
        try:
            with mock.patch('auk_reliability.worker.prosody_transplant', _fake_transplant):
                return w.edit_audio(self.src, 'voice_editor', op, dict(self.p)), w.adapter
        finally:
            w.close()
    def test_raw_words_changed_then_fallback_passes_gate(self):
        r, _ = self._run('hello world')
        self.assertTrue(r.automatic_qa_pass)
        self.assertEqual(r.outcome, 'qa_pass_review_pending')
        rec = r.attempts[0]
        self.assertEqual(rec['selected_mechanism'], 'emotion_prosody_transplant')
        self.assertEqual(rec['emotion_prosody_fallback']['mechanism'], 'prosody_transplant_intonation_only')
        self.assertTrue(r.output_path.endswith('emotion-prosody.wav'))
    def test_fallback_that_fails_the_same_gate_is_not_selected(self):
        r, _ = self._run('hello whirled')
        self.assertFalse(r.automatic_qa_pass)
        self.assertIsNone(r.output_path)
        self.assertIn('emotion_prosody_fallback', r.attempts[0])
        self.assertNotIn('selected_mechanism', r.attempts[0])
    def test_fallback_still_requires_speaker_gate(self):
        r, _ = self._run('hello world', speaker=.5)
        self.assertFalse(r.automatic_qa_pass)
        self.assertIsNone(r.output_path)
    def test_missing_pyworld_fails_safe_and_keeps_original_failure(self):
        import builtins
        real_import = builtins.__import__
        def no_world(name, *a, **k):
            if name == 'pyworld':
                raise ImportError('simulated missing pyworld')
            return real_import(name, *a, **k)
        def tx(path):
            return {'text': 'hello whirled'}
        w = ReliabilityWorker(ToneAdapter(), self.root / 'runs3', semantic_gate=SemanticQAGate(tx, lambda a, b: .9), max_attempts=1)
        try:
            with mock.patch('builtins.__import__', no_world):
                r = w.edit_audio(self.src, 'voice_editor', 'emotion', dict(self.p))
        finally:
            w.close()
        rec = r.attempts[0]
        self.assertFalse(r.automatic_qa_pass); self.assertIsNone(r.output_path)
        self.assertEqual(r.reason, 'qa_failed')  # original failure not masked
        self.assertEqual(rec['emotion_prosody_fallback_error'], 'stylefix_unavailable')
    def test_other_operations_do_not_use_fallback(self):
        r, _ = self._run('hello world', op='whisper')
        self.assertNotIn('emotion_prosody_fallback', r.attempts[0])
    def test_raw_pass_keeps_raw_output(self):
        def tx(path):
            return {'text': 'hello world'}
        w = ReliabilityWorker(ToneAdapter(), self.root / 'runs2', semantic_gate=SemanticQAGate(tx, lambda a, b: .9))
        try:
            r = w.edit_audio(self.src, 'voice_editor', 'emotion', dict(self.p))
        finally:
            w.close()
        self.assertTrue(r.automatic_qa_pass)
        self.assertNotIn('emotion_prosody_fallback', r.attempts[0])

@unittest.skipUnless(importlib.util.find_spec('pyworld'), 'pyworld not installed')
class RealProsodyTransplantTests(unittest.TestCase):
    def test_real_wold_transplant_runs_through_worker(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = tone(root / 'src.wav', 3.0)
            def tx(path):
                return {'text': 'hello world' if Path(path).name == 'emotion-prosody.wav' else 'hello whirled'}
            w = ReliabilityWorker(ToneAdapter(), root / 'runs', semantic_gate=SemanticQAGate(tx, lambda a, b: .9), max_attempts=1)
            try:
                r = w.edit_audio(src, 'voice_editor', 'emotion', {'source_text': 'hello world', 'rights_confirmed': True, 'seed': 9, 'emotion': 'excited'})
            finally:
                w.close()
            self.assertEqual(r.attempts[0].get('emotion_prosody_fallback_error'), None)
            self.assertTrue(r.automatic_qa_pass)

class PackagingTests(unittest.TestCase):
    def test_pyproject_pins_pyworld_and_compatible_setuptools(self):
        text = (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text()
        self.assertIn('pyworld==0.3.5', text); self.assertIn('setuptools<81', text)
    def test_health_check_reports_missing_dependency(self):
        import builtins
        from auk_reliability.stylefix import prosody_transplant_health
        real = builtins.__import__
        def no_world(name, *a, **k):
            if name == 'pyworld':
                raise ModuleNotFoundError("No module named 'pkg_resources'")
            return real(name, *a, **k)
        with mock.patch('builtins.__import__', no_world):
            ok, why = prosody_transplant_health()
        self.assertFalse(ok); self.assertIn('pkg_resources', why)
    @unittest.skipUnless(importlib.util.find_spec('pyworld'), 'pyworld not installed')
    def test_health_check_ok_when_installed(self):
        from auk_reliability.stylefix import prosody_transplant_health
        self.assertEqual(prosody_transplant_health(), (True, ''))

class ContextReadbackTests(unittest.TestCase):
    PARAMS = {'segment_text': 'where', 'alignment_source': 'asr_accepted', 'span_confirmed': True}
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.src = tone(self.root / 'src.wav', 4.0)
        self.cut = tone(self.root / 'cut.wav', 0.6)
    def tearDown(self):
        self.temp.cleanup()
    def _ctx(self, words, **extra):
        params = {**self.PARAMS, 'readback_context_seconds': 0.5, **extra}
        def tx(path):
            return {'text': ' '.join(w['word'] for w in words), 'words': words}
        # window starts at 1.5 (interval 2.0-2.6, context .5): cut is 0.5-1.1 inside it
        verify_segment_in_context(self.src, params, tx, 2.0, 2.6, self.root, Limits())
    def test_exact_words_inside_cut_pass(self):
        self._ctx([{'word': 'said', 'start': 0.0, 'end': 0.4}, {'word': 'where', 'start': 0.5, 'end': 1.1},
                   {'word': 'we', 'start': 1.15, 'end': 1.4}])
    def test_wrong_word_inside_cut_fails(self):
        with self.assertRaises(EditorError) as c:
            self._ctx([{'word': "we're", 'start': 0.5, 'end': 1.1}])
        self.assertEqual(c.exception.code, 'segment_transcript_mismatch')
    def test_neighbour_word_crossing_cut_edge_fails(self):
        with self.assertRaises(EditorError) as c:
            self._ctx([{'word': 'said', 'start': 0.1, 'end': 0.7}, {'word': 'where', 'start': 0.7, 'end': 1.1}])
        self.assertEqual(c.exception.code, 'segment_transcript_mismatch')
    def test_extra_word_inside_cut_fails(self):
        with self.assertRaises(EditorError):
            self._ctx([{'word': 'so', 'start': 0.5, 'end': 0.75}, {'word': 'where', 'start': 0.8, 'end': 1.1}])
    def test_invalid_context_value_rejected(self):
        for bad in (0, -1, 1.5, 'x'):
            with self.assertRaises(EditorError) as c:
                self._ctx([{'word': 'where', 'start': 0.5, 'end': 1.1}], readback_context_seconds=bad)
            self.assertEqual(c.exception.code, 'invalid_readback_context')
    def test_not_opted_in_keeps_original_failure_and_never_calls_context(self):
        called = []
        reg = self.root / 'reg'; reg.mkdir()
        with mock.patch('auk_reliability.segment.flow_evidence_verify', return_value=True):
            with self.assertRaises(EditorError) as c:
                verify_alignment(self.cut, {**self.PARAMS, 'source_text': 'where', 'flow_evidence': {'session_id': 's'}},
                                 lambda p: {'text': "we're"}, flow_registry=reg, context_check=lambda: called.append(1))
        self.assertEqual(c.exception.code, 'segment_transcript_mismatch'); self.assertEqual(called, [])
    def test_opted_in_isolated_failure_defers_to_context_check(self):
        called = []
        reg = self.root / 'reg'; reg.mkdir()
        with mock.patch('auk_reliability.segment.flow_evidence_verify', return_value=True):
            verify_alignment(self.cut, {**self.PARAMS, 'readback_context_seconds': .5, 'source_text': 'where',
                                        'flow_evidence': {'session_id': 's'}},
                             lambda p: {'text': "we're"}, flow_registry=reg, context_check=lambda: called.append(1))
        self.assertEqual(called, [1])

class ReadbackExposureTests(unittest.TestCase):
    def _worker(self, root, flag):
        def tx(path):
            return {'text': 'bbb'}
        return ReliabilityWorker(ToneAdapter(), root / ('r%s' % flag), semantic_gate=SemanticQAGate(tx, lambda a, b: .9),
                                 experimental_context_readback=flag)
    P = {'source_text': 'aaa bbb ccc', 'segment_text': 'bbb', 'edited_segment_text': 'bbb ddd',
         'segment_start_seconds': 1.0, 'segment_end_seconds': 2.0, 'alignment_verified': True,
         'rights_confirmed': True, 'seed': 42, 'readback_context_seconds': 0.5}
    def test_default_worker_refuses_the_parameter_before_any_generation(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = tone(root / 'src.wav', 4.0); w = self._worker(root, False)
            self.assertFalse(w.experimental_context_readback)
            try:
                with self.assertRaises(EditorError) as c:
                    w.edit_audio(src, 'transcript_editor', 'replace', dict(self.P))
                self.assertEqual(c.exception.code, 'experimental_readback_disabled')
                self.assertEqual(w.adapter.calls, [])
            finally:
                w.close()
    def test_constructor_default_is_off(self):
        import inspect
        self.assertFalse(inspect.signature(ReliabilityWorker.__init__).parameters['experimental_context_readback'].default)
    def test_parameter_absent_keeps_default_behavior(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t); src = tone(root / 'src.wav', 4.0); w = self._worker(root, False)
            p = {k: v for k, v in self.P.items() if k != 'readback_context_seconds'}
            try:
                try:
                    w.edit_audio(src, 'transcript_editor', 'replace', p)
                except EditorError as e:
                    self.assertNotEqual(e.code, 'experimental_readback_disabled')
            finally:
                w.close()

class DurationMismatchRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.src = tone(self.root / 'src.wav', 4.0)
        self.p = {'source_text': 'aaa bbb ccc', 'segment_text': 'bbb', 'edited_segment_text': 'bbb ddd',
                  'segment_start_seconds': 1.0, 'segment_end_seconds': 2.0, 'alignment_verified': True,
                  'rights_confirmed': True, 'seed': 42}
    def tearDown(self):
        self.temp.cleanup()
    def _worker(self):
        def tx(path):
            return {'text': 'bbb' if Path(path).name == 'input.wav' else 'aaa bbb ddd ccc'}
        return ReliabilityWorker(ToneAdapter(), self.root / 'runs', semantic_gate=SemanticQAGate(tx, lambda a, b: .9))
    def test_mismatch_retries_with_new_seed_and_records_options(self):
        calls = []
        def fake(full, out, tr, s, e, st, et, final, **kw):
            calls.append(1)
            if len(calls) == 1:
                raise EditorError('transplant_duration_mismatch', 'does not fit')
            shutil.copy(full, final)
            return {'source_cut_seconds': [s, e]}
        w = self._worker()
        try:
            with mock.patch('auk_reliability.worker.localized_transplant', fake):
                r = w.edit_audio(self.src, 'transcript_editor', 'insert', {**self.p, 'anchor': 'bbb', 'text': 'ddd', 'position': 'after'})
        finally:
            w.close()
        self.assertEqual(len(r.attempts), 2)
        self.assertEqual(r.attempts[0]['failure_reason'], 'transplant_duration_mismatch')
        opts = {o['option']: o for o in r.attempts[0]['recovery_options']}
        self.assertTrue(opts['retry_other_seed']['automatic'])
        self.assertFalse(opts['widen_interval']['automatic']); self.assertFalse(opts['whole_clip_scope']['automatic'])
        self.assertNotEqual(r.attempts[0]['plan']['seed'], r.attempts[1]['plan']['seed'])
    def test_persistent_mismatch_ends_without_output(self):
        def fake(*a, **k):
            raise EditorError('transplant_duration_mismatch', 'does not fit')
        w = self._worker()
        try:
            with mock.patch('auk_reliability.worker.localized_transplant', fake):
                r = w.edit_audio(self.src, 'transcript_editor', 'insert', {**self.p, 'anchor': 'bbb', 'text': 'ddd', 'position': 'after'})
        finally:
            w.close()
        self.assertIsNone(r.output_path); self.assertEqual(r.reason, 'transplant_duration_mismatch')
        self.assertEqual(len(r.attempts), 3)

if __name__ == '__main__':
    unittest.main()
