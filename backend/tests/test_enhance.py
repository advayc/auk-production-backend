"""voice_enhancer v0.5.0: measured analysis, adaptive strength, chunk/stitch
equivalence, blend, mastering, validation, and worker wiring with an echo adapter."""
import array, base64, io, math, tempfile, unittest, wave
from pathlib import Path
import numpy as np

from auk_reliability.enhance import (EnhanceConfig, analyze, choose_strength, wet_gain_for,
    chunk_plan, crossfade_stitch, restore_length, blend_dry_wet, resample, decode_float,
    write_wav, master_loudness, measure_loudness, validate_enhanced, MODEL_SR)
from auk_reliability.worker import ReliabilityWorker
from auk_reliability.qa import SemanticQAGate
from auk_reliability.core import EditorError, sha256_file
from auk_reliability.policy import plan_request
from auk_reliability.core import Limits

SR = 24000

def speech_like(n, sr=SR, words=((0.2, 0.8), (1.2, 2.2), (2.5, 3.4)), floor=0.004, seed=7):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for wi, (a, b) in enumerate(words):
        i0, i1 = int(a * sr), min(int(b * sr), n)
        if i1 <= i0: continue
        seg = t[:i1 - i0]
        f0 = (110.0 + 12.0 * (wi % 5)) + 25.0 * np.sin(2 * np.pi * 3.0 * seg)
        phase = 2 * np.pi * np.cumsum(f0) / sr
        v = sum(np.sin(phase * (h + 1)) / (h + 1) for h in range(6))
        env = np.ones(len(seg)); k = min(int(0.03 * sr), len(seg) // 2)
        if k: env[:k] = np.linspace(0, 1, k); env[-k:] = np.linspace(1, 0, k)
        y[i0:i1] = v * env * 0.45
    y += rng.normal(0, floor, n)
    return y

def wav_write(path, y, sr=SR, channels=1):
    y = np.asarray(y)
    if channels == 2 and y.ndim == 1: y = np.stack([y, y], axis=1)
    pcm = (np.clip(y, -1, 1) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(channels); f.setsampwidth(2); f.setframerate(sr)
        f.writeframes(pcm.tobytes())
    return Path(path)

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_noisy_scores_lower_snr_than_clean(self):
        n = 4 * SR
        noisy = wav_write(self.root / 'noisy.wav', speech_like(n, floor=0.09))
        clean = wav_write(self.root / 'clean.wav', speech_like(n, floor=0.0004))
        a_noisy, a_clean = analyze(noisy), analyze(clean)
        self.assertLess(a_noisy['est_snr_db'], a_clean['est_snr_db'])
        self.assertEqual(a_noisy['sample_rate'], SR)
        self.assertAlmostEqual(a_noisy['duration_seconds'], 4.0, places=2)
    def test_clipping_and_dc_detected(self):
        n = 2 * SR
        y = np.clip(speech_like(n) * 3.0, -0.99, 0.99) + 0.01
        m = analyze(wav_write(self.root / 'clip.wav', y))
        self.assertGreater(m['clipping_fraction'], 0.0005)
        self.assertGreater(m['dc_offset'], 0.005)
    def test_silence_ratio(self):
        m = analyze(wav_write(self.root / 'sil.wav', np.random.default_rng(1).normal(0, 0.0002, 5 * SR)))
        self.assertGreater(m['silence_ratio'], 0.95)
    def test_strength_boundaries(self):
        cfg = EnhanceConfig()
        base = {'silence_ratio': 0.2, 'est_snr_db': 30.0, 'clipping_fraction': 0.0}
        self.assertEqual(choose_strength(base, cfg)[0], 'bypass')
        self.assertEqual(choose_strength({**base, 'est_snr_db': 18.0}, cfg)[0], 'light')
        self.assertEqual(choose_strength({**base, 'est_snr_db': 8.0}, cfg)[0], 'full')
        self.assertEqual(choose_strength({**base, 'est_snr_db': 20.0, 'clipping_fraction': 0.01}, cfg)[0], 'full')
        self.assertEqual(choose_strength({**base, 'silence_ratio': 0.99}, cfg)[0], 'bypass')
        self.assertEqual(wet_gain_for('full', cfg), 0.85)

class DspTests(unittest.TestCase):
    def test_chunk_stitch_is_sample_exact(self):
        cfg = EnhanceConfig(max_chunk_seconds=1.0, overlap_seconds=0.25)
        sr = 8000; n = int(2.7 * sr)
        x = np.random.default_rng(3).normal(0, 0.3, n)
        spans = chunk_plan(n, sr, cfg)
        self.assertGreater(len(spans), 2)
        pieces = [x[a:b] for a, b in spans]
        out = crossfade_stitch(pieces, int(cfg.overlap_seconds * sr))
        self.assertEqual(len(out), n)
        np.testing.assert_allclose(out, x, atol=1e-9)
    def test_restore_length(self):
        y = np.ones(100)
        out, drift = restore_length(np.ones(90), 100, 0.5)
        self.assertEqual(len(out), 100); self.assertAlmostEqual(drift, 0.1)
        out, drift = restore_length(np.ones(110), 100, 0.5)
        self.assertEqual(len(out), 100)
    def test_blend_gains(self):
        dry = np.ones(10); wet = np.zeros(10)
        np.testing.assert_allclose(blend_dry_wet(dry, wet, 0.25), np.full(10, 0.75))
    def test_resample_length(self):
        x = np.random.default_rng(2).normal(0, .2, SR)
        y = resample(x, SR, 48000)
        self.assertEqual(len(y), 48000)
        np.testing.assert_allclose(resample(y, 48000, SR), x, atol=0.02)

class MasteringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.cfg = EnhanceConfig()
    def tearDown(self): self.temp.cleanup()
    def test_two_pass_master_hits_target(self):
        n = 5 * SR
        src = wav_write(self.root / 'in.wav', speech_like(n, floor=0.02) * 0.2)
        out = self.root / 'out.wav'
        r = master_loudness(src, out, self.cfg, out_sr=SR, out_channels=1, n_target=n)
        self.assertEqual(r['mode'], 'measured_gain')
        self.assertTrue(r['within_tolerance'], r)
        self.assertLessEqual(r['after']['true_peak_dbtp'], -0.9)
        info = analyze(out)
        self.assertAlmostEqual(info['duration_seconds'], 5.0, places=2)
        self.assertEqual(info['sample_rate'], SR)
    def test_short_input_uses_measured_gain(self):
        n = SR  # 1s: below the 3s two-pass floor
        src = wav_write(self.root / 'short.wav', speech_like(3 * SR, floor=0.02)[:n] * 0.1)
        out = self.root / 'out.wav'
        r = master_loudness(src, out, self.cfg, out_sr=SR, out_channels=1, n_target=n)
        self.assertEqual(r['mode'], 'measured_gain')
        self.assertTrue(r['within_tolerance'], r)
    def test_silence_stays_silence(self):
        n = 5 * SR
        src = wav_write(self.root / 'sil.wav', np.random.default_rng(4).normal(0, 0.0002, n))
        out = self.root / 'out.wav'
        r = master_loudness(src, out, self.cfg, out_sr=SR, out_channels=1, n_target=n)
        self.assertEqual(r['mode'], 'skipped_silence')
        info = analyze(out)
        self.assertLess(info['rms_dbfs'], -60)

class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.cfg = EnhanceConfig()
    def tearDown(self): self.temp.cleanup()
    def _meas(self, n=2 * SR, ch=1):
        return {'duration_seconds': n / SR, 'sample_rate': SR, 'channels': ch, 'samples': n}
    def test_dc_flagged(self):
        p = wav_write(self.root / 'dc.wav', speech_like(2 * SR) + 0.02)
        r = validate_enhanced(p, self._meas(), self.cfg)
        self.assertFalse(r['ok']); self.assertIn('dc_offset', str(r['problems']))
    def test_duration_drift_flagged(self):
        p = wav_write(self.root / 'short.wav', speech_like(2 * SR)[:SR])
        r = validate_enhanced(p, self._meas(), self.cfg)
        self.assertFalse(r['ok'])
    def test_channel_mismatch_flagged(self):
        p = wav_write(self.root / 'st.wav', speech_like(2 * SR), channels=2)
        r = validate_enhanced(p, self._meas(ch=1), self.cfg)
        self.assertFalse(r['ok'])
    def test_clean_passes(self):
        y = speech_like(2 * SR) * 0.3
        p = wav_write(self.root / 'ok.wav', y)
        r = validate_enhanced(p, self._meas(), self.cfg)
        self.assertTrue(r['ok'], r)

class EchoAdapter:
    def __init__(self): self.calls = []
    def run(self, profile, input_audio, plan):
        self.calls.append(dict(plan))
        raw = Path(input_audio).read_bytes()
        return {'audio': base64.b64encode(raw).decode()}, {'fixture': True, 'inference_seconds': 0.01}
    def stop(self): pass

class WorkerEnhancerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.adapter = EchoAdapter()
        self.gate = SemanticQAGate(lambda p: {'text': 'hello world'}, lambda a, b: 0.9)
        self.worker = ReliabilityWorker(self.adapter, self.root / 'runs', semantic_gate=self.gate,
            runtime_profile={'simulation': True})
        self.p = {'source_text': 'hello world', 'rights_confirmed': True, 'seed': 9}
    def tearDown(self): self.worker.close(); self.temp.cleanup()
    def test_full_path_echo_adapter(self):
        src = wav_write(self.root / 'noisy.wav', speech_like(3 * SR, floor=0.2) * 0.8)
        r = self.worker.edit_audio(src, 'voice_enhancer', 'enhance', self.p)
        self.assertTrue(r.technical_success, r.reason)
        self.assertTrue(r.automatic_qa_pass, r.reason)
        att = r.attempts[0]
        self.assertEqual(att['decision']['strength'], 'full')
        self.assertEqual(att['generative']['chunks'], 1)
        self.assertIn('loudness', att)
        # The tuned enhancer instruction and grid-best generation options reach the model.
        self.assertIn('remove noise and reverberation', self.adapter.calls[0]['instruction'])
        go = self.adapter.calls[0]['generation_options']
        self.assertEqual(go['num_inference_steps'], 16)
        self.assertEqual(go['guidance_scale'], 1.0)
        self.assertEqual(go['sway_sampling_coef'], -1.0)
        self.assertEqual(att['plan']['expected_transcript'], 'hello world')
        # Sample-exact duration and format.
        out = analyze(r.output_path)
        self.assertAlmostEqual(out['duration_seconds'], 3.0, places=2)
        self.assertEqual(out['channels'], 1)
        self.assertEqual(out['sample_rate'], SR)
    def test_bypass_skips_the_model(self):
        src = wav_write(self.root / 'clean.wav', speech_like(3 * SR, floor=0.0004) * 0.5)
        r = self.worker.edit_audio(src, 'voice_enhancer', 'enhance', self.p)
        self.assertTrue(r.automatic_qa_pass, r.reason)
        att = r.attempts[0]
        self.assertEqual(att['decision']['strength'], 'bypass')
        self.assertIn('skipped', att['generative'])
        self.assertEqual(len(self.adapter.calls), 0)
    def test_silence_never_calls_the_model(self):
        src = wav_write(self.root / 'sil.wav', np.random.default_rng(5).normal(0, 0.0002, 5 * SR))
        r = self.worker.edit_audio(src, 'voice_enhancer', 'enhance', self.p)
        att = r.attempts[0]
        self.assertEqual(att['decision']['strength'], 'bypass')
        self.assertEqual(len(self.adapter.calls), 0)
        self.assertEqual(att['loudness']['mode'], 'skipped_silence')
    def test_stereo_stays_stereo(self):
        n = 3 * SR
        left = speech_like(n, floor=0.09) * 0.8
        right = np.concatenate([np.zeros(int(0.012 * SR)), left[:n - int(0.012 * SR)]]) * 0.85
        src = wav_write(self.root / 'stereo.wav', np.stack([left, right], 1), channels=2)
        r = self.worker.edit_audio(src, 'voice_enhancer', 'enhance', self.p)
        self.assertTrue(r.technical_success, r.reason)
        att = r.attempts[0]
        self.assertEqual(att['channel_mode'], 'mid_side_stereo')
        out, osr, _ = decode_float(r.output_path)
        self.assertEqual(out.ndim, 2); self.assertEqual(out.shape[1], 2)
        self.assertEqual(osr, SR)
        # Side channel is untouched by the model: L-R shape is preserved up to the
        # file-wide loudness gain (mastering scales L and R together, hence side too).
        side_out = 0.5 * (out[:, 0] - out[:, 1])
        side_in = 0.5 * (left - right)
        a, b = side_out[:len(side_in)], side_in
        gain = float(np.dot(a, b) / (np.dot(b, b) + 1e-12))
        np.testing.assert_allclose(a, gain * b, atol=0.02)
        self.assertGreater(float(np.corrcoef(a, b)[0, 1]), 0.995)
    def test_chunking_on_long_input(self):
        n = 30 * SR  # 3 chunks at 12s + 0.5s overlap
        src = wav_write(self.root / 'long.wav', speech_like(n, words=[(i + 0.1, i + 0.8) for i in range(0, 30, 3)], floor=0.09) * 0.8)
        r = self.worker.edit_audio(src, 'voice_enhancer', 'enhance', self.p)
        self.assertTrue(r.technical_success, r.reason)
        self.assertEqual(r.attempts[0]['generative']['chunks'], 3)
        out = analyze(r.output_path)
        self.assertAlmostEqual(out['duration_seconds'], 30.0, places=2)
    def test_policy_accepts_sway_and_rejects_bad_values(self):
        limits = Limits()
        ok = plan_request('voice_enhancer', 'enhance',
            {**self.p, 'generation_options': {'num_inference_steps': 16, 'guidance_scale': 1.0, 'sway_sampling_coef': -1.0}},
            3.0, limits)
        self.assertEqual(ok['generation_options']['sway_sampling_coef'], -1.0)
        with self.assertRaises(EditorError):
            plan_request('voice_enhancer', 'enhance', {**self.p, 'generation_options': {'sway_sampling_coef': 9.0}}, 3.0, limits)
        with self.assertRaises(EditorError):
            plan_request('voice_enhancer', 'enhance', {**self.p, 'generation_options': {'invented': 1}}, 3.0, limits)

if __name__ == '__main__':
    unittest.main()
