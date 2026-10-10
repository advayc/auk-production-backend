import json, time, unittest
from pathlib import Path
from auk_reliability.core import WallClockAbort, EditorError
from auk_reliability.acceptance import benchmark_profiles, run_acceptance_suite
import test_backend, test_scope

class WallClockTests(test_scope.ScopeTests):
 def test_budget_stop_before_any_request_and_resume_completes(self):
  # Expire the deadline before the run: every request aborts pre-attempt, nothing is recorded.
  self.worker.set_deadline(0.001);time.sleep(0.01)
  r=benchmark_profiles(self.worker,self.manifest(),self.root/'bench',per_operation_limit=1)
  self.assertEqual(r['stopped_early'],'wall_clock_budget');self.assertEqual(r['rows'],[]);self.assertFalse(r['complete'])
  saved=json.loads((self.root/'bench/benchmark.json').read_text());self.assertEqual(saved['rows'],[])
  # Resume with a fresh (unset) deadline completes the full signature without reruns.
  self.worker.set_deadline(None)
  r2=benchmark_profiles(self.worker,self.manifest(),self.root/'bench',per_operation_limit=1,resume=True)
  self.assertTrue(r2['complete']);self.assertEqual(len(r2['rows']),3);self.assertIsNone(r2['stopped_early'])
 def test_budget_stop_mid_run_records_completed_only(self):
  # Let the first (case, profile) complete, then expire the deadline during the next call.
  calls={'n':0};original=self.adapter.run
  def run_then_expire(profile,audio,plan):
   result=original(profile,audio,plan);calls['n']+=1
   if calls['n']==1:self.worker.deadline=time.monotonic()-1
   return result
  self.adapter.run=run_then_expire
  self.worker.set_deadline(3600)
  r=benchmark_profiles(self.worker,self.manifest(),self.root/'bench2',per_operation_limit=1)
  self.assertEqual(r['stopped_early'],'wall_clock_budget');self.assertEqual(len(r['rows']),1)
  lines=(self.root/'bench2/benchmark_progress.jsonl').read_text().splitlines();self.assertEqual(len(lines),1)
  # Resume finishes the remaining two profiles only.
  self.adapter.run=original;self.worker.set_deadline(None)
  r2=benchmark_profiles(self.worker,self.manifest(),self.root/'bench2',per_operation_limit=1,resume=True)
  self.assertTrue(r2['complete']);self.assertEqual(len(r2['rows']),3)
  self.assertEqual(len(self.adapter.calls),3)
 def test_inflight_kill_persists_attempt_then_aborts(self):
  original=self.adapter.run
  def run_timeout(profile,audio,plan):
   self.worker.deadline=time.monotonic()-1
   raise EditorError('inference_timeout','fixture timeout')
  self.adapter.run=run_timeout;self.worker.set_deadline(3600)
  with self.assertRaises(WallClockAbort):
   self.worker.edit_audio(str(self.source),'voice_editor','emotion',dict(self.p))
  folders=[f for f in (self.root/'runs').iterdir() if f.is_dir()]
  self.assertEqual(len(folders),1)
  attempts=json.loads((folders[0]/'attempts.json').read_text())
  self.assertEqual(len(attempts),1);self.assertEqual(attempts[0]['failure_reason'],'inference_timeout')
  self.adapter.run=original
 def test_deadline_validation(self):
  for bad in (0,-5,float('inf'),float('nan'),'3600'):
   with self.assertRaises(ValueError):self.worker.set_deadline(bad)
  self.worker.set_deadline(None);self.assertIsNone(self.worker.deadline)
 def test_acceptance_budget_stop(self):
  self.worker.set_deadline(0.001);time.sleep(0.01)
  r=run_acceptance_suite(self.worker,self.manifest(),self.root/'acc',acceptance=False)
  self.assertEqual(r['stopped_early'],'wall_clock_budget');self.assertFalse(r['complete'])
  self.assertEqual(r['overall']['request_count'],0)
  self.worker.set_deadline(None)
  r2=run_acceptance_suite(self.worker,self.manifest(),self.root/'acc',acceptance=False,resume=True)
  self.assertTrue(r2['complete']);self.assertEqual(r2['overall']['request_count'],1)

if __name__=='__main__':unittest.main()
