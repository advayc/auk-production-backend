import unittest
from auk_reliability.core import Limits, EditorError
from auk_reliability.policy import plan_request

# Oct 16 insert smoke: vctk-p326_028, 7 words in 3.22 s; inserting 'really' must not stay at 3.22 s.
SMOKE={'source_text':'It is believed he had been stabbed.','rights_confirmed':True,'seed':42,
 'segment_start_seconds':0,'segment_end_seconds':None,'segment_scope':'whole_clip',
 'segment_text':'It is believed he had been stabbed.',
 'text':'really','anchor':'believed','position':'before',
 'edited_segment_text':'It is really believed he had been stabbed.'}
BASE={'source_text':'They were the better team on the night.','rights_confirmed':True,'seed':42,
 'segment_start_seconds':0,'segment_end_seconds':3.0,'segment_text':'They were the better team on the night.',
 'original_text':'better','replacement_text':'stronger','edited_segment_text':'They were the stronger team on the night.'}
class V027(unittest.TestCase):
 def test_insert_scales_target_duration_by_word_ratio(self):
  plan=plan_request('transcript_editor','insert',SMOKE,3.22,Limits())
  self.assertEqual(plan['target_seconds'],3.68)  # 3.22 * 8/7, on the 0.02 grid
  self.assertEqual(plan['instruction'],"Replace 'believed' with 'really believed'.")
 def test_equal_word_replace_keeps_source_duration(self):
  plan=plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True},3.0,Limits())
  self.assertEqual(plan['target_seconds'],3.0)
 def test_delete_shrinks_target_duration(self):
  plan=plan_request('transcript_editor','delete',{**BASE,'segment_scope':'whole_clip','text':'better','edited_segment_text':'They were the team on the night.'},3.0,Limits())
  self.assertEqual(plan['target_seconds'],2.64)  # 3.0 * 7/8 = 2.625, ceiled to the 0.02 grid
 def test_word_growth_replace_scales(self):
  plan=plan_request('transcript_editor','replace',{**BASE,'segment_scope':'whole_clip','replacement_text':'much stronger',
   'edited_segment_text':'They were the much stronger team on the night.'},3.0,Limits())
  self.assertEqual(plan['target_seconds'],3.38)  # 3.0 * 9/8 = 3.375, ceiled to the 0.02 grid
 def test_scaling_ratio_is_clamped(self):
  many=' '.join(['word']*30)
  plan=plan_request('transcript_editor','insert',{**SMOKE,'text':many,
   'edited_segment_text':'It is '+many+' believed he had been stabbed.'},3.22,Limits())
  self.assertEqual(plan['target_seconds'],6.44)
 def test_localized_scope_keeps_interval_duration(self):
  plan=plan_request('transcript_editor','delete',{**BASE,'text':'better','edited_segment_text':'They were the team on the night.'},3.0,Limits())
  self.assertEqual(plan['target_seconds'],3.0)
 def test_regenerate_style_also_scales(self):
  plan=plan_request('transcript_editor','insert',{**SMOKE,'instruction_style':'regenerate'},3.22,Limits())
  self.assertEqual(plan['target_seconds'],3.68)
  self.assertTrue(plan['instruction'].startswith('Regenerate this speech as:'))
if __name__=='__main__': unittest.main()
class ArmBExplicitInsert(unittest.TestCase):
 def test_default_style_unchanged(self):
  plan=plan_request('transcript_editor','insert',SMOKE,3.22,Limits())
  self.assertEqual(plan['instruction'],"Replace 'believed' with 'really believed'.")
  self.assertEqual(plan['operation'],'replace_words')
 def test_explicit_insert_names_insertion_point(self):
  plan=plan_request('transcript_editor','insert',{**SMOKE,'instruction_style':'explicit_insert'},3.22,Limits())
  self.assertEqual(plan['instruction'],
   "Insert 'really' immediately before 'believed'. Keep every other word, the word order, and the speaker voice unchanged.")
  self.assertEqual(plan['operation'],'custom')
  self.assertEqual(plan['public_operation'],'insert')
  self.assertEqual(plan['expected_transcript'],'It is really believed he had been stabbed.')
  self.assertEqual(plan['target_seconds'],3.68)  # same v0.2.7 word-ratio scaling as the default arm
  self.assertTrue(plan['identity_required'])
  self.assertTrue(plan['quality_review_required'])
 def test_explicit_insert_after_position(self):
  plan=plan_request('transcript_editor','insert',{**SMOKE,'instruction_style':'explicit_insert','position':'after',
   'edited_segment_text':'It is believed really he had been stabbed.'},3.22,Limits())
  self.assertIn("immediately after 'believed'",plan['instruction'])
 def test_explicit_insert_rejects_delete(self):
  with self.assertRaises(EditorError) as ctx:
   plan_request('transcript_editor','delete',{**BASE,'segment_scope':'whole_clip','text':'better',
    'edited_segment_text':'They were the team on the night.','instruction_style':'explicit_insert'},3.0,Limits())
  self.assertEqual(ctx.exception.code,'unsupported_instruction_style')
 def test_explicit_insert_rejects_replace(self):
  with self.assertRaises(EditorError) as ctx:
   plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True,'instruction_style':'explicit_insert'},3.0,Limits())
  self.assertEqual(ctx.exception.code,'unsupported_instruction_style')
 def test_explicit_insert_still_enforces_transcript_conflict(self):
  with self.assertRaises(EditorError) as ctx:
   plan_request('transcript_editor','insert',{**SMOKE,'instruction_style':'explicit_insert',
    'edited_segment_text':'It is extremely believed he had been stabbed.'},3.22,Limits())
  self.assertEqual(ctx.exception.code,'transcript_conflict')
