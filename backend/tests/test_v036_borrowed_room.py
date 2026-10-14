import unittest, tempfile, wave, array, math
from pathlib import Path
from auk_reliability.transplant import localized_transplant
from auk_reliability.core import EditorError

def tone(path, seconds, freq_step=.057, amp=6000, quiet_tail=0.0, quiet_head=0.0):
    n=round(seconds*24000); vals=[]
    for i in range(n):
        t=i/24000
        a=8 if (t<quiet_head or t>=seconds-quiet_tail) else amp  # quiet floor, not digital zero
        vals.append(int(a*math.sin(i*freq_step)))
    a=array.array('h',vals)
    with wave.open(str(path),'wb') as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(a.tobytes())
    return path

def words_obs(text, entries):
    return {'text':text,'words':[{'word':w,'start':a,'end':b} for w,a,b in entries]}

def _frames(path):
    with wave.open(str(path)) as w:
        return w.getnframes(), w.readframes(w.getnframes())

class BorrowedRoomTests(unittest.TestCase):
    """EXPERIMENTAL (unqualified, opt-in): borrowed-room assembly for packed
    donors. Default path (flag off) must be byte-identical to v0.3.5."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.src=tone(self.root/'bsrc.wav',3.0)
        # packed donor: speech everywhere except a true quiet head
        self.gen=tone(self.root/'bgen.wav',1.9,freq_step=.091,quiet_head=0.15)
        # fully-packed donor: no quiet region at all
        self.gen_nr=tone(self.root/'bgen2.wav',1.9,freq_step=.091)
    def tearDown(self):self.temp.cleanup()
    SRC_W=[('the',.59,1.07),('better',1.39,1.75),('team',1.79,2.05),('on',2.09,2.41),('night',2.45,2.90)]
    SRC_T='the better team on night'
    def _run(self, gen, edited, gen_words, flag=True, out='bout.wav'):
        def tx(path):
            if Path(path).name==Path(self.src).name: return words_obs(self.SRC_T,self.SRC_W)
            return words_obs(edited,gen_words)
        return localized_transplant(self.src,gen,tx,1.34,2.20,self.SRC_T,edited,self.root/out,
                                    allow_borrowed_room=flag)
    def test_packed_donor_rescued_word_bytes_exact(self):
        info=self._run(self.gen,'the stronger team on night',
            [('the',.10,.40),('stronger',.40,.88),('team',.88,1.10),('on',1.10,1.44),('night',1.44,1.80)])
        self.assertEqual(info['span_strategy'],'changed_plus_trailing_equal_words_borrowed_room')
        sn,sb=_frames(self.src); on,ob=_frames(self.root/'bout.wav')
        self.assertEqual(on,sn)
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        self.assertEqual(ob[:cut0*2],sb[:cut0*2]);self.assertEqual(ob[cut1*2:],sb[cut1*2:])
        # donor word region copied byte-exact
        _,gb=_frames(self.gen)
        ds=int(.40*24000)*2;de=int(1.10*24000)*2;wf=(de-ds)
        pre=((cut1-cut0)*2-wf)//2
        self.assertEqual(ob[cut0*2+pre:cut0*2+pre+wf],gb[ds:de])
    def test_flag_off_fails_closed_identical_to_v035(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(self.gen,'the stronger team on night',
                [('the',.10,.40),('stronger',.40,.86),('team',.86,1.12),('on',1.12,1.44),('night',1.44,1.80)],flag=False)
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_no_verified_room_refuses(self):
        with self.assertRaises(EditorError) as ctx:
            self._run(self.gen_nr,'the stronger team on night',
                [('the',.0,.30),('stronger',.30,.76),('team',.76,1.02),('on',1.02,1.34),('night',1.34,1.70)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_changed_only_borrowed_when_single_word_fits(self):
        info=self._run(self.gen,'the good team on night',
            [('the',.10,.40),('good',.40,.54),('team',.54,.80),('on',.80,1.14),('night',1.14,1.50)])
        self.assertEqual(info['span_strategy'],'changed_only_borrowed_room')
        self.assertEqual(info['regenerated_neighbor_words'],'')

    def _max_abs(self, raw_bytes):
        import array as _arr
        a=_arr.array('h'); a.frombytes(raw_bytes)
        return max((abs(x) for x in a), default=0)
    def test_tiled_room_boundary_integrity(self):
        # 100ms verified head room; slack requires ~3s of room -> tiling with
        # internal crossfades. Room interiors must contain ONLY room-level
        # samples (no donor speech leaks through the tiling).
        info=self._run(self.gen,'the good team on night',
            [('the',.10,.40),('good',.40,.60),('team',.60,.86),('on',.86,1.20),('night',1.20,1.56)])
        self.assertEqual(info['span_strategy'],'changed_only_borrowed_room')
        _,ob=_frames(self.root/'bout.wav'); _,gb=_frames(self.gen)
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        ds=int(.40*24000)*2;de=int(.60*24000)*2;wf=de-ds
        pre=((cut1-cut0)*2-wf)//2
        # donor word region byte-exact
        self.assertEqual(ob[cut0*2+pre:cut0*2+pre+wf],gb[ds:de])
        # room interiors (outside the external-crossfade edges) stay at room level
        xf_b=600*2
        self.assertLessEqual(self._max_abs(ob[cut0*2+xf_b:cut0*2+pre]),8)
        self.assertLessEqual(self._max_abs(ob[cut0*2+pre+wf:cut1*2-xf_b]),8)
    def test_longest_room_run_is_selected(self):
        # head run 0.10s at floor 8, tail run 0.30s at floor 24: the longest
        # run (tail) must be the one tiled into the patch.
        import array as _arr, wave as _w
        n=round(1.9*24000); vals=[]
        for i in range(n):
            t=i/24000
            a=8 if t<0.10 else (24 if t>=1.60 else 6000)
            vals.append(int(a*math.sin(i*.091)))
        with _w.open(str(self.root/'bgen3.wav'),'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000)
            f.writeframes(_arr.array('h',vals).tobytes())
        info=self._run(self.root/'bgen3.wav','the good team on night',
            [('the',.10,.40),('good',.40,.60),('team',.60,.86),('on',.86,1.20),('night',1.20,1.56)])
        self.assertEqual(info['span_strategy'],'changed_only_borrowed_room')
        _,ob=_frames(self.root/'bout.wav')
        cut0=int(info['source_cut_seconds'][0]*24000);cut1=int(info['source_cut_seconds'][1]*24000)
        ds=int(.40*24000)*2;de=int(.60*24000)*2;wf=de-ds
        pre=((cut1-cut0)*2-wf)//2
        head_max=self._max_abs(ob[cut0*2+1200:cut0*2+pre])
        self.assertGreater(head_max,8)   # not the head run
        self.assertLessEqual(head_max,24)  # exactly the tail run's level
    def test_slack_too_small_for_crossfades_refuses(self):
        # word fits lengthwise at extra=0 but leaves < xf of room per side,
        # and wider spans fail on length: must fail closed, never clip words.
        with self.assertRaises(EditorError) as ctx:
            self._run(self.gen,'the stronger team on night',
                [('the',.10,.40),('stronger',.40,.82),('team',.82,1.20),('on',1.20,1.44),('night',1.44,1.80)])
        self.assertEqual(ctx.exception.code,'transplant_duration_mismatch')
    def test_natural_room_still_preferred_over_borrowed(self):
        gen2=tone(self.root/'bgen3.wav',3.0,freq_step=.091,quiet_head=.5,quiet_tail=.5)
        info=self._run(gen2,'the stronger team on night',
            [('the',.60,1.00),('stronger',1.10,1.40),('team',1.60,1.90),('on',2.00,2.30),('night',2.34,2.70)],out='bout3.wav')
        self.assertEqual(info['span_strategy'],'changed_only')

if __name__=='__main__':unittest.main()
