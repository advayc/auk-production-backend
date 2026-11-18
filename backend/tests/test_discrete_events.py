import unittest

import numpy as np

from auk_reliability.enhance import EnhanceConfig, suppress_discrete_events

SR = 24000


def db_of(x):
    return 20.0 * np.log10(max(float(np.sqrt(np.mean(np.asarray(x, dtype=float) ** 2))), 1e-12))


def synth(bed_db=-70.0, speech_db=-18.0, breath_db=-45.0, breath_s=0.2, seed=7):
    """3s: noise bed; speech burst 1.0-1.4s; breath event 2.0-2.0+breath_s."""
    rng = np.random.default_rng(seed)
    n = max(3 * SR, int((2.0 + breath_s + 0.5) * SR))
    y = rng.normal(0.0, 10.0 ** (bed_db / 20.0), n)
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


class DiscreteEventSuppressNegativeExpansionTests(unittest.TestCase):
    """Negative/boundary coverage added 2026-11-17: pins the protection boundaries a
    production decision would rely on (DES stays default-OFF)."""

    def cfg(self, **kw):
        c = EnhanceConfig(discrete_event_suppress=True)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    def test_sustained_swell_untouched(self):
        # A 1.5 s elevated span exceeds des_max_event_ms (800 ms): content, not an event.
        y = synth(breath_db=-40.0, breath_s=1.5)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_event_just_under_max_ducked(self):
        # 700 ms < 800 ms max: still an event.
        y = synth(breath_db=-45.0, breath_s=0.7)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 1)
        seg = out[int(2.1 * SR):int(2.6 * SR)]
        self.assertLess(db_of(seg), -55.0)

    def test_speech_adjacent_to_event_bit_identical(self):
        # Event immediately after speech: the speech tail next to the attenuated region
        # must remain sample-exact (fades stay inside the event segment).
        y = synth()
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 1)
        span = slice(int(1.0 * SR), int(1.4 * SR))
        self.assertTrue(np.array_equal(y[span], out[span]))

    def test_frames_within_p95_range_protected(self):
        # Content within des_speech_range_db of the p95 frame level is speech-candidate
        # and must not be ducked, even when it sits inside a long quiet region.
        rng = np.random.default_rng(11)
        y = rng.normal(0.0, 10.0 ** (-70.0 / 20.0), 6 * SR)
        # loud speech elsewhere sets p95 around -18 dB
        t = np.arange(int(2.0 * SR)) / SR
        sp = np.sin(2 * np.pi * 220 * t)
        sp *= (10.0 ** (-18.0 / 20.0)) / np.sqrt(np.mean(sp ** 2))
        y[int(0.5 * SR):int(2.5 * SR)] += sp
        # mid-level burst at -38 dB (within 25 dB of p95) deep inside the quiet tail
        nb = int(0.3 * SR)
        burst = rng.normal(0.0, 1.0, nb)
        burst *= (10.0 ** (-38.0 / 20.0)) / np.sqrt(np.mean(burst ** 2))
        y[int(4.0 * SR):int(4.0 * SR) + nb] += burst
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_uniform_loud_bed_no_events(self):
        # Steady loud noise, no speech: nothing discrete to duck; must be bit-identical.
        rng = np.random.default_rng(3)
        y = rng.normal(0.0, 10.0 ** (-30.0 / 20.0), 3 * SR)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertTrue(np.array_equal(y, out))

    def test_two_events_in_one_region_both_ducked(self):
        rng = np.random.default_rng(5)
        y = rng.normal(0.0, 10.0 ** (-70.0 / 20.0), 5 * SR)
        t = np.arange(int(0.4 * SR)) / SR
        sp = np.sin(2 * np.pi * 200 * t)
        sp *= (10.0 ** (-18.0 / 20.0)) / np.sqrt(np.mean(sp ** 2))
        y[int(0.5 * SR):int(0.9 * SR)] += sp
        for start in (2.0, 3.5):
            nb = int(0.2 * SR)
            br = rng.normal(0.0, 1.0, nb)
            br *= (10.0 ** (-45.0 / 20.0)) / np.sqrt(np.mean(br ** 2))
            y[int(start * SR):int(start * SR) + nb] += br
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 2)
        self.assertLess(db_of(out[int(2.05 * SR):int(2.15 * SR)]), -63.0)
        self.assertLess(db_of(out[int(3.55 * SR):int(3.65 * SR)]), -63.0)

    def test_attenuation_capped_at_max(self):
        # Event 25 dB above the local bed (-45 vs -70): requested duck exceeds the
        # des_max_atten_db=20 cap, so only 20 dB is applied (lands ~-65 dB).
        y = synth(breath_db=-45.0, breath_s=0.2)
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 1)
        self.assertLessEqual(stats['max_atten_db'], 20.0 + 1e-9)
        seg = out[int(2.05 * SR):int(2.15 * SR)]
        self.assertGreaterEqual(db_of(seg), -67.0)
        self.assertLessEqual(db_of(seg), -63.0)

    def test_stereo_input_guard_returns_unchanged(self):
        y = np.zeros((2 * SR, 2))
        out, stats = suppress_discrete_events(y, SR, self.cfg())
        self.assertEqual(stats['events'], 0)
        self.assertIs(out, y)
