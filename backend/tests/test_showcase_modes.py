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
from test_backend import Adapter, speech_hum_wav, wav


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


def scenario_parameters(mode, op, index):
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
    return source, p, expected


# v034: nonverbal_remove is served by the surgical DSP path (hum detection,
# free-hum excision, comb notch) whenever the gate exposes a transcriber - not
# by vendor regeneration. The old pure-tone fixture reads as 100% hum (the comb
# detector's noise floor is defeated by an empty spectrum) and is rejected as
# invalid_argument, so these scenarios use a speech-like carrier with a steady
# synthetic hum, matching the W4 fixture recipe (real speech + synthetic hum).
# Word spans are supplied through the stubbed transcriber's ASR dict shape.
NVDEL_WORDS = [(0.3, 0.9), (1.3, 2.0), (2.4, 3.1), (3.5, 4.2)]


class ShowcaseOperationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = wav(self.root / 'source.wav', 5)
        self.nvdel_source = speech_hum_wav(self.root / 'nvdel_source.wav', 5, NVDEL_WORDS)
        self.adapter = Adapter()
        self.worker = ReliabilityWorker(self.adapter, self.root / 'requests',
                                        runtime_profile={'simulation': True}, max_attempts=1)

    def tearDown(self):
        self.worker.close()
        self.temp.cleanup()

    def scenario(self, mode, op, index):
        source, p, expected = scenario_parameters(mode, op, index)
        nvdel = op == 'nonverbal_remove'

        def transcribe(path, _source=source, _expected=expected):
            if Path(path).name == 'input.wav':
                if nvdel:
                    # ASR dict shape: word timestamps let the surgical path
                    # protect speech and excise only the free hum between words.
                    return {'text': _source,
                            'words': [{'start': a, 'end': b} for a, b in NVDEL_WORDS]}
                return _source
            return _expected

        self.worker.gate = SemanticQAGate(
            transcribe,
            # Changing voice characteristics must not require a matching identity.
            None if op == 'voice_characteristics' else lambda a, b: .95)
        result = self.worker.edit_audio(
            self.nvdel_source if nvdel else self.source, mode, op, p)
        self.assertTrue(result.technical_success, result.reason)
        self.assertTrue(result.automatic_qa_pass, result.reason)
        self.assertIsNone(result.semantic_success)
        self.assertEqual(result.outcome, 'qa_pass_review_pending')
        self.assertEqual(len(result.attempts), 1)
        if nvdel:
            # Surgical path: no vendor call; the attempt carries the DSP record.
            self.assertEqual(len(self.adapter.calls), 0)
            plan = result.attempts[0]['plan']
            surgical = result.attempts[0]['surgical']
            self.assertEqual(result.attempts[0]['mechanism'],
                             'dsp_excise_comb_notch_no_resynthesis')
            self.assertTrue(surgical['hum_detected'])
            self.assertGreater(surgical['removed_free_seconds'], 0.0)
            self.assertLess(surgical['out_duration'], surgical['in_duration'])
        else:
            plan = self.adapter.calls[0][1]
        self.assertEqual(plan['expected_transcript'], expected)
        self.assertEqual(plan['public_operation'], op)
        self.assertEqual(plan['identity_required'], op != 'voice_characteristics')
        self.assertTrue(plan['quality_review_required'])
        with wave.open(result.output_path) as output:
            self.assertEqual(output.getframerate(), 24000)
            if nvdel:
                # Surgical output keeps the speech; its duration is the input
                # minus the excised free hum, not the requested target_seconds.
                self.assertEqual(output.getnframes(), round(surgical['out_duration'] * 24000))
            else:
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
