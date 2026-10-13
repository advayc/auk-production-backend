import unittest, tempfile, wave, array, math
from pathlib import Path
from auk_reliability.transplant import localized_transplant
from auk_reliability.core import EditorError

def tone(path, seconds, freq_step=.057, amp=6000):
    a=array.array('h',(int(amp*math.sin(i*freq_step)) for i in range(round(seconds*24000))))
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(a.tobytes())
    return path

def words_obs(text, entries):
    return {'text':text,'words':[{'word':w,'start':a,'end':b} for w,a,b in entries]}

def _frames(path):
    with wave.open(str(path)) as w:
        return w.getnframes(), w.readframes(w.getnframes())

class MultiwordSpanTests(unittest.TestCase):
    """v0.3.5: when the changed word alone cannot fit the interval cut, the
    replace path widens the span with trailing EQUAL words that sit fully
    inside the verified interval. The text never changes, the cut never
    crosses the interval, outside-interval PCM stays byte-exact, duration is
    preserved, and the smallest fitting span wins. Anything that still cannot
    fit fails closed."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'msrc.wav',3.0)
        self.gen=tone(self.root/'mgen.wav',3.0,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    def _run(self, start, end, src_words, src_text, edited_text, gen_words):
        def tx(path):
            name=Path(path).name
            if name==Path(self.src).name: return words_obs(src_text,src_words)
            return words_obs(edited_text,gen_words)
        out=self.root/'mout.wav'
        return localized_transplant(self.src,self.gen,tx,start,end,src_text,edited_text,out), out

    SRC_W=[('the',.59,1.07),('better',1.39,1.75),('team',1.79,2.05),('on',2.09,2.41),('night',2.45,2.90)]
    SRC_T='the better team on night'
    EDIT_T='the stronger team on night'

    def test_base_fit_keeps_changed_only_strategy(self):
        # Donor changed word fits the default cut: behavior identical to v0.3.4.
        info,out=self._run(1.34,2.20,self.SRC_W,self.SRC_T,self.EDIT_T,
            [('the',.70,1.10),('stronger',1.30,1.58),('team',2.00,2.26),('on',2.30,2.60),('night',2.60,3.00)])
        self.assertEqual(info['span_strategy'],'changed_only')
        self.assertEqual(info['regenerated_neighbor_words'],'')

    def test_trailing_equal_word_span_fits(self):
        # Donor 'stronger' (0.46s) is longer than the default 'better' cut
        # (0.45s after interval clamping), but 'stronger team' (0.74s) fits the
        # widened 'better team' cut (0.75s) fully inside the interval.
        info,out=self._run(1.34,2.20,self.SRC_W,self.SRC_T,self.EDIT_T,
            [('the',.90,1.28),('stronger',1.32,1.78),('team',1.82,2.06),('on',2.14,2.50),('night',2.50,3.00)])
        self.assertEqual(info['span_strategy'],'changed_plus_trailing_equal_words')
        self.assertEqual(info['regenerated_neighbor_words'],'team')
        sn,sb=_frames(self.src); on,ob=_frames(out)
        self.assertEqual(on,sn)  # fixed duration
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertGreaterEqual(cut0,int(1.34*24000));self.assertLessEqual(cut1,int(2.20*24000))
        self.assertEqual(ob[:cut0*2],sb[:cut0*2])   # head byte-exact
        self.assertEqual(ob[cut1*2:],sb[cut1*2:])   # tail byte-exact
        self.assertTrue(info['duration_preserved']);self.assertTrue(info['cut_clamped_to_interval'])

    def test_no_fitting_span_inside_interval_fails_closed(self):
        # Donor 'stronger team' (0.98s) exceeds every span that fits inside the
        # interval; 'on' would cross the interval edge, so nothing may be used.
        with self.assertRaises(EditorError) as ctx:
            self._run(1.34,2.20,self.SRC_W,self.SRC_T,self.EDIT_T,
                [('the',.90,1.28),('stronger',1.32,1.98),('team',2.02,2.30),('on',2.34,2.70),('night',2.70,3.00)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')

    def test_trailing_word_crossing_interval_is_never_used(self):
        # The only trailing equal word ends outside the verified interval:
        # the span search must refuse to cross it and fail closed.
        src_w=[('the',.59,1.07),('better',1.39,1.61),('team',2.18,2.50)]
        with self.assertRaises(EditorError) as ctx:
            self._run(1.34,2.20,src_w,'the better team','the stronger team',
                [('the',.90,1.28),('stronger',1.32,2.30),('team',2.34,2.66)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')

    def test_deletion_and_insertion_report_strategy(self):
        # Strategy metadata exists on every localized path, not just replace.
        info,_=self._run(1.34,2.20,
            [('the',.59,1.07),('better',1.39,1.75),('team',1.79,2.05),('on',2.09,2.41)],
            'the better team on','the team on',
            [('the',.60,1.00),('team',1.60,1.90),('on',2.00,2.40)])
        self.assertEqual(info['span_strategy'],'deletion')
        self.assertEqual(info['regenerated_neighbor_words'],'')

if __name__=='__main__':unittest.main()
