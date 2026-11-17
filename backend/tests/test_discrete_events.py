import unittest

import numpy as np

from auk_reliability.enhance import EnhanceConfig, suppress_discrete_events

SR = 24000


def db_of(x):
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2))), 1e-12))


def synth(bed_db=-70.0, speech_db=-18.0, breath_db=-45.0, breath_s=0.2, seed=7):
    """3s: noise bed; speech burst 1.0-1.4s; breath event 2.0-2.0+breath_s."""
    rng = np.random.default_rng(seed)
    y = rng.normal(0.0, 10.0 ** (bed_db / 20.0), 3 * SR)
    t = np.arange(int(0.4 * SR)) / SR
    speech = (0.6 * np.sin(2 * np.pi * 200 * t) + 0.4 * rng.normal(0, 1, t.size))
    speech *= (10.0 ** (speech_db / 20.0)) / np.sqrt(np.mean(speech ** 2))
    y[int(1.0 * SR):int(1.4 * SR)] += speech
    nb = int(breath_s * SR)
    breath = rng.normal(0.0, 1.0, nb)
    breath *= (10.0 ** (breath_db / 20.0)) / np.sqrt(np.mean(breath ** 2))
    y[int(2.0 * SR):int(2.0 * SR) + nb] += breath
    return y.astype(np.float64)


class DiscreteEventSuppressTests(unittest.TestCase):
    def cfg(self, **kw):
        c = EnhanceConfig(discrete_event_suppress=True)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_breath_event_ducked_toward_bed(self):
        y = synth()
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 1)
        seg = out[int(2.05 * SR):int(2.15 * SR)]
        self.assertLessEqual(db_of(seg), -63.0)  # ~bed level (was -45)
        self.assertGreaterEqual(db_of(seg), -76.0)
        self.assertGreater(stats['max_atten_db'], 6.0)
        self.assertLessEqual(stats['max_atten_db'], 20.0)

    def test_speech_samples_untouched(self):
        y = synth()
        out, _ = suppress_discrete_events(y, SR, self.cfg())
        span = slice(int(1.02 * SR), int(1.38 * SR))
        self.assertTrue(np.array_equal(y[span], out[span]))

    def test_length_preserved(self):
        y = synth()
        out, _ = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(len(out), len(y))

    def test_short_blip_ignored(self):
        y = synth(breath_s=0.03)  # 30 ms < 60 ms minimum
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_loud_breath_near_speech_level_protected(self):
        # A breath within the speech dynamic range (like the 3:41 loud breath both
        # Adobe and the candidate keep) must not be treated as an event.
        y = synth(breath_db=-30.0)
        out, stats = suppress_discrete_events(y, SR, self.cfg(des_speech_range_db=15.0))
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_silence_noop(self):
        y = np.zeros(2 * SR)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_tiny_input_noop(self):
        y = np.zeros(100)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)

    def test_flag_default_off(self):
        self.assertFalse(EnhanceConfig().discrete_event_suppress)

    def test_no_nan_or_clipping_growth(self):
        y = synth()
        out, _ = suppress_discrete_events(y, SR, self.cfg())
        self.assertTrue(np.all(np.isfinite(out)))
        self.assertLessEqual(float(np.max(np.abs(out))), float(np.max(np.abs(y))) + 1e-9)


if __name__ == '__main__':
    unittest.main()
