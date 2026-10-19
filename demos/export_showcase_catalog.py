"""Export the exact 90 code-test scenarios for presentation; no audio generation."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'backend/tests')]
from auk_reliability.core import Limits, scoped_limits
from auk_reliability.policy import ACTIVE_MODES, OPERATIONS, plan_request
from test_showcase_modes import scenario_parameters


def catalog():
    cases = []
    for mode in ACTIVE_MODES:
        for operation in OPERATIONS[mode]:
            for index in range(10):
                source, parameters, expected = scenario_parameters(mode, operation, index)
                plan = plan_request(mode, operation, parameters, 5.0,
                                    scoped_limits(Limits(), operation))
                test_name = f'test_{mode}_{operation}_{index + 1:02d}'
                cases.append({'id': f'{mode}/{operation}/{index + 1:02d}',
                              'test': f'test_showcase_modes.ShowcaseOperationTests.{test_name}',
                              'mode': mode, 'operation': operation,
                              'source_text': source, 'input_seconds': 5.0,
                              'parameters': parameters, 'expected_text': expected,
                              'target_seconds': plan['target_seconds'],
                              'instruction': plan['instruction'],
                              'human_review_required': True})
    return {'kind': 'automated_test_recipes', 'simulation': True, 'case_count': len(cases),
            'audio_generation_status': 'pending',
            'note': 'Tone fixtures and canned ASR/speaker scores exercise code contracts. '
                    'These transcripts describe test fixtures, not verified human recordings. '
                    'This is not a reviewed audio-generation manifest.',
            'cases': cases}


def markdown(data):
    lines = ['# All ten cases per operation', '',
             '90 executable tests: 60 voice-editor cases and 30 transcript-editor cases. '
             'Each table below lists all ten cases for that operation.', '',
             '**These are code tests using simulated inference.** Real audio generation '
             'and human listening remain pending. The tests run real FFmpeg/WAV preparation, '
             'duration checks, QA routing, and artifact logging.', '',
             '[Exact requests and expected results (JSON)](showcase_test_cases.json) · '
             '[Test source](../backend/tests/test_showcase_modes.py) · '
             '[Audio batch instructions](SHOWCASE.md)', '',
             '## Run the presentation tests', '', 'From the repository root:', '',
             '```sh', 'PYTHONPATH=backend:backend/tests python -m unittest test_showcase_modes -v',
             '```', '', 'Run just the ten speed cases:', '', '```sh',
             'PYTHONPATH=backend:backend/tests python -m unittest discover -s backend/tests -p test_showcase_modes.py -k voice_editor_speed -v',
             '```', '', 'Run one specific case:', '', '```sh',
             'PYTHONPATH=backend:backend/tests python -m unittest test_showcase_modes.ShowcaseOperationTests.test_voice_editor_speed_01 -v',
             '```', '', 'Every case verifies a single attempt, a valid 24 kHz WAV with the planned '
             'frame count, the exact expected transcript, correct identity-QA routing, saved '
             'result metadata, and a pending human-review status. Transcript cases also verify '
             'the text changed and that whole-clip scope is recorded.', '']
    groups = defaultdict(list)
    for case in data['cases']:
        groups[(case['mode'], case['operation'])].append(case)
    for (mode, operation), cases in groups.items():
        lines += [f'## {mode} / {operation}', '',
                  '| Case | Requested edit | Input text | Expected text | Output duration |',
                  '|---|---|---|---|---:|']
        for case in cases:
            p = case['parameters']
            edit = {
                'emotion': lambda: p['emotion'],
                'voice_characteristics': lambda: p['description'],
                'whisper': lambda: 'Soft whisper; preserve words and identity',
                'speed': lambda: f"{p['speed_factor']:g}x speed",
                'custom': lambda: p['instruction'],
                'nonverbal_remove': lambda: 'Remove humming; shorten duration',
                'replace': lambda: f"Replace '{p['original_text']}' with '{p['replacement_text']}'",
                'insert': lambda: f"Insert '{p['text']}' {p['position']} '{p['anchor']}'",
                'delete': lambda: f"Delete '{p['text']}'",
            }[operation]()
            cells = [case['id'].rsplit('/', 1)[1], edit, case['source_text'],
                     case['expected_text'], f"{case['target_seconds']:g} s"]
            lines.append('| ' + ' | '.join(c.replace('|', '\\|') for c in cells) + ' |')
        lines.append('')
    lines += ['## Keep the index in sync', '',
              'The exporter reads the same scenario builder that the executable tests use.', '',
              '```sh', 'python demos/export_showcase_catalog.py',
              'python demos/export_showcase_catalog.py --check', '```', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if committed catalog files are stale')
    args = parser.parse_args()
    data = catalog()
    outputs = {'showcase_test_cases.json': json.dumps(data, indent=2, allow_nan=False) + '\n',
               'TEST_CASES.md': markdown(data)}
    for name, content in outputs.items():
        path = ROOT / 'demos' / name
        if args.check:
            if not path.is_file() or path.read_text() != content:
                raise SystemExit(f'Stale catalog: run python demos/export_showcase_catalog.py ({name})')
        else:
            path.write_text(content)
    print(f"{'Verified' if args.check else 'Exported'} {len(data['cases'])} cases; 10 per operation")


if __name__ == '__main__':
    main()
