import unittest
from auk_reliability.core import Limits, EditorError
from auk_reliability.policy import plan_request

# v0.2.9: replacement spanning the entire segment diverts to the vendor zero-shot TTS template
# (bounded-validated 27 Oct 2026, run w2v6-20261027T150204Z: 12/12 exact transcripts, WER 0.0;
# speaker identity still fails the 0.75 gate - 0.567-0.728 - so review_required/no-output stands).
BASE={'source_text':'The visitors are, however, in strong form.','rights_confirmed':True,'seed':42,
 'segment_start_seconds':0,'segment_end_seconds':3.94,'segment_text':'The visitors are, however, in strong form.',
 'original_text':'The visitors are, however, in strong form.','replacement_text':'The visitors are, however, in excellent form.',
 'edited_segment_text':'The visitors are, however, in excellent form.','alignment_verified':True}
class FullSegmentReplace(unittest.TestCase):
 def test_full_segment_diverts_to_tts_template(self):
  plan=plan_request('transcript_editor','replace',dict(BASE),3.94,Limits())
  self.assertEqual(plan['operation'],'custom')
  self.assertEqual(plan['instruction'],"Say the following with the same voice: 'The visitors are, however, in excellent form.'")
  self.assertEqual(plan['expected_transcript'],'The visitors are, however, in excellent form.')
 def test_full_segment_detection_normalizes_punctuation(self):
  # old/replacement without the final period still span the segment (normalized comparison);
  # the derived edit reconstructs the period, so this is a valid request shape.
  p={**BASE,'original_text':'The visitors are, however, in strong form',
     'replacement_text':'The visitors are, however, in excellent form'}
  plan=plan_request('transcript_editor','replace',p,3.94,Limits())
  self.assertEqual(plan['operation'],'custom')
  self.assertTrue(plan['instruction'].startswith('Say the following with the same voice: '))
 def test_partial_span_keeps_replace_phrasing(self):
  p={**BASE,'original_text':'strong','replacement_text':'excellent'}
  plan=plan_request('transcript_editor','replace',p,3.94,Limits())
  self.assertEqual(plan['operation'],'replace_words')
  self.assertEqual(plan['instruction'],"Replace 'strong' with 'excellent'.")
 def test_identical_full_segment_replacement_rejected(self):
  # Replacement differing from the old text only in punctuation/case is a no-op: reject it.
  p={**BASE,'replacement_text':'the visitors are however in strong form',
     'edited_segment_text':'the visitors are however in strong form'}
  with self.assertRaises(EditorError) as ctx:
   plan_request('transcript_editor','replace',p,3.94,Limits())
  self.assertEqual(ctx.exception.code,'invalid_replacement')
 def test_regenerate_style_unaffected_by_full_segment_scope(self):
  plan=plan_request('transcript_editor','replace',{**BASE,'instruction_style':'regenerate'},3.94,Limits())
  self.assertEqual(plan['operation'],'custom')
  self.assertTrue(plan['instruction'].startswith('Regenerate this speech as:'))
if __name__=='__main__': unittest.main()
