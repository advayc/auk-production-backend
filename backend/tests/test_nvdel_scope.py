"""Regression: nonverbal_remove uses the NVDEL-01 scoped envelope; other ops keep default caps.

The NVDEL-01 probe (2026-10-18, L4) established the application envelope for
nonverbal_remove: 23.88s input -> 22.0s output, combined 45.88s, ASR identical,
speaker cosine 0.9660. scoped_limits() encodes that envelope. build_plan must
apply it, or a valid in-envelope request fails with invalid_argument (observed
2026-10-27 on a 19.59s AMI clip against the default 15.0s input cap).
"""
import unittest

from auk_reliability.core import Limits, EditorError
from auk_reliability.policy import plan_request

AMI_DURATION = 19.59  # ami-es2002a-d-225.62-245.21.wav (CC BY 4.0)
NVDEL_ROW = dict(mode='voice_editor', operation='nonverbal_remove', parameters={
    'source_text': 'affection from their family and yeah they have lots of personality.',
    'rights_confirmed': True,
    'seed': 42,
    'sound': 'laughs',
    'target_seconds': 18.44,
})


def plan(duration, row=None, mode=None, op=None, params=None):
    row = row or NVDEL_ROW
    return plan_request(mode or row['mode'], op or row['operation'],
                        params or dict(row['parameters']), duration, Limits())


class TestNvdelScopedLimits(unittest.TestCase):
    def test_real_ami_clip_is_in_scope(self):
        p = plan(AMI_DURATION)
        self.assertEqual(p['instruction'], 'Remove the laughs from the audio.')

    def test_input_above_scoped_cap_rejected(self):
        with self.assertRaises(EditorError) as ctx:
            plan(26.0)
        self.assertEqual(ctx.exception.code, 'invalid_argument')

    def test_target_above_scoped_cap_rejected(self):
        params = dict(NVDEL_ROW['parameters'], target_seconds=25.5)
        with self.assertRaises(EditorError) as ctx:
            plan(AMI_DURATION, params=params)
        self.assertEqual(ctx.exception.code, 'invalid_argument')

    def test_target_must_shorten(self):
        params = dict(NVDEL_ROW['parameters'], target_seconds=AMI_DURATION)
        with self.assertRaises(EditorError) as ctx:
            plan(AMI_DURATION, params=params)
        self.assertEqual(ctx.exception.code, 'duration_conflict')

    def test_other_operations_keep_default_input_cap(self):
        params = {'source_text': 'hello world test clip', 'rights_confirmed': True,
                  'seed': 42, 'emotion': 'calm'}
        with self.assertRaises(EditorError) as ctx:
            plan(AMI_DURATION, mode='voice_editor', op='emotion', params=params)
        self.assertEqual(ctx.exception.code, 'invalid_argument')


if __name__ == '__main__':
    unittest.main()
