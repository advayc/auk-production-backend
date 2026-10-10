import unittest, tempfile, json, base64, wave, array, math, dataclasses
from pathlib import Path
from auk_reliability.worker import ReliabilityWorker, configure_default_worker, edit_audio
from auk_reliability.qa import SemanticQAGate
from auk_reliability.core import EditorError, Limits, sha256_file
from auk_reliability.acceptance import percentile, recommend_profiles, run_acceptance_suite, configure_acceptance_suite
from auk_reliability.dataset import validate_dataset
from auk_reliability.policy import OPERATIONS
from auk_reliability.segment import splice

def wav(path,seconds=1):
 a=array.array('h',(int(6000*math.sin(i*.057)) for i in range(round(seconds*24000))))
 with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(a.tobytes())
 return path
class Adapter:
 def __init__(self):self.calls=[];self.stops=0;self.fail=0;self.silent=False
 def run(self,profile,input_audio,plan):
  self.calls.append((profile,dict(plan)))
  if self.fail>0:self.fail-=1;raise EditorError('inference_timeout','fixture timeout')
  raw=Path(input_audio).read_bytes()
  # The real model honors the requested duration; the fixture trims or pads the
  # echoed audio to plan['target_seconds'] so duration validation stays meaningful.
  target=plan.get('target_seconds')
  if isinstance(target,(int,float)) and target>0:
   import io as _io
   with wave.open(_io.BytesIO(raw)) as w:frames=w.readframes(w.getnframes())
   want=int(round(target*24000))*2
   frames=(frames[:want] if len(frames)>=want else frames+b'\0\0'*((want-len(frames))//2))
   b=_io.BytesIO()
   with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(frames)
   raw=b.getvalue()
  if self.silent:
   import io
   b=io.BytesIO()
   with wave.open(b,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b'\0\0'*24000)
   raw=b.getvalue()
  return {'audio':base64.b64encode(raw).decode()},{'fixture':True,'inference_seconds':.01}
 def stop(self):self.stops+=1
class BackendTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=wav(self.root/'source.wav',3)
  self.adapter=Adapter();self.gate=SemanticQAGate(lambda p:{'text':'hello world'},lambda a,b:.9)
  self.worker=ReliabilityWorker(self.adapter,self.root/'runs',semantic_gate=self.gate,runtime_profile={'simulation':True})
  self.p={'source_text':'hello world','rights_confirmed':True,'seed':9}
 def tearDown(self):self.worker.close();self.temp.cleanup()
 def request(self,**p):return self.worker.edit_audio(self.source,'voice_editor','emotion',{**self.p,**p})
 def test_pass_is_review_pending(self):
  r=self.request();self.assertTrue(r.technical_success);self.assertTrue(r.automatic_qa_pass);self.assertIsNone(r.semantic_success);self.assertEqual(r.outcome,'qa_pass_review_pending')
 def test_retry_is_bounded_and_logged(self):
  self.adapter.fail=2;r=self.request();self.assertEqual(len(r.attempts),3);self.assertTrue(r.automatic_qa_pass);self.assertEqual([a['seed'] for a in r.attempts],[9,10,11]);self.assertEqual(self.adapter.stops,2)
 def test_exhausted_timeout(self):
  self.adapter.fail=9;r=self.request();self.assertFalse(r.technical_success);self.assertEqual(len(r.attempts),3)
 def test_missing_qa_is_not_success(self):
  self.worker.gate=SemanticQAGate();r=self.request();self.assertTrue(r.technical_success);self.assertFalse(r.automatic_qa_pass);self.assertIsNone(r.output_path);self.assertEqual(len(r.attempts),1)
 def test_bad_semantics_bounded(self):
  self.worker.gate=SemanticQAGate(lambda p:'wrong words',lambda a,b:.9);r=self.request();self.assertTrue(r.technical_success);self.assertFalse(r.automatic_qa_pass);self.assertEqual(len(r.attempts),3)
 def test_speaker_failure(self):
  self.worker.gate=SemanticQAGate(lambda p:'hello world',lambda a,b:.1);self.assertFalse(self.request().automatic_qa_pass)
 def test_nonfinite_speaker_failure(self):
  self.worker.gate=SemanticQAGate(lambda p:'hello world',lambda a,b:float('nan'));self.assertFalse(self.request().automatic_qa_pass)
 def test_silent_output_never_success(self):
  self.adapter.silent=True;r=self.request();self.assertFalse(r.technical_success);self.assertFalse(r.automatic_qa_pass)
 def test_rights_required(self):
  with self.assertRaises(EditorError):self.request(rights_confirmed=False)
 def test_missing_source_text(self):
  with self.assertRaises(EditorError):self.request(source_text='')
 def test_unknown_profile(self):
  with self.assertRaises(EditorError):self.request(profile='invented')
 def test_wrapper(self):
  configure_default_worker(self.worker);r=edit_audio(self.source,'voice_enhancer','denoise',self.p);self.assertTrue(r.automatic_qa_pass)
 def test_custom_requires_contract(self):
  with self.assertRaises(EditorError):self.worker.edit_audio(self.source,'voice_editor','custom',{**self.p,'instruction':'calm'})
 def test_voice_change_does_not_demand_same_identity(self):
  self.worker.gate=SemanticQAGate(lambda p:'hello world');r=self.worker.edit_audio(self.source,'voice_editor','voice_characteristics',{**self.p,'description':'warm'});self.assertTrue(r.automatic_qa_pass)
 def test_segment_outside_pcm_unchanged(self):
  # Localized edits run the full-context transplant: generation comes from the
  # whole clip (speaker context), the changed phrase is spliced into the
  # verified interval, and audio outside the interval stays byte-exact.
  p={**self.p,'segment_text':'hello world','edited_segment_text':'hello moon','original_text':'world',
   'replacement_text':'moon','alignment_verified':True,'segment_start_seconds':.5,'segment_end_seconds':1.}
  def transcript(path):
   name=Path(path).name
   if name in ('input.wav','normalized-source.wav'):return {'text':'hello world','words':[{'word':'hello','start':.2,'end':.5},{'word':'world','start':.6,'end':.9}]}
   return {'text':'hello moon','words':[{'word':'hello','start':.5,'end':1.0},{'word':'moon','start':1.5,'end':1.85}]}
  self.worker.gate=SemanticQAGate(transcript,lambda a,b:.9)
  r=self.worker.edit_audio(self.source,'transcript_editor','replace',p)
  self.assertTrue(r.automatic_qa_pass)
  splice=r.attempts[0]['splice'];self.assertEqual(splice['method'],'localized_context_transplant')
  self.assertTrue(splice['outside_pcm'].startswith('byte-exact'))
  self.assertTrue(splice['duration_preserved'])
  with wave.open(str(self.source)) as w:src=w.readframes(w.getnframes())
  with wave.open(r.output_path) as w:out=w.readframes(w.getnframes())
  self.assertEqual(len(out),len(src))  # fixed duration: no tail shift
  c0,c1=(int(x*24000)*2 for x in splice['source_cut_seconds'])  # narrowed to 'world' + pads, clamped to interval
  self.assertGreaterEqual(c0,int(.5*24000)*2)  # never outside the verified interval
  self.assertLessEqual(c1,int(1.*24000)*2)
  self.assertLessEqual(c1,int((1.+.12+.001)*24000)*2)  # cut = changed word + pads, not the whole window
  self.assertGreaterEqual(c0,int((.6-.06-.001)*24000)*2)  # and no wider than the changed word + pads
  self.assertEqual(out[:c0],src[:c0])  # before the cut: byte-exact
  self.assertEqual(out[c1:],src[c1:])  # after the cut: byte-exact, unmoved
  self.assertIsNone(r.semantic_success)  # still review-pending
 def test_whole_clip_scope_needs_no_human_alignment_and_keeps_strict_qa(self):
  p={**self.p,'segment_text':'hello world','edited_segment_text':'hello moon','original_text':'world','replacement_text':'moon','segment_scope':'whole_clip'}
  def transcript(path):return {'text':'hello world' if Path(path).name=='input.wav' else 'hello moon'}
  self.worker.gate=SemanticQAGate(transcript,lambda a,b:.9)
  r=self.worker.edit_audio(self.source,'transcript_editor','replace',p)
  self.assertTrue(r.automatic_qa_pass);self.assertIn('skipped',r.attempts[0]['splice']);self.assertEqual(r.attempts[0]['plan']['instruction'],"Replace 'world' with 'moon'.")
  with wave.open(r.output_path) as w:self.assertEqual(w.getnframes(),72000)
  # wrong words are still rejected (no gate weakening)
  self.worker.gate=SemanticQAGate(lambda path:{'text':'hello world' if Path(path).name=='input.wav' else 'hello mouse'},lambda a,b:.9)
  self.assertFalse(self.worker.edit_audio(self.source,'transcript_editor','replace',p).automatic_qa_pass)
  with self.assertRaises(EditorError):self.worker.edit_audio(self.source,'transcript_editor','replace',{**p,'segment_start_seconds':1.0})
 def test_insert_and_delete_local_splices(self):
  cases=[('insert',{'text':'small','anchor':'world','position':'before'},'hello small world',
    [('hello',.5,1.0),('small',1.1,1.4),('world',1.5,2.0)],
    [('hello',.2,.5),('world',1.6,1.9)],(0.4,2.0)),  # source gap [.5,1.6] fits the donor phrase
    ('delete',{'text':'world'},'hello',[('hello',.5,1.0)],
    [('hello',.2,.5),('world',.6,.9)],(.3,1.))]
  for op,fields,expected,gen_words,src_words,win in cases:
   p={**self.p,**fields,'segment_text':'hello world','edited_segment_text':expected,
    'alignment_verified':True,'segment_start_seconds':win[0],'segment_end_seconds':win[1]}
   def transcript(path,expected=expected,gen_words=gen_words,src_words=src_words):
    if Path(path).name in ('input.wav','normalized-source.wav'):
     return {'text':'hello world','words':[{'word':w,'start':a,'end':b} for w,a,b in src_words]}
    return {'text':expected,'words':[{'word':w,'start':a,'end':b} for w,a,b in gen_words]}
   self.worker.gate=SemanticQAGate(transcript,lambda a,b:.9)
   r=self.worker.edit_audio(self.source,'transcript_editor',op,p)
   self.assertTrue(r.automatic_qa_pass)
   splice=r.attempts[0]['splice'];self.assertEqual(splice['method'],'localized_context_transplant')
   self.assertTrue(splice['outside_pcm'].startswith('byte-exact'))
   self.assertTrue(splice['duration_preserved'])
   with wave.open(str(self.source)) as w:src=w.readframes(w.getnframes())
   with wave.open(r.output_path) as w:out=w.readframes(w.getnframes())
   self.assertEqual(len(out),len(src))  # fixed duration: insert/delete never shifts the tail
   c0,c1=(int(x*24000)*2 for x in splice['source_cut_seconds'])
   self.assertGreaterEqual(c0,int(win[0]*24000)*2);self.assertLessEqual(c1,int(win[1]*24000)*2)
   self.assertEqual(out[:c0],src[:c0])
   self.assertEqual(out[c1:],src[c1:])  # byte-exact, unmoved
 def test_window_neighbor_words_keep_original_pcm(self):
  # Regression: a verified window wider than the changed word must not drop
  # unchanged neighbors ('team' was eaten when the whole window was replaced).
  p={**self.p,'source_text':'they were the better team on the night','segment_text':'they were the better team on the night','edited_segment_text':'they were the stronger team on the night',
   'original_text':'better','replacement_text':'stronger','alignment_verified':True,
   'segment_start_seconds':1.34,'segment_end_seconds':2.2}
  def transcript(path):
   if Path(path).name in ('input.wav','normalized-source.wav'):
    return {'text':'they were the better team on the night','words':[
     {'word':'they','start':.1,'end':.3},{'word':'were','start':.35,'end':.6},{'word':'the','start':.65,'end':.8},
     {'word':'better','start':1.34,'end':1.8},{'word':'team','start':1.85,'end':2.2},
     {'word':'on','start':2.3,'end':2.45},{'word':'the','start':2.5,'end':2.6},{'word':'night','start':2.65,'end':2.95}]}
   return {'text':'they were the stronger team on the night','words':[
    {'word':'they','start':.1,'end':.3},{'word':'were','start':.35,'end':.6},{'word':'the','start':.65,'end':.8},
    {'word':'stronger','start':1.2,'end':1.65},{'word':'team','start':1.75,'end':2.05},
    {'word':'on','start':2.1,'end':2.25},{'word':'the','start':2.3,'end':2.4},{'word':'night','start':2.45,'end':2.75}]}
  self.worker.gate=SemanticQAGate(transcript,lambda a,b:.9)
  r=self.worker.edit_audio(self.source,'transcript_editor','replace',p)
  self.assertTrue(r.automatic_qa_pass)
  splice=r.attempts[0]['splice']
  cut=splice['source_cut_seconds']
  self.assertAlmostEqual(cut[0],1.34,places=3)  # pad clamped at the verified interval start, never before it
  self.assertAlmostEqual(cut[1],1.85,places=3)  # 'better' end + pad clamped at 'team' start - 'team' NOT in the cut
  with wave.open(str(self.source)) as w:src=w.readframes(w.getnframes())
  with wave.open(r.output_path) as w:out=w.readframes(w.getnframes())
  self.assertEqual(len(out),len(src))  # fixed duration: no tail shift
  c0,c1=(int(x*24000)*2 for x in cut)
  self.assertEqual(out[:c0],src[:c0])
  self.assertEqual(out[c1:],src[c1:])  # 'team' and everything after: original PCM, unmoved
 def test_ambiguous_alignment_blocks(self):
  with self.assertRaises(EditorError):self.worker.edit_audio(self.source,'transcript_editor','replace',self.p)
 def test_segment_transcript_conflict_blocks(self):
  p={**self.p,'segment_text':'hello world','edited_segment_text':'hello sun','original_text':'world',
    'replacement_text':'moon','alignment_verified':True,'segment_start_seconds':1.,'segment_end_seconds':2.}
  with self.assertRaises(EditorError):self.worker.edit_audio(self.source,'transcript_editor','replace',p)
 def test_no_inference_on_invalid_edit(self):
  with self.assertRaises(EditorError):self.worker.edit_audio(self.source,'voice_enhancer','insert',self.p)
  self.assertFalse(self.adapter.calls)
 def test_missing_manifest_is_not_acceptance(self):
  path=self.root/'manifest.json';path.write_text(json.dumps({'schema_version':1,'clips':[],'requests':[]}))
  a=validate_dataset(path);self.assertFalse(a['valid']);self.assertEqual(a['distinct_sources'],0)
 def test_smoke_and_no_argument_suite(self):
  labels={k:'fixture' for k in ['voice_id','accent','microphone','noise','reverb','speaking_speed','duration_bucket','language']};labels['format']='wav'
  m={'schema_version':1,'clips':[{'id':'one','audio_path':str(self.source),'sha256':sha256_file(self.source),
    'rights_verified':True,'license':'synthetic unittest only','provenance':'test sine fixture','transcript_verified':True,
    'transcript':'hello world','split':'development','labels':labels}],
    'requests':[{'id':'req-1','clip_id':'one','mode':'voice_editor','operation':'emotion','parameters':self.p}]}
  path=self.root/'manifest.json';path.write_text(json.dumps(m));configure_acceptance_suite(self.worker,path,self.root/'suite')
  r=run_acceptance_suite(acceptance=False);self.assertEqual(r['overall']['request_count'],1);self.assertFalse(r['acceptance_pass']);self.assertFalse(r['technical_acceptance_pass']);self.assertEqual(r['status'],'SIMULATED_TEST_ONLY')
 def test_simulations_cannot_recommend(self):
  rows=[{'mode':'voice_editor','operation':'emotion','profile':'base_f32','technical_success':True,'automatic_qa_pass':True,
  'semantic_success':True,'latency_seconds':1,'reason':None,'attempts':[],'case_id':'x','request_dir':None}]*1000
  r=recommend_profiles({'rows':rows,'environment':{'simulation':True}});self.assertIsNone(r['voice_editor/emotion']['recommended_profile'])
 def test_percentiles(self):self.assertEqual(percentile([1,2,3,4],.5),2.5);self.assertIsNone(percentile([],.95))
 def test_cross_process_root_lock(self):
  with self.assertRaises(EditorError):ReliabilityWorker(Adapter(),self.root/'runs')
 def test_all_operations_have_policy(self):self.assertEqual(sum(map(len,OPERATIONS.values())),11)


class MakeVenvFallbackTests(unittest.TestCase):
    def test_venv_without_working_ensurepip(self):
        import tempfile, shutil as _sh
        from unittest import mock
        from pathlib import Path as _P
        import auk_reliability.core as c
        real = c.command
        def fake(args, **kw):
            if list(map(str, args))[1:3] == ['-m', 'venv'] and '--without-pip' not in args:
                raise c.EditorError('process_failed', 'ensurepip failed')
            if 'pip' in map(str, args) and 'install' in map(str, args):
                return ''
            if list(map(str, args))[1:4] == ['-m', 'pip', '--version']:
                return 'pip'
            return real(args, **kw)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(c, 'command', fake):
            py = c.make_venv(_P(d) / 'venv')
            self.assertEqual(py.name, 'python')
            self.assertTrue(py.exists())
