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
