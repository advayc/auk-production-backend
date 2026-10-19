from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from auk_reliability.policy import OPERATIONS
from auk_reliability.showcase import prepare_showcase, run_showcase, select_cases


def audit_fixture():
    clips = {f'c{i}': {'id': f'c{i}', 'sha256': str(i), 'audio_path': f'/audio/{i}.wav',
                       'duration': 3, 'labels': {'voice_id': f'speaker-{i % 3}'}}
             for i in range(12)}
    requests = [{'id': f'{mode}-{op}-{i:02d}', 'mode': mode, 'operation': op,
                 'clip_id': f'c{i}', 'parameters': {'source_text': 'checked speech', 'seed': 42}}
                for mode in ('voice_editor', 'transcript_editor')
                for op in OPERATIONS[mode] for i in range(12)]
    return {'valid': True, 'errors': [], 'clips': clips, 'requests': requests,
            'data': {'schema_version': 1}, 'manifest_sha256': 'manifest-hash'}


class ShowcaseSelectionTests(unittest.TestCase):
    def setUp(self):
        self.audit = audit_fixture()

    def test_ninety_cases_ten_for_every_operation(self):
        cases = select_cases(self.audit)
        self.assertEqual(len(cases), 90)
        for mode in ('voice_editor', 'transcript_editor'):
            for op in OPERATIONS[mode]:
                group = [c for c in cases if (c['mode'], c['operation']) == (mode, op)]
                self.assertEqual(len(group), 10)
                self.assertEqual(len({c['clip_id'] for c in group}), 10)

    def test_prefers_different_speakers(self):
        cases = select_cases(self.audit, per_operation=3)
        self.assertEqual(len({self.audit['clips'][c['clip_id']]['labels']['voice_id']
                              for c in cases[:3]}), 3)

    def test_deterministic_even_if_manifest_reordered(self):
        expected = select_cases(self.audit)
        self.audit['requests'].reverse()
        self.assertEqual(select_cases(self.audit), expected)

    def test_seed_only_variants_do_not_fill_coverage(self):
        original = self.audit['requests'][0]
        self.audit['requests'] = [c for c in self.audit['requests']
                                  if c['operation'] != 'emotion']
        self.audit['requests'] += [{**original, 'id': f'seed-{i}',
                                   'parameters': {**original['parameters'], 'seed': i}}
                                  for i in range(10)]
        with self.assertRaisesRegex(ValueError, 'emotion.*found 1'):
            select_cases(self.audit)

    def test_duplicate_recording_under_different_ids_is_not_diversity(self):
        for clip in self.audit['clips'].values():
            clip['sha256'] = 'same-recording'
        with self.assertRaisesRegex(ValueError, 'found 1'):
            select_cases(self.audit)

    def test_missing_operation_names_the_gap(self):
        self.audit['requests'] = [c for c in self.audit['requests'] if c['operation'] != 'delete']
        with self.assertRaisesRegex(ValueError, 'transcript_editor/delete.*found 0'):
            select_cases(self.audit)

    def test_mode_scope_and_input_immutability(self):
        original = deepcopy(self.audit)
        cases = select_cases(self.audit, modes=('transcript_editor',))
        self.assertEqual(len(cases), 30)
        cases[0]['parameters']['seed'] = 1
        self.assertEqual(self.audit, original)

    def test_invalid_dataset_and_limits_fail(self):
        for count in (0, -1, True, 1.5, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select_cases(self.audit, per_operation=count)
        self.audit.update(valid=False, errors=['unverified transcript'])
        with self.assertRaisesRegex(ValueError, 'preflight'):
            select_cases(self.audit)

    def test_enhancer_is_out_of_scope(self):
        with self.assertRaisesRegex(ValueError, 'only'):
            select_cases(self.audit, modes=('voice_enhancer',))

    def test_freeze_absolutizes_sources_and_preserves_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'selected.json'
            with patch('auk_reliability.showcase.validate_dataset', return_value=self.audit):
                prepare_showcase('input.json', target)
            data = json.loads(target.read_text())
            self.assertEqual(len(data['requests']), 90)
            self.assertEqual(data['showcase']['source_manifest_sha256'], 'manifest-hash')
            self.assertFalse(data['showcase']['acceptance_benchmark'])
            self.assertTrue(all(Path(c['audio_path']).is_absolute() for c in data['clips']))
            with self.assertRaises(FileExistsError):
                prepare_showcase('input.json', target)


class ShowcaseExecutionTests(unittest.TestCase):
    def test_requires_one_attempt_real_runtime(self):
        for attempts, profile in [(3, {'simulation': False}), (1, {'simulation': True}), (1, {})]:
            with self.subTest(attempts=attempts, profile=profile), self.assertRaises(ValueError):
                run_showcase(SimpleNamespace(max_attempts=attempts, runtime_profile=profile),
                             'not-read.json', 'unused')

    def test_run_is_screening_only_and_restores_deadline_on_failure(self):
        audit = audit_fixture()
        worker = SimpleNamespace(max_attempts=1, runtime_profile={'simulation': False}, deadline=123)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'selected.json'
            cases = select_cases(audit)
            target.write_text(json.dumps({'requests': cases, 'showcase': {'per_operation': 10}}))
            audit['requests'] = cases
            def fail(*args, **kwargs):
                self.assertFalse(kwargs['acceptance'])
                self.assertTrue(kwargs['resume'])
                worker.deadline = 999
                raise RuntimeError('interrupted')
            with patch('auk_reliability.showcase.validate_dataset', return_value=audit), \
                 patch('auk_reliability.showcase.run_acceptance_suite', side_effect=fail), \
                 self.assertRaisesRegex(RuntimeError, 'interrupted'):
                run_showcase(worker, target, Path(tmp) / 'run', resume=True)
            self.assertEqual(worker.deadline, 123)
