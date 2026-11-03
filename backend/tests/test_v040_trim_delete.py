import unittest, tempfile, wave, array, math, json
from pathlib import Path
from auk_reliability.worker import ReliabilityWorker
from auk_reliability.qa import SemanticQAGate
from auk_reliability.trimdelete import boundary_estimate, candidate_cuts, trim_delete
from auk_reliability.policy import plan_request
from auk_reliability.core import Limits

def tone(path, seconds, freq_step=.057, amp=6000):
    a = array.array('h', (int(amp*math.sin(i*freq_step)) for i in range(round(seconds*24000))))
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(a.tobytes())
    return path

WORDS = [{'word': 'He', 'start': 0.0, 'end': 0.5}, {'word': 'scored', 'start': 0.55, 'end': 1.26},
         {'word': 'one', 'start': 1.30, 'end': 1.60}, {'word': 'goal', 'start': 1.65, 'end': 2.0},
         {'word': 'and', 'start': 2.05, 'end': 2.3}, {'word': 'was', 'start': 2.35, 'end': 2.6},
         {'word': 'on', 'start': 2.62, 'end': 2.8}, {'word': 'fire', 'start': 2.85, 'end': 3.18}]
SRC_TEXT = 'He scored one goal and was on fire.'
EXPECTED = 'one goal and was on fire.'

class Adapter:
    def __init__(self):
        self.calls = []
    def run(self, profile, input_audio, plan):
        self.calls.append(dict(plan))
        out = Path(input_audio).parent / 'vendor-out.wav'
        tone(out, float(plan.get('target_seconds') or 2.0))
        return {'audio': __import__('base64').b64encode(out.read_bytes()).decode()}, {'wall_ms': 5}
    def stop(self):
        pass

DELETE_P = {'source_text': SRC_TEXT, 'rights_confirmed': True, 'seed': 42, 'profile': 'base_f32',
            'segment_scope': 'whole_clip', 'segment_text': SRC_TEXT,
            'segment_start_seconds': 0, 'segment_end_seconds': 3.18,
            'text': 'He scored', 'edited_segment_text': EXPECTED}

class BoundaryEstimateTests(unittest.TestCase):
    def test_prefix(self):
        est = boundary_estimate(WORDS, SRC_TEXT, 'He scored')
        self.assertEqual(est, {'direction': 'prefix', 'estimate': 1.26})
    def test_suffix(self):
        est = boundary_estimate(WORDS, SRC_TEXT, 'on fire.')
        self.assertEqual(est, {'direction': 'suffix', 'estimate': 2.62})
    def test_interior_returns_none(self):
        self.assertIsNone(boundary_estimate(WORDS, SRC_TEXT, 'one goal'))
    def test_asr_mismatch_returns_none(self):
        bad = [dict(w, word='xyz') for w in WORDS[:1]] + WORDS[1:]
        self.assertIsNone(boundary_estimate(bad, SRC_TEXT, 'He scored'))

class CandidateCutTests(unittest.TestCase):
    def test_prefix_offsets_and_clamps(self):
        cuts = candidate_cuts('prefix', 1.26, 3.18)
        self.assertEqual(cuts[0], 1.21)
        self.assertIn(1.56, cuts)
        self.assertTrue(all(0.05 < c < 3.18 - 0.3 + 1e-9 or c <= 3.18 for c in cuts))
        cuts = candidate_cuts('prefix', 0.01, 3.18)
        self.assertTrue(all(c >= 0.05 for c in cuts))
    def test_suffix_offsets(self):
        cuts = candidate_cuts('suffix', 2.62, 3.18)
        self.assertEqual(cuts[0], 2.67)
        self.assertIn(2.32, cuts)

class TrimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.src = tone(self.root/'src.wav', 3.0)
    def tearDown(self):
        self.temp.cleanup()
    def test_prefix_trim_duration_and_fade(self):
        info = trim_delete(self.src, self.root/'out.wav', 1.0, 'prefix')
        self.assertAlmostEqual(info['out_duration'], 2.0, places=2)
        with wave.open(str(self.root/'out.wav'), 'rb') as f:
            self.assertEqual(f.getnframes(), 48000)
            f.rewind(); first = f.readframes(8)
        self.assertEqual(max(array.array('h', first)), 0)  # fade-in starts at zero
    def test_suffix_trim(self):
        info = trim_delete(self.src, self.root/'out2.wav', 2.0, 'suffix')
        self.assertAlmostEqual(info['out_duration'], 2.0, places=2)

class PolicyTests(unittest.TestCase):
    def test_delete_uses_verbatim_tts_instruction(self):
        plan = plan_request('transcript_editor', 'delete', dict(DELETE_P), 3.18, Limits())
        self.assertEqual(plan['operation'], 'custom')
        self.assertEqual(plan['instruction'], "Say the following with the same voice: 'one goal and was on fire.'")
        self.assertNotIn('Replace', plan['instruction'])
    def test_delete_duration_scaling_kept(self):
        plan = plan_request('transcript_editor', 'delete', dict(DELETE_P), 3.18, Limits())
        # 8 words -> 6 words: v0.2.7 word-ratio scaling still applies
        self.assertAlmostEqual(plan['target_seconds'], round(3.18 * 0.75, 1), places=3)

class WorkerTrimTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.src = tone(self.root/'src.wav', 3.18)
        self.adapter = Adapter()
    def tearDown(self):
        self.temp.cleanup()
    def _worker(self, gate):
        return ReliabilityWorker(self.adapter, self.root/'runs', semantic_gate=gate,
                                 runtime_profile={'simulation': True})
    def test_trim_selected_no_vendor_call(self):
        def tx(path):
            name = Path(path).name
            if name == 'input.wav':
                return {'text': SRC_TEXT, 'words': WORDS}
            return {'text': EXPECTED, 'words': []}
        gate = SemanticQAGate(tx, lambda a, b: .9)
        r = self._worker(gate).edit_audio(self.src, 'transcript_editor', 'delete', dict(DELETE_P))
        self.assertTrue(r.automatic_qa_pass)
        self.assertEqual(r.outcome, 'qa_pass_review_pending')
        self.assertEqual(len(self.adapter.calls), 0)
        rec = r.attempts[0]
        self.assertEqual(rec['mechanism'], 'dsp_boundary_trim_candidate_selection')
        self.assertTrue(rec['selected'])
        self.assertEqual(len(rec['trim']['candidates']), 1)  # first candidate passed, stop
        self.assertEqual(rec['trim']['direction'], 'prefix')
    def test_trim_all_candidates_fail_falls_to_vendor(self):
        def tx(path):
            name = Path(path).name
            if name == 'input.wav':
                return {'text': SRC_TEXT, 'words': WORDS}
            if name.startswith('trim-candidate'):
                return {'text': 'scored one goal and was on fire.', 'words': []}  # residue -> gate fail
            return {'text': EXPECTED, 'words': []}  # vendor output passes
        gate = SemanticQAGate(tx, lambda a, b: .9)
        r = self._worker(gate).edit_audio(self.src, 'transcript_editor', 'delete', dict(DELETE_P))
        self.assertTrue(r.automatic_qa_pass)
        self.assertGreaterEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.adapter.calls[0]['instruction'],
                         "Say the following with the same voice: 'one goal and was on fire.'")
        self.assertTrue((Path(r.request_dir)/'trim-delete.json').exists())
        rec = json.loads((Path(r.request_dir)/'trim-delete.json').read_text())
        self.assertEqual(rec['failure_reason'], 'trim_no_candidate_passed')
        self.assertEqual(len(rec['trim']['candidates']), 8)
    def test_interior_delete_skips_trim(self):
        p = dict(DELETE_P)
        p['text'] = 'one goal'
        p['edited_segment_text'] = 'He scored and was on fire.'
        def tx(path):
            if Path(path).name == 'input.wav':
                return {'text': SRC_TEXT, 'words': WORDS}
            return {'text': 'He scored and was on fire.', 'words': []}
        gate = SemanticQAGate(tx, lambda a, b: .9)
        r = self._worker(gate).edit_audio(self.src, 'transcript_editor', 'delete', p)
        self.assertTrue(r.automatic_qa_pass)
        self.assertGreaterEqual(len(self.adapter.calls), 1)
        self.assertFalse((Path(r.request_dir)/'trim-delete.json').exists())
        self.assertNotIn('mechanism', r.attempts[0])

if __name__ == '__main__':
    unittest.main()
