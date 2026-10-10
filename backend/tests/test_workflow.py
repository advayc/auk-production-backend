import unittest, tempfile, json, csv, zipfile, wave, math, array
from pathlib import Path
from auk_reliability.workflow import *
class WorkflowTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def audio(self):
  p=self.root/'one.wav'
  with wave.open(str(p),'wb') as w:
   w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
   a=array.array('h',[int(4000*math.sin(i*.05)) for i in range(24000*4)]);w.writeframes(a.tobytes())
  return p
 def test_template_no_approval_and_no_overwrite(self):
  self.audio();f=self.root/'clips.csv';self.assertEqual(make_clip_template(self.root,f),1)
  rows=list(csv.DictReader(f.open()));self.assertEqual(rows[0]['rights_verified'],'false');self.assertEqual(rows[0]['accent'],'unknown')
  with self.assertRaises(FileExistsError):make_clip_template(self.root,f)
 def test_manifest_ten_requests_all_active_operations(self):
  self.audio();f=self.root/'clips.csv';make_clip_template(self.root,f);r=list(csv.DictReader(f.open()))[0]
  r.update(transcript='hello world again',transcript_verified='true',rights_verified='true',license='synthetic test',provenance='synthetic test',
   alignment_verified='true',segment_start_seconds='0',segment_end_seconds='2',segment_text='hello world again',replace_old='world',replace_new='moon',
   insert_text='small',insert_anchor='world',insert_position='before',delete_text='world')
  for k in DIMENSIONS:
   if k!='format':r[k]='en' if k=='language' else 'fixture'
  with f.open('w',newline='') as o:w=csv.DictWriter(o,fieldnames=CLIP_FIELDS);w.writeheader();w.writerow(r)
  audit=build_manifest(f,self.root/'manifest.json',reviewer='test',languages=['en'])
  self.assertFalse(audit['valid']);self.assertEqual(audit['request_count'],10);self.assertEqual(len(audit['coverage']),8)
  self.assertFalse(any('request' in e for e in audit['errors']),audit['errors'])
 def test_zip_traversal_blocked(self):
  z=self.root/'x.zip'
  with zipfile.ZipFile(z,'w') as o:o.writestr('../oops','bad')
  with self.assertRaises(ValueError):extract_bundle(z,self.root/'data')
 def test_zip_overwrite_blocked(self):
  z=self.root/'x.zip';(self.root/'data').mkdir();(self.root/'data/a').write_text('old')
  with zipfile.ZipFile(z,'w') as o:o.writestr('a','new')
  with self.assertRaises(FileExistsError):extract_bundle(z,self.root/'data')
 def test_review_is_hash_bound(self):
  p=self.audio();d=self.root/'request';d.mkdir();(d/'result.json').write_text(json.dumps({'output_path':str(p)}))
  r=save_review(d,reviewer='test',passed=False);self.assertFalse(r['passed']);self.assertEqual(r['output_sha256'],sha256_file(p))
 def test_candidate_cannot_promote_simulation(self):
  result=candidate_profiles({'rows':[],'environment':{'simulation':True}})
  self.assertTrue(all(v['recommended_profile'] is None for v in result.values()))
 def test_missing_candidate_blocks_manifest(self):
  f=self.root/'manifest.json';f.write_text(json.dumps({'requests':[{'mode':'voice_editor','operation':'emotion','parameters':{}}]}))
  with self.assertRaises(ValueError):apply_candidates(f,{},self.root/'selected.json')
 def test_screening_floor_cannot_lower(self):
  with self.assertRaises(ValueError):candidate_profiles({'rows':[],'environment':{}},minimum_per_operation=1)
 def test_interrupted_benchmark_blocks_selection(self):
  with self.assertRaises(ValueError):candidate_profiles({'rows':[],'environment':{},'complete':False})
 def test_existing_venv_without_pip_is_repaired(self):
  from unittest import mock
  import auk_reliability.core as core
  env=self.root/'venv';(env/'bin').mkdir(parents=True);(env/'bin/python').touch();calls=[]
  def command(args,**kw):
   calls.append(args)
   if len(calls)==1:raise core.EditorError('process_failed','pip missing')
   return 'pip'
  with mock.patch.object(core,'command',command):self.assertEqual(core.make_venv(env),env/'bin/python')
  self.assertIn('--python',calls[1])
