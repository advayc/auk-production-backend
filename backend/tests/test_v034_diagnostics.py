import array, math, sys, tempfile, unittest, wave
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_backend
from auk_reliability.diagnostics import classify_transcript_disagreement, outside_interval_pcm_exact
from auk_reliability.seam import seam_report


def write_samples(path, samples, rate=24000):
    a = array.array('h', samples)
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate); f.writeframes(a.tobytes())
    return path


def sine(n, amp=6000, phase=0.0):
    return [int(amp * math.sin(2 * math.pi * 440 * i / 24000 + phase)) for i in range(n)]


class SeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def test_continuous_join_scores_low(self):
        p = write_samples(self.root / 'smooth.wav', sine(48000))
        r = seam_report(p, [1.0])
        b = r['boundaries'][0]
        self.assertLess(b['jump_peak'], 0.05)
        self.assertLess(b['flux_ratio'], 2.0)

    def test_discontinuous_join_flags(self):
        smooth = write_samples(self.root / 's.wav', sine(48000))
        clicky = write_samples(self.root / 'c.wav', sine(24000) + sine(24000, phase=math.pi / 2))
        sb = seam_report(smooth, [1.0])['boundaries'][0]
        cb = seam_report(clicky, [1.0])['boundaries'][0]
        self.assertGreater(cb['jump_peak'], 5 * sb['jump_peak'])
        self.assertGreater(cb['flux_ratio'], 1.5 * sb['flux_ratio'])
        self.assertGreater(cb['jump_peak'], 0.1)

    def test_report_is_diagnostic_only(self):
        r = seam_report(write_samples(self.root / 'x.wav', sine(48000)), [0.5, 1.5])
        self.assertEqual(len(r['boundaries']), 2)
        self.assertIn('never changes pass/fail', r['note'])


class OutsideExactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()

    def test_exact_outside(self):
        src = sine(48000)
        out = list(src); out[24000:36000] = sine(12000, phase=1.0)  # change inside [1.0, 1.5)
        a = write_samples(self.root / 'a.wav', src); b = write_samples(self.root / 'b.wav', out)
        self.assertTrue(outside_interval_pcm_exact(a, b, 1.0, 1.5))
        out2 = list(src); out2[100] += 100  # change outside
        c = write_samples(self.root / 'c.wav', out2)
        self.assertFalse(outside_interval_pcm_exact(a, c, 1.0, 1.5))

    def test_length_mismatch_is_not_exact(self):
        a = write_samples(self.root / 'a.wav', sine(48000))
        b = write_samples(self.root / 'b.wav', sine(24000))
        self.assertFalse(outside_interval_pcm_exact(a, b, 0.5, 1.0))


def qa_dict(expected, observed, diff_passed=False, speaker_passed=True):
    return {'automatic_pass': False, 'unverified': [],
            'checks': {'transcript': {'passed': diff_passed, 'expected': expected, 'observed': observed,
                                      'error_rate': 0.25, 'status': 'review_required'},
                       'speaker': {'passed': speaker_passed, 'score': 0.9, 'threshold': 0.75}}}


class ClassifierTests(unittest.TestCase):
    WORDS_OUTSIDE = [{'word': 'There', 'start': 0.0, 'end': 0.4}, {'word': 'watch', 'start': 0.4, 'end': 0.7},
                     {'word': 'shows', 'start': 0.7, 'end': 1.2}]

    def test_small_disagreement_without_timings_is_unlocated(self):
        c = classify_transcript_disagreement(qa_dict('They watch shows', 'There watch shows'), outside_exact=True)
        self.assertIsNotNone(c)
        self.assertEqual(c['failure_class'], 'transcript_disagreement_unlocated_candidate')
        self.assertEqual(c['differing_token_count'], 1)
        self.assertIn('stays qa_failed', c['note'])

    def test_timed_outside_cut_is_unedited_span(self):
        c = classify_transcript_disagreement(qa_dict('They watch shows', 'There watch shows'),
                                             outside_exact=True, cut=[1.0, 1.5], timed_words=self.WORDS_OUTSIDE)
        self.assertEqual(c['failure_class'], 'transcript_disagreement_unedited_span_candidate')
        self.assertEqual(c['located_tokens'][0]['token'], 'there')

    def test_timed_inside_cut_is_edited_span(self):
        inside = [{'word': 'They', 'start': 0.0, 'end': 0.3}, {'word': 'watch', 'start': 0.4, 'end': 0.7},
                  {'word': 'Their', 'start': 1.1, 'end': 1.3}, {'word': 'shows', 'start': 1.5, 'end': 1.9}]
        c = classify_transcript_disagreement(qa_dict('They watch our shows', 'They watch Their shows'),
                                             outside_exact=True, cut=[1.0, 1.5], timed_words=inside)
        self.assertEqual(c['failure_class'], 'transcript_disagreement_edited_span_candidate')

    def test_deletion_diff_is_unlocated(self):
        c = classify_transcript_disagreement(qa_dict('They really watch shows', 'They watch shows'),
                                             outside_exact=True, cut=[1.0, 1.5],
                                             timed_words=[{'word': w, 'start': i, 'end': i + 0.3}
                                                          for i, w in enumerate(['They', 'watch', 'shows'])])
        self.assertEqual(c['failure_class'], 'transcript_disagreement_unlocated_candidate')

    def test_timing_count_mismatch_is_unlocated(self):
        c = classify_transcript_disagreement(qa_dict('They watch shows', 'There watch shows'),
                                             outside_exact=True, cut=[1.0, 1.5],
                                             timed_words=[{'word': 'There', 'start': 0.0, 'end': 0.4}])
        self.assertEqual(c['failure_class'], 'transcript_disagreement_unlocated_candidate')

    def test_large_disagreement_not_classified(self):
        self.assertIsNone(classify_transcript_disagreement(
            qa_dict('They watch shows', 'completely different sentence entirely'), outside_exact=True))

    def test_changed_outside_pcm_not_classified(self):
        self.assertIsNone(classify_transcript_disagreement(
            qa_dict('They watch shows', 'There watch shows'), outside_exact=False))

    def test_other_failing_check_not_classified(self):
        self.assertIsNone(classify_transcript_disagreement(
            qa_dict('They watch shows', 'There watch shows', speaker_passed=False), outside_exact=True))

    def test_passing_transcript_not_classified(self):
        self.assertIsNone(classify_transcript_disagreement(
            qa_dict('They watch shows', 'They watch shows', diff_passed=True), outside_exact=True))


class WorkerWiringTests(test_backend.BackendTests):
    """Localized replace where QA fails on a one-word disagreement: the attempt
    stays qa_failed, carries the diagnostic classification, the outside-interval
    byte-exact proof, and seam metrics. Pass/fail behavior is unchanged."""
    def _request(self, observed):
        p = {'source_text': 'They watch movies', 'segment_text': 'They watch movies',
             'original_text': 'movies', 'replacement_text': 'shows',
             'edited_segment_text': 'They watch shows',
             'segment_start_seconds': 0.5, 'segment_end_seconds': 2.5,
             'rights_confirmed': True, 'seed': 9}
        words = [{'word': w, 'start': i * 0.5, 'end': i * 0.5 + 0.4} for i, w in enumerate(observed.split())]
        self.gate.transcriber = lambda path: {'text': observed, 'words': words}

        def fake_transplant(full, out, transcriber, start, end, src_txt, edited, final, **kw):
            final.write_bytes(Path(full).read_bytes())
            return {'method': 'localized_context_transplant', 'source_cut_seconds': [1.0, 1.5]}
        with mock.patch('auk_reliability.worker.verify_alignment', lambda *a, **k: None), \
             mock.patch('auk_reliability.worker.localized_transplant', fake_transplant):
            return self.worker.edit_audio(self.source, 'transcript_editor', 'replace', p)

    def test_classification_and_diagnostics_recorded_on_failure(self):
        r = self._request('There watch shows')
        self.assertFalse(r.automatic_qa_pass)  # unchanged: still failed
        a = r.attempts[0]
        self.assertEqual(a['failure_reason'], 'qa_failed')
        self.assertTrue(a['outside_interval_pcm_exact'])
        self.assertEqual(a['failure_class']['failure_class'], 'transcript_disagreement_unedited_span_candidate')
        self.assertIn('seam', a)
        self.assertEqual(len(a['seam']['boundaries']), 2)

    def test_large_disagreement_gets_no_classification(self):
        r = self._request('nothing resembles the expected words at all now')
        a = r.attempts[0]
        self.assertEqual(a['failure_reason'], 'qa_failed')
        self.assertNotIn('failure_class', a)
        self.assertTrue(a['outside_interval_pcm_exact'])

    def test_matching_transcript_still_passes(self):
        r = self._request('They watch shows')
        self.assertTrue(r.automatic_qa_pass)  # pass path untouched
        self.assertNotIn('failure_class', r.attempts[0])


if __name__ == '__main__':
    unittest.main()
