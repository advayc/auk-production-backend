"""Enhancer acceptance-scope flag (v0.5.1).

The acceptance suite can measure voice_enhancer through the same gated worker
path when AUK_ACCEPTANCE_VOICE_ENHANCER is set, without touching the delivery
contract (policy.ACTIVE_MODES). These tests pin both sides of that contract:
flag off = byte-identical legacy scope; flag on = enhancer cases run end to
end in the suite and the report says so honestly.
"""
import json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

from auk_reliability.policy import (ACTIVE_MODES, ENHANCER_ACCEPTANCE_ENV,
    acceptance_scope_modes, enhancer_acceptance_opt_in, selected_modes)
from auk_reliability.core import sha256_file
from auk_reliability.acceptance import configure_acceptance_suite, run_acceptance_suite
import test_backend


def enhancer_manifest(root, source):
    """One voice_editor case + one voice_enhancer case over the same fixture clip."""
    labels = {k: 'fixture' for k in ['voice_id', 'accent', 'microphone', 'noise',
        'reverb', 'speaking_speed', 'duration_bucket', 'language']}
    labels['format'] = 'wav'
    clip = {'id': 'one', 'audio_path': str(source), 'sha256': sha256_file(source),
        'rights_verified': True, 'license': 'synthetic unittest only',
        'provenance': 'test sine fixture', 'transcript_verified': True,
        'transcript': 'hello world', 'split': 'development', 'labels': labels}
    p = {'source_text': 'hello world', 'rights_confirmed': True, 'seed': 9}
    d = {'schema_version': 1, 'clips': [clip], 'requests': [
        {'id': 've', 'clip_id': 'one', 'mode': 'voice_editor', 'operation': 'emotion', 'parameters': dict(p)},
        {'id': 'enh', 'clip_id': 'one', 'mode': 'voice_enhancer', 'operation': 'denoise', 'parameters': dict(p)}]}
    path = root / 'manifest.json'
    path.write_text(json.dumps(d))
    return path


class FlagTests(unittest.TestCase):
    def test_flag_parsing(self):
        for true_value in ['1', 'true', 'TRUE', 'yes', 'on', ' 1 ']:
            self.assertTrue(enhancer_acceptance_opt_in({ENHANCER_ACCEPTANCE_ENV: true_value}))
        for false_value in ['', '0', 'false', 'no', 'off', 'enabled-ish']:
            self.assertFalse(enhancer_acceptance_opt_in({ENHANCER_ACCEPTANCE_ENV: false_value}))
        self.assertFalse(enhancer_acceptance_opt_in({}))

    def test_flag_off_scope_is_the_legacy_contract(self):
        self.assertEqual(acceptance_scope_modes(env={}), ACTIVE_MODES)
        self.assertEqual(acceptance_scope_modes(env={ENHANCER_ACCEPTANCE_ENV: '0'}), ACTIVE_MODES)

    def test_flag_on_extends_scope_without_touching_the_contract(self):
        env = {ENHANCER_ACCEPTANCE_ENV: '1'}
        self.assertEqual(acceptance_scope_modes(env=env), tuple(ACTIVE_MODES) + ('voice_enhancer',))
        # The delivery contract and its default resolver are byte-identical either way.
        self.assertEqual(ACTIVE_MODES, ('voice_editor', 'transcript_editor'))
        self.assertEqual(selected_modes(), ACTIVE_MODES)

    def test_explicit_modes_always_win(self):
        env = {ENHANCER_ACCEPTANCE_ENV: '1'}
        self.assertEqual(acceptance_scope_modes(['voice_editor'], env=env), ('voice_editor',))
        with self.assertRaises(ValueError):
            acceptance_scope_modes([], env=env)


class SuiteScopeTests(test_backend.BackendTests):
    def setUp(self):
        super().setUp()
        self.manifest = enhancer_manifest(self.root, self.source)

    def test_flag_off_excludes_enhancer_end_to_end(self):
        env = {k: v for k, v in os.environ.items() if k != ENHANCER_ACCEPTANCE_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            configure_acceptance_suite(self.worker, self.manifest, self.root / 'suite')
            r = run_acceptance_suite(acceptance=False)
        self.assertEqual(r['scope_modes'], list(ACTIVE_MODES))
        self.assertEqual(r['excluded_request_count'], 1)
        self.assertEqual(list(r['by_operation']), ['voice_editor/emotion'])
        self.assertFalse(r['enhancer_acceptance_opt_in'])
        report = (self.root / 'suite/REPORT.md').read_text()
        self.assertIn('Voice Enhancer: out of scope', report)

    def test_flag_on_measures_enhancer_end_to_end(self):
        with mock.patch.dict(os.environ, {ENHANCER_ACCEPTANCE_ENV: '1'}):
            configure_acceptance_suite(self.worker, self.manifest, self.root / 'suite')
            r = run_acceptance_suite(acceptance=False)
        # Both contract modes and the enhancer ran through the suite.
        self.assertEqual(r['scope_modes'], ['voice_editor', 'transcript_editor', 'voice_enhancer'])
        self.assertEqual(r['excluded_request_count'], 0)
        self.assertTrue(r['enhancer_acceptance_opt_in'])
        enh = r['by_operation']['voice_enhancer/denoise']
        self.assertEqual(enh['request_count'], 1)
        self.assertEqual(enh['technical_success_rate'], 1.0)
        self.assertEqual(enh['automatic_qa_pass_rate'], 1.0)
        self.assertEqual(r['by_operation']['voice_editor/emotion']['request_count'], 1)
        # The enhancer case really went through the adaptive pipeline, not a stub:
        # the fixture adapter saw the generative chunk call(s) or a measured bypass
        # decision, and the attempt record carries the measured analysis.
        rows = [json.loads(line) for line in (self.root / 'suite/requests.jsonl').read_text().splitlines()]
        enh_row = [row for row in rows if row['case_id'] == 'enh'][0]
        attempt = enh_row['attempts'][0]
        self.assertIn(attempt['decision']['strength'], ('bypass', 'light', 'full'))
        self.assertIn('mechanism', attempt)
        self.assertEqual(attempt['mechanism'], 'adaptive_analysis_generative_chunks_blend_master')
        if attempt['decision']['strength'] != 'bypass':
            self.assertTrue(any(c[1].get('instruction') for c in self.adapter.calls))
        # The report is honest about the flag: in scope for measurement, contract unchanged.
        report = (self.root / 'suite/REPORT.md').read_text()
        self.assertIn('acceptance opt-in flag', report)
        self.assertNotIn('out of scope, owned by another engineer', report)
        # Simulation still can never count as acceptance evidence.
        self.assertEqual(r['status'], 'SIMULATED_TEST_ONLY')
        self.assertFalse(r['acceptance_pass'])

    def test_flag_on_but_explicit_modes_exclude_enhancer(self):
        with mock.patch.dict(os.environ, {ENHANCER_ACCEPTANCE_ENV: '1'}):
            r = run_acceptance_suite(self.worker, self.manifest, self.root / 'suite2',
                acceptance=False, modes=['voice_editor'])
        self.assertEqual(r['scope_modes'], ['voice_editor'])
        self.assertEqual(list(r['by_operation']), ['voice_editor/emotion'])


if __name__ == '__main__':
    unittest.main()

# Only the new flag regressions; the shared backend fixtures run in their own modules.
for _name in dir(test_backend.BackendTests):
    if _name.startswith('test_') and _name not in SuiteScopeTests.__dict__:
        setattr(SuiteScopeTests, _name, None)
