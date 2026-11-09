import json, time, unittest
from pathlib import Path
from auk_reliability.acceptance import recommend_profiles, run_acceptance_suite
from auk_reliability.dataset import validate_dataset
from auk_reliability.core import sha256_file
import test_scope


class AcceptanceBoundaryTests(test_scope.ScopeTests):
    # Boundary coverage for the acceptance gates and dataset validator that the
    # existing suites name but do not assert directly. Every case here is a
    # rejection path: nothing below may ever present as acceptance evidence.

    def test_incomplete_run_fails_technical_gate(self):
        # A stopped-early suite records completed rows only and must report every
        # gate false - a partial run can never present as acceptance evidence.
        self.worker.set_deadline(0.001); time.sleep(0.01)
        r = run_acceptance_suite(self.worker, self.manifest(), self.root/'acc-inc', acceptance=False)
        self.assertEqual(r['stopped_early'], 'wall_clock_budget')
        self.assertFalse(r['complete'])
        self.assertFalse(r['technical_acceptance_pass'])
        self.assertFalse(r['acceptance_pass'])
        self.assertNotEqual(r['status'], 'MEASURED_ACCEPTANCE_PASS')

    def test_unreviewed_semantics_are_not_success(self):
        # Fixture worker leaves semantic_success=None (no human review). The
        # suite must count those as unreviewed, never as semantic success.
        r = run_acceptance_suite(self.worker, self.manifest(), self.root/'acc-unrev', acceptance=False)
        self.assertEqual(r['overall']['semantic_unreviewed_count'], 1)
        self.assertEqual(r['overall']['semantic_success_rate'], 0)
        self.assertFalse(r['acceptance_pass'])
        self.assertNotEqual(r['status'], 'MEASURED_ACCEPTANCE_PASS')

    @staticmethod
    def _rows(profile, n, qa=True, sem=True, tech=True, lat=1.0):
        return [{'mode': 'voice_editor', 'operation': 'emotion', 'profile': profile,
                 'technical_success': tech, 'automatic_qa_pass': qa, 'semantic_success': sem,
                 'latency_seconds': lat, 'reason': None, 'attempts': [], 'case_id': 'x',
                 'request_dir': None}] * n

    def _recommend(self, rows):
        return recommend_profiles({'rows': rows, 'environment': {'simulation': False},
                                   'scope_modes': ['voice_editor']})['voice_editor/emotion']

    def test_recommend_profiles_denominator_floors_and_p95_choice(self):
        # Below the per-op/profile request denominator: never qualified.
        r = self._recommend(self._rows('base_f32', 999))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')
        # QA floor breach at full denominator: never qualified.
        r = self._recommend(self._rows('base_f32', 980) + self._rows('base_f32', 20, qa=False))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')
        # Unreviewed semantics at full denominator: never qualified.
        r = self._recommend(self._rows('base_f32', 1000, sem=None))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')
        # Two qualified profiles: the fastest measured P95 wins.
        r = self._recommend(self._rows('base_q8', 1000, lat=2.0) + self._rows('flash_f16', 1000, lat=1.0))
        self.assertEqual(r['recommended_profile'], 'flash_f16'); self.assertEqual(r['status'], 'measured')

    def _valid_manifest(self):
        labels = {k: 'fixture' for k in ['voice_id', 'accent', 'microphone', 'noise', 'reverb',
                                         'speaking_speed', 'duration_bucket', 'language']}
        labels['format'] = 'wav'
        return {'schema_version': 1,
                'clips': [{'id': 'one', 'audio_path': str(self.source),
                           'sha256': sha256_file(self.source),
                           'rights_verified': True, 'license': 'synthetic unittest only',
                           'provenance': 'test sine fixture', 'transcript_verified': True,
                           'transcript': 'hello world', 'split': 'development', 'labels': labels}],
                'requests': [{'id': 'req-1', 'clip_id': 'one', 'mode': 'voice_editor',
                              'operation': 'emotion', 'parameters': dict(self.p)}]}

    def _validate(self, data, acceptance=False):
        path = self.root/'manifest-boundary.json'; path.write_text(json.dumps(data))
        return validate_dataset(path, acceptance=acceptance)

    def test_recommend_profiles_exact_threshold_boundaries(self):
        # Floors are inclusive at exactly .99 and reject one request below it
        # (acceptance.py recommend_profiles: technical/qa/semantic floors, min_requests).
        # QA rate exactly .99 (990/1000) qualifies; .989 does not.
        r = self._recommend(self._rows('base_f32', 990) + self._rows('base_f32', 10, qa=False))
        self.assertEqual(r['recommended_profile'], 'base_f32')
        r = self._recommend(self._rows('base_f32', 989) + self._rows('base_f32', 11, qa=False))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')
        # Technical-success rate exactly .99 qualifies; .989 does not.
        r = self._recommend(self._rows('base_f32', 990) + self._rows('base_f32', 10, tech=False))
        self.assertEqual(r['recommended_profile'], 'base_f32')
        r = self._recommend(self._rows('base_f32', 989) + self._rows('base_f32', 11, tech=False))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')
        # Reviewed-semantic rate exactly .99 qualifies; .989 does not.
        r = self._recommend(self._rows('base_f32', 990) + self._rows('base_f32', 10, sem=False))
        self.assertEqual(r['recommended_profile'], 'base_f32')
        r = self._recommend(self._rows('base_f32', 989) + self._rows('base_f32', 11, sem=False))
        self.assertIsNone(r['recommended_profile']); self.assertEqual(r['status'], 'not_qualified')

    def test_validator_rejects_missing_or_inaccurate_attestations(self):
        cases = {
            # Attestation says one thing, bytes say another (corrupted artifact).
            'sha mismatch': lambda d: d['clips'][0].update(sha256='0' * 64),
            # Missing attestations: flags that must be affirmed are false.
            'transcript verification not affirmed': lambda d: d['clips'][0].update(transcript_verified=False),
            'rights verification not affirmed': lambda d: d['clips'][0].update(rights_verified=False),
            # A dimension label that attests "not audited" is not a label.
            'unreviewed dimension label': lambda d: d['clips'][0]['labels'].update(noise='unreviewed'),
            # Format label must match the actual container.
            'format label mismatch': lambda d: d['clips'][0]['labels'].update(format='flac'),
            # Request text must match the verified clip transcript.
            'source_text mismatch': lambda d: d['requests'][0]['parameters'].update(source_text='different words'),
        }
        for name, corrupt in cases.items():
            with self.subTest(case=name):
                d = self._valid_manifest(); corrupt(d)
                a = self._validate(d)
                self.assertFalse(a['valid'], name)
                self.assertTrue(a['errors'], name)

    def test_validator_detects_corrupted_audio_bytes(self):
        # Manifest attestation stays constant; the audio bytes change after hashing.
        d = self._valid_manifest()
        with self.source.open('ab') as f: f.write(b'\x00\x01')
        a = self._validate(d)
        self.assertFalse(a['valid'])
        self.assertIn('SHA-256', str(a['errors']))

    def test_acceptance_split_enforced(self):
        # A development-split clip cannot serve an acceptance run.
        a = self._validate(self._valid_manifest(), acceptance=True)
        self.assertFalse(a['valid'])
        self.assertIn('held_out', str(a['errors']))


if __name__ == '__main__':
    unittest.main()
