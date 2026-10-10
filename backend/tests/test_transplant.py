import unittest, tempfile, wave, array, math, json
from pathlib import Path
from auk_reliability.transplant import insert_transplant, _find_unique_span, _word_tokens
from auk_reliability.core import EditorError
from auk_reliability.worker import ReliabilityWorker
from auk_reliability.qa import SemanticQAGate
import base64

def tone(path, seconds, freq_step=.057, amp=6000):
    a=array.array('h',(int(amp*math.sin(i*freq_step)) for i in range(round(seconds*24000))))
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(a.tobytes())
    return path

def words_obs(text, entries):
    return {'text':text,'words':[{'word':w,'start':a,'end':b} for w,a,b in entries]}

SRC_WORDS=[('hello',.5,1.0),('world',1.5,2.0)]
GEN_WORDS=[('hello',.3,.8),('big',.8,1.1),('world',1.1,1.6),('hello',2.0,2.5),('world',2.5,3.0)]

class TransplantUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'src.wav',3.0)
        self.gen=tone(self.root/'gen.wav',4.5,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def tx(self,path):
        name=Path(path).name
        if name=='src.wav': return words_obs('hello world',SRC_WORDS)
        if name=='gen.wav': return words_obs('hello big world hello world',GEN_WORDS)
        raise AssertionError(name)
    def test_span_unique_only(self):
        self.assertEqual(_find_unique_span(['a','b','c'],['b','c'],'x'),(1,3))
        with self.assertRaises(EditorError):_find_unique_span(['a','b','a','b'],['a','b'],'x')
        with self.assertRaises(EditorError):_find_unique_span(['a','b'],['c'],'x')
    def test_insert_after_builds_candidate_and_preserves_outside_pcm(self):
        out=self.root/'cand.wav'
        info=insert_transplant(self.src,self.gen,self.tx,'hello','big','after',out)
        with wave.open(str(self.src)) as w:s=w.readframes(w.getnframes())
        with wave.open(str(out)) as w:c=w.readframes(w.getnframes())
        cut0=int((.5-.06)*24000);tail_from=int((1.0+.12)*24000)
        self.assertEqual(c[:cut0*2],s[:cut0*2])  # head byte-exact
        self.assertEqual(c[len(c)-(len(s)-tail_from*2):],s[tail_from*2:])  # tail byte-exact, shifted
        self.assertEqual(info['method'],'asr_guided_transplant')
        self.assertEqual(info['outside_pcm'].startswith('byte-exact'),True)
    def test_insert_before(self):
        def tx2(path):
            if Path(path).name=='src.wav': return words_obs('hello world',SRC_WORDS)
            return words_obs('big hello world',[('big',.3,.6),('hello',.6,1.0),('world',1.2,1.7)])
        out=self.root/'cand2.wav'
        info=insert_transplant(self.src,self.gen,tx2,'hello','big','before',out)
        self.assertEqual(info['generation_span_seconds'][0],round(.3-.06,3))
    def test_ambiguous_generation_span_fails_closed(self):
        def tx3(path):
            if Path(path).name=='src.wav': return words_obs('hello world',SRC_WORDS)
            return words_obs('hello big hello big',[('hello',.3,.8),('big',.8,1.1),('hello',1.5,2.0),('big',2.0,2.3)])
        with self.assertRaises(EditorError) as ctx:
            insert_transplant(self.src,self.gen,tx3,'hello','big','after',self.root/'c3.wav')
        self.assertEqual(ctx.exception.code,'transplant_span_ambiguous')
    def test_missing_word_timestamps_fail_closed(self):
        with self.assertRaises(EditorError) as ctx:
            insert_transplant(self.src,self.gen,lambda p:{'text':'hello big world'},'hello','big','after',self.root/'c4.wav')
        self.assertEqual(ctx.exception.code,'transplant_alignment_unavailable')

class SalvageAdapter:
    def __init__(self,generation):self.generation=generation
    def run(self,profile,input_audio,plan):
        return {'audio':base64.b64encode(Path(self.generation).read_bytes()).decode()},{'fixture':True,'inference_seconds':.01}
    def stop(self):pass

class SalvageIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=tone(self.root/'source.wav',3.0)
        self.generation=tone(self.root/'generation.wav',4.5,freq_step=.091)
        self.adapter=SalvageAdapter(self.generation)
    def tearDown(self):self.temp.cleanup()
    def params(self):
        return {'source_text':'hello world','rights_confirmed':True,'seed':9,'profile':'base_f32',
         'segment_scope':'whole_clip','segment_text':'hello world','edited_segment_text':'hello big world',
         'text':'big','anchor':'hello','position':'after'}
    def gate(self):
        def tx(path):
            name=Path(path).name
            if name=='input.wav': return words_obs('hello world',SRC_WORDS)
            if name=='output.wav': return words_obs('hello hello big world hello world',[('hello',.1,.4)]+GEN_WORDS)
            if name=='candidate.wav': return words_obs('hello big world',[('hello',.5,1.0),('big',1.0,1.3),('world',1.5,2.0)])
            return {'text':'unknown fixture file','words':[]}
        return SemanticQAGate(tx,lambda a,b:.9)
    def test_restart_defect_salvaged_with_same_gates(self):
        worker=ReliabilityWorker(self.adapter,self.root/'runs',semantic_gate=self.gate(),runtime_profile={'simulation':True})
        try:
            r=worker.edit_audio(self.source,'transcript_editor','insert',self.params())
        finally:worker.close()
        self.assertTrue(r.technical_success);self.assertTrue(r.automatic_qa_pass)
        self.assertIsNone(r.semantic_success)  # still review-pending, never auto-approved
        self.assertTrue(r.output_path.endswith('candidate.wav'))
        salvage=r.attempts[0].get('salvage')
        self.assertIsNotNone(salvage);self.assertEqual(salvage['method'],'asr_guided_transplant')
        self.assertEqual(salvage['qa']['checks']['transcript']['observed'],'hello big world')
        with wave.open(str(self.source)) as w:s=w.readframes(w.getnframes())
        with wave.open(r.output_path) as w:c=w.readframes(w.getnframes())
        cut0=int((.5-.06)*24000)
        self.assertEqual(c[:cut0*2],s[:cut0*2])
    def test_salvage_fails_closed_when_no_clean_span(self):
        def tx(path):
            name=Path(path).name
            if name=='input.wav': return words_obs('hello world',SRC_WORDS)
            if name=='output.wav': return {'text':'hello world','words':[{'word':'hello','start':.1,'end':.5},{'word':'world','start':.6,'end':1.0}]}  # insert omitted
            return {'text':'?','words':[]}
        worker=ReliabilityWorker(self.adapter,self.root/'runs2',semantic_gate=SemanticQAGate(tx,lambda a,b:.9),runtime_profile={'simulation':True})
        try:
            r=worker.edit_audio(self.source,'transcript_editor','insert',self.params())
        finally:worker.close()
        self.assertFalse(r.automatic_qa_pass);self.assertIsNone(r.output_path)
        self.assertEqual(r.attempts[0].get('salvage_error'),'transplant_span_ambiguous')
        self.assertEqual(len(r.attempts),3)  # retry budget unchanged, no salvage loop
    def test_no_salvage_when_transcript_passes_but_speaker_fails(self):
        def tx(path):
            name=Path(path).name
            if name=='input.wav': return words_obs('hello world',SRC_WORDS)
            return words_obs('hello big world',[('hello',.3,.8),('big',.8,1.1),('world',1.1,1.6)])
        worker=ReliabilityWorker(self.adapter,self.root/'runs3',semantic_gate=SemanticQAGate(tx,lambda a,b:.1),runtime_profile={'simulation':True})
        try:
            r=worker.edit_audio(self.source,'transcript_editor','insert',self.params())
        finally:worker.close()
        self.assertFalse(r.automatic_qa_pass)
        self.assertNotIn('salvage',r.attempts[0])  # words already right; voice defect is not transplantable

if __name__=='__main__':unittest.main()

def _frames(path):
    with wave.open(str(path)) as w:
        return w.getnframes(), w.readframes(w.getnframes())

class LocalizedIntervalContractTests(unittest.TestCase):
    """v0.3.0: the verified interval is the hard preservation boundary.
    Fixed duration, cut clamped inside it, frame-exact donor fit or fail closed."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'lsrc.wav',3.0)
        self.gen=tone(self.root/'lgen.wav',3.0,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def _run(self, start, end, src_words, src_text, edited_text, gen_words,
             src_file=None, gen_file=None):
        from auk_reliability.transplant import localized_transplant
        sf=src_file or self.src; gf=gen_file or self.gen
        def tx(path):
            name=Path(path).name
            if name==Path(sf).name: return words_obs(src_text,src_words)
            if name==Path(gf).name: return words_obs(edited_text,gen_words)
            return words_obs(edited_text,gen_words)
        out=self.root/'lout.wav'
        return localized_transplant(sf,gf,tx,start,end,src_text,edited_text,out), out
    def test_replace_duration_preserved_cut_clamped_outside_exact(self):
        info,out=self._run(1.1,1.7,
            [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa xyz ccc',
            [('aaa',.4,.8),('xyz',1.0,1.5),('ccc',1.8,2.2)])
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)  # fixed duration: output length identical
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertGreaterEqual(cut0,int(1.1*24000));self.assertLessEqual(cut1,int(1.7*24000))
        self.assertEqual(ob[:cut0*2],sb[:cut0*2])   # head byte-exact, unmoved
        self.assertEqual(ob[cut1*2:],sb[cut1*2:])   # tail byte-exact, unmoved
        self.assertTrue(info['duration_preserved']);self.assertTrue(info['cut_clamped_to_interval'])
    def test_pads_truncated_at_interval_edges(self):
        info,out=self._run(1.15,1.65,
            [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa xyz ccc',
            [('aaa',.4,.8),('xyz',1.0,1.5),('ccc',1.8,2.2)])
        self.assertEqual(info['source_cut_seconds'][0],1.15)
        self.assertEqual(info['source_cut_seconds'][1],1.65)
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)
        self.assertEqual(ob[:int(1.15*24000)*2],sb[:int(1.15*24000)*2])
        self.assertEqual(ob[int(1.65*24000)*2:],sb[int(1.65*24000)*2:])
    def test_cut_never_clips_neighbor_words(self):
        info,out=self._run(1.1,1.75,
            [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',1.65,2.0)],'aaa bbb ccc','aaa xyz ccc',
            [('aaa',.4,.8),('xyz',1.0,1.4),('ccc',1.6,2.0)])
        self.assertLessEqual(info['source_cut_seconds'][1],1.65)  # clamped to neighbor start, not pad_post
    def test_cut_grows_into_interval_room_tone_to_fit_donor(self):
        info,out=self._run(1.1,1.95,
            [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa xyz ccc',
            [('aaa',.4,.8),('xyz',1.0,1.62),('ccc',1.9,2.3)])  # donor word 0.62s > default cut 0.58s
        self.assertAlmostEqual(info['source_cut_seconds'][1],1.76,places=2)  # grew past pad_post, still inside interval
        self.assertLessEqual(info['source_cut_seconds'][1],1.95)
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertEqual(ob[:cut0*2],sb[:cut0*2]);self.assertEqual(ob[cut1*2:],sb[cut1*2:])
    def test_donor_words_longer_than_cut_fail_closed(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(1.1,1.7,
                [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa xyz ccc',
                [('aaa',.4,.8),('xyz',1.0,1.62),('ccc',1.9,2.3)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_insufficient_donor_room_tone_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(1.1,1.7,
                [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa xyz ccc',
                [('aaa',.4,.49),('xyz',.49,1.0),('ccc',1.0,1.4)])  # donor words packed, no room tone
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_deletion_fills_exact_frames_with_room_tone(self):
        info,out=self._run(1.1,1.7,
            [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa ccc',
            [('aaa',.4,.8),('ccc',1.5,1.9)])
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)  # deletion keeps duration; no silent gap, no shift
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertEqual(ob[:cut0*2],sb[:cut0*2]);self.assertEqual(ob[cut1*2:],sb[cut1*2:])
    def test_deletion_gap_too_short_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(1.1,1.7,
                [('aaa',.5,.9),('bbb',1.2,1.6),('ccc',2.0,2.4)],'aaa bbb ccc','aaa ccc',
                [('aaa',.4,.8),('ccc',.9,1.3)])  # 0.1s gap < 0.56s cut
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_insertion_fits_interval_room_tone(self):
        info,out=self._run(0.8,2.6,
            [('aaa',.5,.9),('ccc',2.0,2.4)],'aaa ccc','aaa bbb ccc',
            [('aaa',.4,.8),('bbb',1.0,1.4),('ccc',1.8,2.2)])
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)  # insertion at fixed duration inside a wider interval
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertGreaterEqual(cut0,int(0.8*24000));self.assertLessEqual(cut1,int(2.6*24000))
        self.assertGreaterEqual(cut0,int(0.9*24000));self.assertLessEqual(cut1,int(2.0*24000))  # kept words untouched
        self.assertEqual(ob[:cut0*2],sb[:cut0*2]);self.assertEqual(ob[cut1*2:],sb[cut1*2:])
    def test_insertion_too_long_for_interval_fails_closed(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(0.8,2.6,
                [('aaa',.5,.9),('ccc',1.2,1.6)],'aaa ccc','aaa bbb ccc',  # only 0.3s gap
                [('aaa',.4,.8),('bbb',1.0,1.4),('ccc',1.8,2.2)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
        self.assertIn('widen the interval',str(ctx.exception))

class InsertPatchClampTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'src.wav',3.0)
        self.gen=tone(self.root/'gen.wav',4.5,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def test_patch_never_includes_following_generation_word(self):
        # 'world' starts only .05s after 'big' ends (< pad_post .12): the patch
        # must stop at 'world'.start instead of absorbing its onset.
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('hello world',SRC_WORDS)
            return words_obs('hello big world',[('hello',.3,.8),('big',.8,1.1),('world',1.15,1.6)])
        out=self.root/'c.wav'
        info=insert_transplant(self.src,self.gen,tx,'hello','big','after',out)
        self.assertEqual(info['generation_span_seconds'][1],1.15)
    def test_patch_never_includes_preceding_generation_word(self):
        # previous word ends .29, 'hello' starts .3 (< pad_pre .06 gap):
        # g0 clamps to prev word end.
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('hello world',SRC_WORDS)
            return words_obs('well hello big world',[('well',.0,.29),('hello',.3,.8),('big',.8,1.1),('world',1.3,1.8)])
        out=self.root/'c2.wav'
        info=insert_transplant(self.src,self.gen,tx,'hello','big','after',out)
        self.assertEqual(info['generation_span_seconds'][0],0.29)

class InsertSourceCutClampTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'src.wav',3.0)
        self.gen=tone(self.root/'gen.wav',4.5,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def test_cut_stops_at_following_source_word(self):
        # 'to' starts 1.26, contiguous with 'managed' end 1.26 (< pad_post .12):
        # the cut must stop at 1.26 so the next word keeps its full onset.
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('i managed to take',[(' i',.5,.96),(' managed',.96,1.26),(' to',1.26,1.42),(' take',1.42,1.62)])
            return words_obs('i managed really',[(' i',.0,.22),(' managed',.22,.46),(' really.',.46,.78)])
        out=self.root/'c3.wav'
        info=insert_transplant(self.src,self.gen,tx,'i managed','really','after',out)
        self.assertEqual(info['source_span_seconds'][1],1.26)
        with wave.open(str(self.src)) as w:s=w.readframes(w.getnframes())
        with wave.open(str(out)) as w:c=w.readframes(w.getnframes())
        tail_from=int(1.26*24000)
        self.assertEqual(c[len(c)-(len(s)-tail_from*2):],s[tail_from*2:])  # 'to' onward byte-exact

class InsertBoundaryContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'src.wav',3.0)
        self.gen=tone(self.root/'gen.wav',4.5,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def test_overlapping_next_word_never_truncates_anchor(self):
        # next source word OVERLAPS the anchor end (ASR jitter): cut must still
        # cover the full anchor, and the following word keeps everything after it.
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('i managed to take',[(' i',.5,.96),(' managed',.96,1.26),(' to',1.20,1.42),(' take',1.42,1.62)])
            return words_obs('i managed really',[(' i',.0,.22),(' managed',.22,.46),(' really.',.46,.78)])
        out=self.root/'c4.wav'
        info=insert_transplant(self.src,self.gen,tx,'i managed','really','after',out)
        self.assertEqual(info['source_span_seconds'][1],1.26)  # full anchor cut, not 1.20
    def test_overlapping_prev_word_never_delays_anchor_start(self):
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('well i managed to',[(' well',.2,.55),(' i',.5,.96),(' managed',.96,1.26),(' to',1.3,1.5)])
            return words_obs('i managed really',[(' i',.0,.22),(' managed',.22,.46),(' really.',.46,.78)])
        out=self.root/'c5.wav'
        info=insert_transplant(self.src,self.gen,tx,'i managed','really','after',out)
        self.assertEqual(info['source_span_seconds'][0],0.5)  # anchor start, not prev end .55
    def test_gen_overlap_keeps_full_phrase(self):
        def tx(path):
            name=Path(path).name
            if name=='src.wav': return words_obs('hello world',SRC_WORDS)
            # next gen word overlaps 'big' end: patch must still cover 'big' fully
            return words_obs('hello big world',[('hello',.3,.8),('big',.8,1.1),('world',1.05,1.6)])
        out=self.root/'c6.wav'
        info=insert_transplant(self.src,self.gen,tx,'hello','big','after',out)
        self.assertEqual(info['generation_span_seconds'][1],1.1)
