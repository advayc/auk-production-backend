import unittest
from auk_reliability.core import EditorError, Limits
from auk_reliability.policy import plan_request, OPERATIONS

SRC = 'We tested the setup before launch and it worked.'

def params(**kw):
    p = {'rights_confirmed': True, 'source_text': SRC, 'sound': 'humming', 'target_seconds': 11.0}
    p.update(kw)
    return p

class NonverbalRemovePlanTests(unittest.TestCase):
    def test_registered_operation(self):
        self.assertIn('nonverbal_remove', OPERATIONS['voice_editor'])

    def test_plan_shape_vendor_prompt(self):
        plan = plan_request('voice_editor', 'nonverbal_remove', params(), 12.0, Limits())
        self.assertEqual(plan['operation'], 'nonverbal_remove')
        # Vendor cookbook 4.4 prompt shape, byte-identical to the NVDEL-01 probe request.
        self.assertEqual(plan['instruction'], 'Remove the humming from the audio.')
        self.assertEqual(plan['target_seconds'], 11.0)
        self.assertEqual(plan['expected_transcript'], SRC)
        self.assertTrue(plan['preserve_content'])
        self.assertTrue(plan['identity_required'])

    def test_target_rounded_to_grid(self):
        plan = plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=11.013), 12.0, Limits())
        self.assertEqual(plan['target_seconds'], 11.02)

    def test_missing_sound_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'nonverbal_remove', params(sound='  '), 12.0, Limits())
        self.assertEqual(ctx.exception.code, 'missing_sound')

    def test_missing_target_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=None), 12.0, Limits())
        self.assertEqual(ctx.exception.code, 'missing_target')

    def test_target_must_shorten(self):
        for t in (12.0, 12.5):
            with self.assertRaises(EditorError) as ctx:
                plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=t), 12.0, Limits())
            self.assertEqual(ctx.exception.code, 'duration_conflict')

    def test_expected_text_conflict_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'nonverbal_remove', params(expected_text='different words entirely'), 12.0, Limits())
        self.assertEqual(ctx.exception.code, 'transcript_conflict')

    def test_nvdel01_sized_input_plans_via_wired_scope(self):
        # Owner decision landed 2026-10-27: build_plan wires scoped_limits internally,
        # so the NVDEL-01 shape (23.88s input, 25/25/50 envelope) plans via the plain
        # path. The pre-wiring contract test (default 15s cap blocks it) is superseded;
        # over-envelope rejection stays covered in test_nvdel_scope.py (26s input).
        plan = plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=22.0), 23.88, Limits())
        self.assertEqual(plan['operation'], 'nonverbal_remove')
        self.assertEqual(plan['target_seconds'], 22.0)
        with self.assertRaises(EditorError):
            plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=24.0), 26.0, Limits())

    def test_target_bounds_guard(self):
        # target below the minimum audio length fails closed at require_finite.
        with self.assertRaises(EditorError):
            plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=0.4), 12.0, Limits())


if __name__ == '__main__':
    unittest.main()

# ---- scoped caps + end-to-end normal path (v033, evidence-bounded) ----
import test_backend
from auk_reliability.core import scoped_limits

class NonverbalRemoveScopeTests(unittest.TestCase):
    def test_scoped_limits_helper(self):
        base = Limits()
        scoped = scoped_limits(base, 'nonverbal_remove')
        self.assertEqual((scoped.max_input_seconds, scoped.max_output_seconds, scoped.combined_seconds), (25.0, 25.0, 50.0))
        self.assertEqual(scoped_limits(base, 'speed'), base)  # every other op untouched

    def test_fixture_sized_plan_builds_under_scope(self):
        # The actual NVDEL-01 request shape (23.88s -> 22.0s) plans under the scoped caps.
        plan = plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=22.0), 23.88,
                            scoped_limits(Limits(), 'nonverbal_remove'))
        self.assertEqual(plan['target_seconds'], 22.0)
        self.assertEqual(plan['instruction'], 'Remove the humming from the audio.')

    def test_boundary_exact_25s_input_accepted_under_scope(self):
        # The scoped cap is 25.0s inclusive: a request at exactly the app-tested
        # bound plans normally (25.5s is rejected above).
        plan = plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=24.0), 25.0,
                            scoped_limits(Limits(), 'nonverbal_remove'))
        self.assertEqual(plan['target_seconds'], 24.0)

    def test_beyond_probe_envelope_fails_closed(self):
        # 25.5s input exceeds the evidence-bounded scope (probe verified 23.88s only).
        with self.assertRaises(EditorError):
            plan_request('voice_editor', 'nonverbal_remove', params(target_seconds=24.0), 25.5,
                         scoped_limits(Limits(), 'nonverbal_remove'))
        # NOTE: the scoped combined cap (50s) is unreachable given target < duration <= 25;
        # it stays as defense in depth, not as a binding constraint.

class NonverbalRemoveE2ETests(test_backend.BackendTests):
    def test_nvdel01_sized_request_passes_normal_path(self):
        # 23.88s input (NVDEL-01 fixture size) end to end: scoped preparation, plan,
        # generation, output validation and QA. The fixture adapter honors target_seconds.
        src = test_backend.wav(self.root/'nvdel.wav', 23.88)
        r = self.worker.edit_audio(src, 'voice_editor', 'nonverbal_remove',
            {'rights_confirmed': True, 'source_text': 'hello world', 'seed': 42,
             'sound': 'humming', 'target_seconds': 22.0})
        self.assertTrue(r.technical_success)
        self.assertTrue(r.automatic_qa_pass)
        plan = self.adapter.calls[0][1]
        self.assertEqual(plan['instruction'], 'Remove the humming from the audio.')
        self.assertEqual(plan['target_seconds'], 22.0)
        self.assertEqual(plan['expected_transcript'], 'hello world')

    def test_other_ops_keep_default_caps(self):
        # The same 23.88s input is still rejected for every non-NVDEL operation.
        src = test_backend.wav(self.root/'long.wav', 23.88)
        with self.assertRaises(EditorError):
            self.worker.edit_audio(src, 'voice_editor', 'speed', {**self.p, 'speed_factor': 1.5})
