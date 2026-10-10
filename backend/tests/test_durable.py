import unittest,tempfile,json
from pathlib import Path
from auk_reliability.durable import Checkpoint,balanced_cases,prepare_run,assert_split_disjoint,add_artifact_hashes
from auk_reliability.core import atomic_json
class DurableTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_sync_restore_and_tamper(self):
  local=self.root/'local';local.mkdir();(local/'audio.wav').write_bytes(b'valid-test-bytes')
  cp=Checkpoint(self.root/'backup',{'dataset':local});self.assertEqual(cp.sync()['verified_files'],1)
  (local/'audio.wav').unlink();cp.restore();self.assertTrue((local/'audio.wav').exists())
  (self.root/'backup/dataset/audio.wav').write_bytes(b'tampered')
  with self.assertRaises(ValueError):cp.restore()
 def test_partial_restore_ignores_other_labels_and_leaves_backup_untouched(self):
  a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir();(a/'f').write_text('data');(b/'g').write_text('backend-old')
  Checkpoint(self.root/'backup',{'dataset':a,'backend':b}).sync()
  before=sorted((p.name,p.read_bytes()) for p in (self.root/'backup').rglob('*') if p.is_file())
  a2=self.root/'a2';b2=self.root/'b2';a2.mkdir();b2.mkdir();(b2/'g').write_text('backend-NEW')
  cp=Checkpoint(self.root/'backup',{'dataset':a2,'backend':b2})
  with self.assertRaises(FileExistsError):cp.restore()
  self.assertEqual(cp.restore(only=('dataset',))['restored_files'],1)
  self.assertEqual((a2/'f').read_text(),'data');self.assertEqual((b2/'g').read_text(),'backend-NEW')
  self.assertEqual(before,sorted((p.name,p.read_bytes()) for p in (self.root/'backup').rglob('*') if p.is_file()))
  with self.assertRaises(ValueError):cp.restore(only=('nope',))
 def test_restore_conflict(self):
  local=self.root/'local';local.mkdir();(local/'x').write_text('old');cp=Checkpoint(self.root/'backup',{'state':local});cp.sync();(local/'x').write_text('new')
  with self.assertRaises(FileExistsError):cp.restore()
 def test_skips_venv(self):
  local=self.root/'local';(local/'venv').mkdir(parents=True);(local/'venv/x').write_text('x');cp=Checkpoint(self.root/'backup',{'state':local});self.assertEqual(cp.sync()['verified_files'],0)
 def test_round_robin_and_variants(self):
  audit={'clips':{},'requests':[]}
  for sp in ('a','b','c'):
   for i in range(2):
    cid=sp+str(i);audit['clips'][cid]={'split':'development','labels':{'voice_id':sp}}
    for j in range(2):audit['requests'].append({'id':cid+str(j),'clip_id':cid,'mode':'voice_editor','operation':'emotion'})
  cases=balanced_cases(audit,6);self.assertEqual(len({c['clip_id'] for c in cases}),6);self.assertEqual([c['clip_id'][0] for c in cases],list('abcabc'))
 def test_benchmark_rejects_held_out(self):
  a={'clips':{'x':{'split':'held_out','labels':{'voice_id':'a'}}},'requests':[{'clip_id':'x','mode':'voice_editor','operation':'speed'}]}
  with self.assertRaises(ValueError):balanced_cases(a,1)
 def test_resume_identity_and_partial_tail(self):
  run=self.root/'run';prepare_run(run,'sig',False,'rows.jsonl');(run/'rows.jsonl').write_text('{"case_id":"one"}\n{"partial":')
  rows=prepare_run(run,'sig',True,'rows.jsonl');self.assertEqual(len(rows),1)
  with self.assertRaises(ValueError):prepare_run(run,'changed',True,'rows.jsonl')
  with self.assertRaises(FileExistsError):prepare_run(run,'sig',False,'rows.jsonl')
 def test_resume_hash_check(self):
  artifact=self.root/'out.wav';artifact.write_bytes(b'a');run=self.root/'run';prepare_run(run,'sig',False,'rows.jsonl')
  row=add_artifact_hashes({'case_id':'one','output_path':str(artifact),'attempts':[]});(run/'rows.jsonl').write_text(json.dumps(row)+'\n');artifact.write_bytes(b'b')
  with self.assertRaises(ValueError):prepare_run(run,'sig',True,'rows.jsonl')
 def test_disjoint(self):
  a=self.root/'a';b=self.root/'b'
  atomic_json(a,{'clips':[{'sha256':'a','labels':{'voice_id':'a'}}]});atomic_json(b,{'clips':[{'sha256':'b','labels':{'voice_id':'a'}}]})
  with self.assertRaises(ValueError):assert_split_disjoint(a,b)
 def test_resume_benchmark_skips_completed(self):
  from unittest.mock import patch
  from auk_reliability.acceptance import benchmark_profiles
  from auk_reliability.worker import Result
  class Worker:
   runtime_profile={'simulation':True};max_attempts=1
   def __init__(self):self.calls=0
   def edit_audio(self,*args):
    self.calls+=1
    return Result(str(self.calls),'failed',False,False,None,None,'test',args[-1]['profile'],.1,[],str(self.root))
  worker=Worker();worker.root=self.root/'requests';worker.root.mkdir()
  audit={'valid':True,'errors':[],'manifest_sha256':'x','scope_modes':['voice_editor'],'excluded_request_count':0,
   'clips':{'a':{'audio_path':'test','split':'development','labels':{'voice_id':'a'}}},
   'requests':[{'id':'one','clip_id':'a','mode':'voice_editor','operation':'emotion','parameters':{}}]}
  with patch('auk_reliability.acceptance.validate_dataset',return_value=audit):
   out=self.root/'bench';benchmark_profiles(worker,'unused',out,per_operation_limit=1,modes=['voice_editor'])
   self.assertEqual(worker.calls,3);benchmark_profiles(worker,'unused',out,per_operation_limit=1,modes=['voice_editor'],resume=True);self.assertEqual(worker.calls,3)
 def test_strict_gate_rejects_one_percent_failures(self):
  from auk_reliability.acceptance import _add_strict_gate
  g={'technical_success_rate':1.,'automatic_qa_pass_rate':1.,'semantic_success_rate':.99,'semantic_unreviewed_count':0,'joint_success_rate':.99}
  s={'technical_acceptance_pass':True,'by_operation':{'voice_editor/emotion':g},'overall':g};_add_strict_gate(s);self.assertFalse(s['observed_perfect_pass'])
