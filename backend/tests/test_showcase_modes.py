"""Ten executable scenarios per operation (90 total), using simulated inference.

Real FFmpeg preparation, WAV validation, policy, QA routing and result logging
run here. Canned ASR and generated tone fixtures are not evidence of model quality.
"""
import json
from pathlib import Path
import tempfile
import unittest
import wave

from auk_reliability.qa import SemanticQAGate
from auk_reliability.worker import ReliabilityWorker
from test_backend import Adapter, wav


EMOTIONS = ['calm', 'happy', 'sad', 'angry', 'fearful', 'surprised',
            'disgusted', 'excited', 'calm', 'happy']
VOICES = ['warm and low', 'bright and airy', 'raspy', 'smooth and resonant',
          'soft and breathy', 'crisp and clear', 'deep and rounded',
          'light and youthful', 'rich and full', 'thin and nasal']
CUSTOM = ['confident', 'bored and monotone', 'gentle', 'energetic', 'hesitant',
          'reassuring', 'formal', 'conversational', 'dramatic', 'understated']
SPEEDS = [.5, .6, .75, .8, .9, 1.1, 1.25, 1.5, 1.75, 2.0]
REPLACEMENTS = [('better', 'stronger'), ('better', 'weaker'), ('team', 'side'),
                ('night', 'day'), ('the better', 'a stronger'),
                ('better team', 'stronger side'), ('on the night', 'in the game'),
                ('They were', 'We were'), ('They were', 'They are'),
                ('the better team', 'a much stronger side')]
INSERTS = [('really', 'were', 'after'), ('clearly', 'were', 'after'),
           ('much', 'better', 'before'), ('football', 'team', 'before'),
           ('last', 'night', 'before'), ('certainly', 'They', 'after'),
           ('indeed', 'team', 'after'), ('by far', 'the better', 'before'),
           ('without doubt', 'were', 'after'), ('overall', 'night', 'after')]
DELETES = ['They', 'were', 'the better', 'better', 'team', 'on the night',
           'on', 'the night', 'They were', 'the better team']


class ShowcaseOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = wav(self.root / 'source.wav', 5)
        self.adapter = Adapter()
        self.worker = ReliabilityWorker(self.adapter, self.root / 'requests',
                                        runtime_profile={'simulation': True}, max_attempts=1)

    def tearDown(self):
        self.worker.close()
        self.temp.cleanup()

    def scenario(self, mode, op, index):
        # Each index has different checked source content, also exercising content
        # QA with different expected transcripts rather than just different seeds.
        context = ['', ' according to everyone', ' in our opinion', ' despite the rain',
                   ' as we expected', ' by a wide margin', ' after all',
                   ' without a doubt', ' against their rivals', ' this season'][index]
        source = 'They were the better team on the night' + context
        p = {'source_text': source, 'rights_confirmed': True, 'seed': 42}
        expected = source
        if op == 'emotion':
            p['emotion'] = EMOTIONS[index]
        elif op == 'voice_characteristics':
            p['description'] = VOICES[index]
        elif op == 'speed':
            p['speed_factor'] = SPEEDS[index]
        elif op == 'custom':
            p.update(instruction=f'Sound {CUSTOM[index]}. Keep every word unchanged.',
                     semantic_contract={'preserve_transcript': True})
        elif op == 'nonverbal_remove':
            p.update(sound='humming', target_seconds=3 + index * .1)
        elif mode == 'transcript_editor':
            p.update(segment_scope='whole_clip', segment_text=source)
            if op == 'replace':
                old, new = REPLACEMENTS[index]
                p.update(original_text=old, replacement_text=new)
                expected = source.replace(old, new, 1)
            elif op == 'insert':
                text, anchor, position = INSERTS[index]
                p.update(text=text, anchor=anchor, position=position)
                replacement = text + ' ' + anchor if position == 'before' else anchor + ' ' + text
                expected = source.replace(anchor, replacement, 1)
            else:
                p['text'] = DELETES[index]
                expected = ' '.join(source.replace(p['text'], '', 1).split())
            p['edited_segment_text'] = expected
        self.worker.gate = SemanticQAGate(
            lambda path: source if Path(path).name == 'input.wav' else expected,
            # Changing voice characteristics must not require a matching identity.
            None if op == 'voice_characteristics' else lambda a, b: .95)
        result = self.worker.edit_audio(self.source, mode, op, p)
        self.assertTrue(result.technical_success, result.reason)
        self.assertTrue(result.automatic_qa_pass, result.reason)
        self.assertIsNone(result.semantic_success)
        self.assertEqual(result.outcome, 'qa_pass_review_pending')
        self.assertEqual(len(result.attempts), 1)
        plan = self.adapter.calls[0][1]
        self.assertEqual(plan['expected_transcript'], expected)
        self.assertEqual(plan['public_operation'], op)
        self.assertEqual(plan['identity_required'], op != 'voice_characteristics')
        self.assertTrue(plan['quality_review_required'])
        with wave.open(result.output_path) as output:
            self.assertEqual(output.getframerate(), 24000)
            self.assertEqual(output.getnframes(), round(plan['target_seconds'] * 24000))
        saved = json.loads((Path(result.request_dir) / 'result.json').read_text())
        self.assertEqual(saved['output_path'], result.output_path)
        self.assertIsNone(saved['semantic_success'])
        if mode == 'transcript_editor':
            self.assertNotEqual(expected, source)
            self.assertIn('skipped', result.attempts[0]['splice'])


def _scenario(mode, operation, index):
    def test(self):
        self.scenario(mode, operation, index)
    test.__doc__ = f'{mode}/{operation}, scenario {index + 1:02d}: real pipeline, simulated model.'
    return test


for _mode, _operations in {
    'voice_editor': ('emotion', 'voice_characteristics', 'whisper', 'speed', 'custom', 'nonverbal_remove'),
    'transcript_editor': ('replace', 'insert', 'delete'),
}.items():
    for _operation in _operations:
        for _index in range(10):
            setattr(ShowcaseOperationTests, f'test_{_mode}_{_operation}_{_index + 1:02d}',
                    _scenario(_mode, _operation, _index))
