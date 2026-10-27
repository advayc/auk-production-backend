"""Regression: nonverbal_remove scope is caller-applied; plan_request defaults stay conservative.

Owner architecture (backend/auk_reliability/worker.py, v033): the worker invokes
scoped_limits(self.limits, operation) per request - evidence-bounded 25/25/50 envelope
for nonverbal_remove (NVDEL-01 probe 2026-10-18, L4: 23.88s -> 22.0s, ASR identical,
speaker cosine 0.9660) - while every other operation keeps default caps, and plain
plan_request with default Limits keeps rejecting over-default input. The 2026-10-27
megacell failure (19.59s AMI, invalid_argument) came from a RUNNER calling plan_request
with plain Limits(), bypassing the worker's scoped preparation - the fix belongs at the
call site, not in build_plan's default contract.
"""
import unittest

from auk_reliability.core import Limits, EditorError, scoped_limits
from auk_reliability.policy import plan_request

AMI_DURATION = 19.59  # ami-es2002a-d-225.62-245.21.wav (CC BY 4.0)
NVDEL_ROW = dict(mode='voice_editor', operation='nonverbal_remove', parameters={
    'source_text': 'affection from their family and yeah they have lots of personality.',
    'rights_confirmed': True,
    'seed': 42,
    'sound': 'laughs',
    'target_seconds': 18.44,
})


def plan(duration, row=None, limits=None):
    row = row or NVDEL_ROW
    return plan_request(row['mode'], row['operation'], dict(row['parameters']),
                        duration, limits or Limits())


class TestNvdelScopedLimits(unittest.TestCase):
    def test_default_limits_reject_ami_sized_input(self):
        # Conservative public default (15s input cap) is intact for plain callers.
        with self.assertRaises(EditorError) as ctx:
            plan(AMI_DURATION)
        self.assertEqual(ctx.exception.code, 'invalid_argument')

    def test_explicit_scope_accepts_real_ami_row(self):
        # The worker pattern: caller applies the evidence-bounded envelope.
        p = plan(AMI_DURATION, limits=scoped_limits(Limits(), 'nonverbal_remove'))
        self.assertEqual(p['operation'], 'nonverbal_remove')
        self.assertEqual(p['target_seconds'], 18.44)

    def test_scope_still_rejects_beyond_envelope(self):
        # 26s input exceeds the 25s evidence bound even with scope applied.
        with self.assertRaises(EditorError) as ctx:
            plan(26.0, limits=scoped_limits(Limits(), 'nonverbal_remove'))
        self.assertEqual(ctx.exception.code, 'invalid_argument')

    def test_scope_is_nvdel_only(self):
        # scoped_limits leaves every other operation at default caps:
        # a 19.59s emotion request still hits the 15s input cap.
        row = dict(NVDEL_ROW, operation='emotion', parameters={
            'source_text': NVDEL_ROW['parameters']['source_text'],
            'rights_confirmed': True, 'seed': 42, 'emotion': 'calm',
            'target_seconds': 18.44})
        with self.assertRaises(EditorError) as ctx:
            plan(19.59, row=row, limits=scoped_limits(Limits(), 'emotion'))
        self.assertEqual(ctx.exception.code, 'invalid_argument')

    def test_duration_conflict_still_fails_closed_under_scope(self):
        # target >= duration is a contract error independent of caps.
        row = dict(NVDEL_ROW, parameters=dict(NVDEL_ROW['parameters'], target_seconds=19.59))
        with self.assertRaises(EditorError) as ctx:
            plan(19.59, row=row, limits=scoped_limits(Limits(), 'nonverbal_remove'))
        self.assertEqual(ctx.exception.code, 'duration_conflict')


if __name__ == '__main__':
    unittest.main()
