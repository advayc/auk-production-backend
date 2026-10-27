import unittest, tempfile, csv, wave, math, array
from pathlib import Path
from auk_reliability.core import Limits, EditorError, _quote_words
from auk_reliability.policy import plan_request
from auk_reliability.segment import verify_alignment
from auk_reliability.workflow import make_whole_clip_csv, make_clip_template, CLIP_FIELDS

BASE={'source_text':'They were the better team on the night.','rights_confirmed':True,'seed':42,
 'segment_start_seconds':0,'segment_end_seconds':3.0,'segment_text':'They were the better team on the night.',
 'original_text':'better','replacement_text':'stronger','edited_segment_text':'They were the stronger team on the night.'}
class V025(unittest.TestCase):
 def test_take_home_prompt_style(self):
  self.assertEqual(_quote_words('but accepting'),"'but accepting'");self.assertEqual(_quote_words("don't"),'"don\'t"')
  plan=plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True},3.0,Limits())
  self.assertEqual(plan['instruction'],"Replace 'better' with 'stronger'.")
  self.assertEqual(plan['expected_transcript'],'They were the stronger team on the night.')
 def test_insert_and_delete_use_supported_replace_prompt(self):
  B={**BASE,'alignment_verified':True}
  ins=plan_request('transcript_editor','insert',{**B,'text':'really','anchor':'better','position':'before','edited_segment_text':'They were the really better team on the night.'},3.0,Limits())
  self.assertEqual(ins['instruction'],"Replace 'better' with 'really better'.")
  self.assertEqual(ins['expected_transcript'],'They were the really better team on the night.')
  dele=plan_request('transcript_editor','delete',{**B,'text':'better','edited_segment_text':'They were the team on the night.'},3.0,Limits())
  self.assertEqual(dele['instruction'],"Replace 'better team' with 'team'.")
  last=plan_request('transcript_editor','delete',{**B,'text':'night.','edited_segment_text':'They were the better team on the'},3.0,Limits())
  self.assertEqual(last['instruction'],"Replace 'the night.' with 'the'.")
  old=plan_request('transcript_editor','insert',{**B,'text':'really','anchor':'better','position':'before','instruction_style':'regenerate','edited_segment_text':'They were the really better team on the night.'},3.0,Limits())
  self.assertTrue(old['instruction'].startswith('Regenerate this speech as:'))
  with self.assertRaises(EditorError):plan_request('transcript_editor','insert',{**B,'text':'really','anchor':'better','position':'before','edited_segment_text':'They were the better team on the night.'},3.0,Limits())
 def test_regenerate_style_still_available(self):
  plan=plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True,'instruction_style':'regenerate'},3.0,Limits())
  self.assertTrue(plan['instruction'].startswith('Regenerate this speech as:'))
 def test_whole_clip_alignment_requires_exact_checked_text(self):
  seen=[]
  ok={**BASE,'segment_scope':'whole_clip'}
  verify_alignment('x.wav',ok,lambda p:'they were the better team on the night')
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_text':'They were the better team.'},lambda p:'they were the better team')
  with self.assertRaises(EditorError):verify_alignment('x.wav',ok,lambda p:'they were the best team on the night')  # ASR mismatch still fails
 def test_segment_asr_variants_position_scoped(self):
  ok={**BASE,'segment_scope':'whole_clip'}
  asr_says='they were the better squad on the night'  # ASR misspelling class: 'team' heard as 'squad'
  good=[{'position':4,'expected':'team','observed':'squad'}]
  verify_alignment('x.wav',{**ok,'segment_asr_variants':good},lambda p:asr_says)  # documented slot passes
  # strict default: same ASR mismatch without declared variant still fails
  with self.assertRaises(EditorError):verify_alignment('x.wav',ok,lambda p:asr_says)
  # wrong documented position rejected
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':[{'position':3,'expected':'team','observed':'squad'}]},lambda p:asr_says)
  # variant slot mismatch vs actual ASR rejected
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':good},lambda p:'they were the better club on the night')
  # other word changes rejected even with a valid variant declared
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':good},lambda p:'they were the better squad on that night')
  # insertion rejected (length mismatch)
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':good},lambda p:'they were the better squad team on the night')
  # deletion rejected (length mismatch)
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':good},lambda p:'they were the squad on the night')
  # expected==observed variant is a no-op alias and rejected
  with self.assertRaises(EditorError):verify_alignment('x.wav',{**ok,'segment_asr_variants':[{'position':4,'expected':'team','observed':'team'}]},lambda p:asr_says)
 def test_output_asr_variants_position_scoped(self):
  from auk_reliability.qa import SemanticQAGate
  plan={'expected_transcript':'They were the better team on the night','identity_required':False}
  asr_says='they were the better squad on the night'  # ASR misspelling class: 'team' heard as 'squad'
  good=[{'position':4,'expected':'team','observed':'squad','note':'doc'}]
  gate=SemanticQAGate(lambda p:asr_says)
  passed=gate.check('s','o',{**plan,'output_asr_variants':good})
  self.assertTrue(passed['automatic_pass'])
  self.assertEqual(passed['checks']['transcript']['applied_asr_variants'][0]['position'],4)
  self.assertEqual(passed['checks']['transcript']['expected'],plan['expected_transcript'])  # expected text immutable
  self.assertEqual(passed['checks']['transcript']['observed'],asr_says)  # raw decode kept for diagnostics
  # strict default: same ASR mismatch without declared variant still fails
  self.assertFalse(gate.check('s','o',plan)['automatic_pass'])
  # wrong documented position rejected
  self.assertFalse(gate.check('s','o',{**plan,'output_asr_variants':[{'position':3,'expected':'team','observed':'squad'}]})['automatic_pass'])
  # variant slot mismatch vs actual ASR rejected
  self.assertFalse(gate.check('s','o',{**plan,'output_asr_variants':[{'position':4,'expected':'team','observed':'club'}]})['automatic_pass'])
  # other word changes rejected even with a valid variant declared
  self.assertFalse(SemanticQAGate(lambda p:'they were the better squad on that night').check('s','o',{**plan,'output_asr_variants':good})['automatic_pass'])
  # insertion rejected (length mismatch)
  self.assertFalse(SemanticQAGate(lambda p:'they were the better squad team on the night').check('s','o',{**plan,'output_asr_variants':good})['automatic_pass'])
  # deletion rejected (length mismatch)
  self.assertFalse(SemanticQAGate(lambda p:'they were the squad on the night').check('s','o',{**plan,'output_asr_variants':good})['automatic_pass'])
  # expected==observed variant is a no-op alias and rejected
  self.assertFalse(gate.check('s','o',{**plan,'output_asr_variants':[{'position':4,'expected':'team','observed':'team'}]})['automatic_pass'])
 def test_output_asr_variants_plan_validation(self):
  ok={**BASE,'alignment_verified':True,'output_asr_variants':[{'position':4,'expected':'team','observed':'squad'}]}
  plan=plan_request('transcript_editor','replace',ok,3.0,Limits())
  self.assertEqual(plan['output_asr_variants'][0]['observed'],'squad')
  self.assertNotIn('output_asr_variants',plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True},3.0,Limits()))
  for bad in ('notalist',[{'position':'4','expected':'team','observed':'squad'}],[{'position':4,'expected':'team'}],[{'position':4,'expected':'team','observed':'team'}],['squad']):
   with self.assertRaises(EditorError):plan_request('transcript_editor','replace',{**BASE,'alignment_verified':True,'output_asr_variants':bad},3.0,Limits())
 def test_generation_options_validation_and_payload(self):
  from auk_reliability.core import LocalAuKServer
  B2={'source_text':'They were the better team on the night.','rights_confirmed':True,'seed':42}
  good={'num_inference_steps':64,'guidance_scale':3.0}
  plan=plan_request('voice_editor','emotion',{**B2,'emotion':'excited','generation_options':good},3.0,Limits())
  self.assertEqual(plan['generation_options'],good)
  self.assertNotIn('generation_options',plan_request('voice_editor','emotion',{**B2,'emotion':'excited'},3.0,Limits()))
  for bad in ('x',{'num_inference_steps':0},{'num_inference_steps':129},{'num_inference_steps':4.5},{'guidance_scale':-1},{'guidance_scale':21},{'guidance_scale':True},{'temperature':0.5}):
   with self.assertRaises(EditorError):plan_request('voice_editor','emotion',{**B2,'emotion':'excited','generation_options':bad},3.0,Limits())
  ad=LocalAuKServer.__new__(LocalAuKServer);ad.model_id="m"
  payload=ad._request_payload('in.wav',{'instruction':'i','seed':42,'target_seconds':3.0,'generation_options':good})
  self.assertEqual(payload['request']['options'],{'duration_sec':3.0,'num_inference_steps':64,'guidance_scale':3.0})
  payload=ad._request_payload('in.wav',{'instruction':'i','seed':42,'target_seconds':3.0})
  self.assertEqual(payload['request']['options'],{'duration_sec':3.0})  # strict default unchanged
 def test_no_scope_still_needs_human_alignment(self):
  with self.assertRaises(EditorError):verify_alignment('x.wav',dict(BASE),lambda p:BASE['segment_text'])
 def test_whole_clip_csv_is_separate_copy_and_reports_problems(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);p=d/'a.wav'
   with wave.open(str(p),'wb') as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(array.array('h',[int(3000*math.sin(i*.05)) for i in range(48000)]).tobytes())
   f=d/'clips.csv';make_clip_template(d,f);r=list(csv.DictReader(f.open()))[0]
   r.update(transcript='hello world again world',transcript_verified='true',replace_old='again',delete_text='world')
   with f.open('w',newline='') as o:
    w=csv.DictWriter(o,fieldnames=CLIP_FIELDS);w.writeheader();w.writerow(r)
   before=f.read_text();out=d/'clips_whole.csv'
   report=make_whole_clip_csv(f,out);self.assertEqual(f.read_text(),before)
   self.assertEqual(report['whole_clip_rows'],0);self.assertIn('delete_text not unique in whole transcript',report['rows_left_unchanged'][0]['reasons'])
   with self.assertRaises(FileExistsError):make_whole_clip_csv(f,out)
   r['delete_text']='hello';f.write_text('');
   with f.open('w',newline='') as o:
    w=csv.DictWriter(o,fieldnames=CLIP_FIELDS);w.writeheader();w.writerow(r)
   out2=d/'clips_whole2.csv';report=make_whole_clip_csv(f,out2);self.assertEqual(report['whole_clip_rows'],1)
   row=list(csv.DictReader(out2.open()))[0]
   self.assertEqual((row['segment_scope'],row['alignment_verified'],row['segment_start_seconds']),('whole_clip','false','0'));self.assertAlmostEqual(float(row['segment_end_seconds']),2.0,1)
if __name__=='__main__':unittest.main()
