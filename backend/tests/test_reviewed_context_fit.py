"""Bound selected-context reuse. Synthetic PCM, not model/listening evidence."""
import copy, tempfile, unittest, wave, array, math
from pathlib import Path
from auk_reliability.transcriptflow import TranscriptSession
from auk_reliability.segment import verify_alignment
from auk_reliability.transplant import localized_transplant
from auk_reliability.core import EditorError

TEXT='alpha beta gamma tail'
WORDS=[dict(word=w,start=a,end=b,probability=.99) for w,a,b in
       [('alpha',0,.42),('beta',.42,.78),('gamma',.78,1.32),('tail',1.32,1.7)]]
def asr(p):return dict(text=TEXT,words=copy.deepcopy(WORDS))
def tone(p,f):
 with wave.open(str(p),'wb') as w:
  w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000)
  w.writeframes(array.array('h',(int(5000*math.sin(i*f)) for i in range(48000))).tobytes())
class ReviewedContext(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.r=Path(self.t.name);self.src=self.r/'source.wav';self.gen=self.r/'donor.wav';tone(self.src,.1);tone(self.gen,.2)
  self.s=TranscriptSession(self.src,asr,self.r/'session',flow_registry=self.r/'registry');self.s.transcribe()
 def tearDown(self):self.t.cleanup()
 def params(self):
  c=self.s.review_candidates('alpha beta gamma')[0]
  return self.s.span_params('alpha beta gamma','delta beta gamma',confirmation_token=self.s.confirm_span(c))
 def donor(self,p):
  self.assertEqual(p,self.gen) # source ASR is never used to override session text
  return dict(text='delta beta gamma tail',words=[dict(word=w,start=a,end=b) for w,a,b in [('delta',0,.3),('beta',.3,.7),('gamma',.7,1.32),('tail',1.32,1.7)]])
 def fit(self,p):
  return localized_transplant(self.src,self.gen,self.donor,0,1.32,TEXT,'delta beta gamma tail',self.r/'out.wav',measured_span=p['changed_span_words'],reviewed_span=p.get('reviewed_span_words'))
 def test_selected_context_fits_without_changing_outside(self):
  p=self.params();rec=self.fit(p)
  self.assertEqual(rec['regenerated_neighbor_words'],'beta gamma')
  with wave.open(str(self.src)) as w:a=w.readframes(w.getnframes())
  with wave.open(str(self.r/'out.wav')) as w:b=w.readframes(w.getnframes())
  self.assertEqual(len(a),len(b));self.assertEqual(a[63360:],b[63360:])
 def test_old_changed_only_evidence_still_fails_closed(self):
  p=self.params();p.pop('reviewed_span_words')
  with self.assertRaises(EditorError) as e:self.fit(p)
  self.assertEqual(e.exception.code,'transplant_duration_mismatch');self.assertIn('safe surrounding room',str(e.exception))
 def test_context_word_tamper_fails_mac(self):
  p=self.params();p['reviewed_span_words']['words'][1]['word']='other'
  with self.assertRaises(EditorError) as e:verify_alignment(self.src,p,asr,flow_registry=self.r/'registry')
  self.assertEqual(e.exception.code,'flow_evidence_invalid')
 def test_context_offset_tamper_fails_mac(self):
  p=self.params();p['reviewed_span_words']['source_token_start']=1
  with self.assertRaises(EditorError) as e:verify_alignment(self.src,p,asr,flow_registry=self.r/'registry')
  self.assertEqual(e.exception.code,'flow_evidence_invalid')
 def test_outside_context_refused_even_at_internal_api(self):
  p=self.params();p['reviewed_span_words']['words'][-1]['end']='1.4'
  with self.assertRaises(EditorError):self.fit(p)
 def test_bad_order_refused(self):
  p=self.params();p['reviewed_span_words']['words'][1]['start']='0.2'
  with self.assertRaises(EditorError):self.fit(p)
 def test_changed_timing_mismatch_refused(self):
  p=self.params();p['reviewed_span_words']['words'][0]['end']='0.4'
  with self.assertRaises(EditorError):self.fit(p)
 def test_wrong_token_context_refused(self):
  p=self.params();p['reviewed_span_words']['words'][1]['word']='wrong'
  with self.assertRaises(EditorError):self.fit(p)
 def test_corrected_flow_uses_bound_context_without_source_asr(self):
  # Simulate already-reviewed corrected words with established acoustic times.
  self.s.corrected=True;p=self.params()
  verify_alignment(self.src,p,lambda p:self.fail('source ASR must not override corrections'),flow_registry=self.r/'registry')
  self.assertEqual(self.fit(p)['source_interval_seconds'],[0,1.32])
 def test_nonfinite_context_refused(self):
  for value in ['nan','inf','-inf']:
   p=self.params();p['reviewed_span_words']['words'][1]['start']=value
   with self.assertRaises(EditorError):self.fit(p)
 def test_outer_neighbor_tamper_fails_mac(self):
  p=self.params();p['reviewed_span_words']['next_word_start']='2.0'
  with self.assertRaises(EditorError) as e:verify_alignment(self.src,p,asr,flow_registry=self.r/'registry')
  self.assertEqual(e.exception.code,'flow_evidence_invalid')
 def test_outer_neighbor_overlap_refused(self):
  p=self.params();p['reviewed_span_words']['next_word_start']='1.2'
  with self.assertRaises(EditorError):self.fit(p)
 def test_context_beyond_reviewed_selection_cannot_supply_room(self):
  p=self.params();p['reviewed_span_words']['words'].append(dict(word='tail',start='1.32',end='1.7'))
  with self.assertRaises(EditorError):self.fit(p)
