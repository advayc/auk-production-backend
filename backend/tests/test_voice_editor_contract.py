import unittest
from auk_reliability.core import Limits, EditorError
from auk_reliability.policy import plan_request

# Contract tests for the first workflow (AI Voice Editor). The original brief
# requires every operation to have explicit prompt, duration, validation and
# retry rules; these tests lock the SHIPPED rules exactly as they stand.
# Test-only addition: no backend behavior changes.

BASE = {'rights_confirmed': True,
        'source_text': 'They were the better team on the night.'}
SRC = BASE['source_text']

def plan(op, extra=None, duration=3.0):
    p = dict(BASE)
    if extra: p.update(extra)
    return plan_request('voice_editor', op, p, duration, Limits())

class VoiceEditorContractTests(unittest.TestCase):
    def test_whisper_prompt_duration_and_preservation(self):
        pl = plan('whisper')
        self.assertEqual(pl['instruction'], 'Speak in a soft whisper, retaining the words and speaker identity.')
        self.assertEqual(pl['target_seconds'], 3.0)  # duration-preserving
        self.assertTrue(pl['preserve_content'])
        self.assertEqual(pl['expected_transcript'], SRC)
    def test_whisper_rejects_conflicting_target(self):
        with self.assertRaises(EditorError) as ctx:
            plan('whisper', {'target_seconds': 2.0})
        self.assertEqual(ctx.exception.code, 'duration_conflict')
    def test_whisper_rejects_foreign_expected_text(self):
        with self.assertRaises(EditorError) as ctx:
            plan('whisper', {'expected_text': 'different words'})
        self.assertEqual(ctx.exception.code, 'transcript_conflict')
    def test_emotion_prompt_and_validation(self):
        pl = plan('emotion', {'emotion': 'happy'})
        self.assertEqual(pl['instruction'], 'Change the emotion to happy. Retain the words and speaker identity.')
        self.assertEqual(pl['target_seconds'], 3.0)
        self.assertEqual(pl['expected_transcript'], SRC)
        with self.assertRaises(EditorError) as ctx:
            plan('emotion', {'emotion': 'meh'})
        self.assertEqual(ctx.exception.code, 'invalid_emotion')
    def test_voice_characteristics_description_rules(self):
        pl = plan('voice_characteristics', {'description': 'a warm low voice'})
        self.assertEqual(pl['instruction'], 'Keep the words unchanged. Change the voice character to "a warm low voice".')
        self.assertEqual(pl['expected_transcript'], SRC)
        with self.assertRaises(EditorError) as ctx:
            plan('voice_characteristics', {'description': '  '})
        self.assertEqual(ctx.exception.code, 'missing_description')
        self.assertFalse(pl['identity_required'])  # speaker check off: the voice is meant to change
    def test_speed_target_derivation_and_conflict(self):
        pl = plan('speed', {'speed_factor': 1.5})
        self.assertEqual(pl['instruction'], 'Adjust the speech speed to 1.5x.')
        self.assertEqual(pl['target_seconds'], 2.0)  # duration / speed
        self.assertTrue(pl['preserve_content'])
        self.assertEqual(pl['expected_transcript'], SRC)
        with self.assertRaises(EditorError) as ctx:
            plan('speed', {'speed_factor': 1.5, 'target_seconds': 1.9})
        self.assertEqual(ctx.exception.code, 'duration_conflict')
        with self.assertRaises(EditorError):
            plan('speed', {'speed_factor': 3.0})  # outside 0.5-2.0
    def test_custom_instruction_rules(self):
        contract = {'semantic_contract': {'preserve_transcript': True}}
        pl = plan('custom', {'instruction': 'Make it sound like a phone call', 'target_seconds': 2.5, **contract})
        self.assertEqual(pl['instruction'], 'Make it sound like a phone call')
        self.assertEqual(pl['target_seconds'], 2.5)  # custom may change duration
        self.assertEqual(pl['expected_transcript'], SRC)  # forced to source
        self.assertTrue(pl['quality_review_required'])
        with self.assertRaises(EditorError) as ctx:
            plan('custom', {'instruction': ' ', **contract})
        self.assertEqual(ctx.exception.code, 'missing_instruction')
    def test_custom_requires_preserve_transcript_contract(self):
        with self.assertRaises(EditorError) as ctx:
            plan('custom', {'instruction': 'Make it sound like a phone call'})
        self.assertEqual(ctx.exception.code, 'unsupported_contract')
    def test_nonverbal_remove_rules(self):
        pl = plan('nonverbal_remove', {'sound': 'humming', 'target_seconds': 2.0})
        self.assertEqual(pl['instruction'], 'Remove the humming from the audio.')
        self.assertEqual(pl['target_seconds'], 2.0)
        self.assertEqual(pl['expected_transcript'], SRC)  # words preserved
        with self.assertRaises(EditorError) as ctx:
            plan('nonverbal_remove', {'target_seconds': 2.0})
        self.assertEqual(ctx.exception.code, 'missing_sound')
        with self.assertRaises(EditorError) as ctx:
            plan('nonverbal_remove', {'sound': 'humming'})
        self.assertEqual(ctx.exception.code, 'missing_target')
        with self.assertRaises(EditorError) as ctx:
            plan('nonverbal_remove', {'sound': 'humming', 'target_seconds': 3.0})
        self.assertEqual(ctx.exception.code, 'duration_conflict')  # must shorten
    def test_common_gate_rules(self):
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'whisper', {'source_text': SRC}, 3.0, Limits())
        self.assertEqual(ctx.exception.code, 'rights_not_confirmed')
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'whisper', {'rights_confirmed': True, 'source_text': ' '}, 3.0, Limits())
        self.assertEqual(ctx.exception.code, 'missing_transcript')
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'time_travel', BASE, 3.0, Limits())
        self.assertEqual(ctx.exception.code, 'unsupported_operation')
    def test_duration_budget_and_grid(self):
        # target rounds UP to the 0.02s grid
        pl = plan('whisper', duration=3.013)
        self.assertEqual(pl['target_seconds'], 3.02)
        # input + output must fit the combined application budget
        with self.assertRaises(EditorError) as ctx:
            plan_request('voice_editor', 'custom',
                         {**BASE, 'instruction': 'stretch it', 'target_seconds': 15.5,
                          'semantic_contract': {'preserve_transcript': True}}, 15.0, Limits())
        self.assertEqual(ctx.exception.code, 'duration_budget')

if __name__ == '__main__':
    unittest.main()
