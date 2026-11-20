import json,tempfile,unittest,wave,array,math
from pathlib import Path
from auk_reliability.export import export_mp3_final
from auk_reliability.core import EditorError
class FinalMP3(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.r=Path(self.t.name);self.wav=self.r/'processing.wav'
  with wave.open(str(self.wav),'wb') as w:
   w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(array.array('h',(int(6000*math.sin(i*.08)) for i in range(24000))).tobytes())
  self.d=dict(technical_success=True,automatic_qa_pass=True,output_path=str(self.wav));self.save()
 def tearDown(self):self.t.cleanup()
 def save(self):(self.r/'result.json').write_text(json.dumps(self.d))
 def test_mp3_final_preserves_internal_wav_and_result(self):
  before=self.wav.read_bytes();result=(self.r/'result.json').read_bytes();r=export_mp3_final(self.r)
  self.assertEqual(self.wav.read_bytes(),before);self.assertEqual((self.r/'result.json').read_bytes(),result)
  self.assertTrue(Path(r['output_path']).is_file());self.assertEqual(r['format'],'mp3');self.assertEqual(json.loads((self.r/'final-result.json').read_text())['output_path'],r['output_path']);self.assertTrue(r['lossy']);self.assertEqual(r['sample_rate'],48000)
  import subprocess
  meta=json.loads(subprocess.run(['ffprobe','-v','error','-show_streams','-of','json',r['output_path']],capture_output=True,text=True,check=True).stdout)['streams'][0]
  self.assertEqual(int(meta['bit_rate']),320000);self.assertEqual(int(meta['sample_rate']),48000)
  self.assertEqual(json.loads((self.r/'final-export.json').read_text())['mp3_sha256'],r['mp3_sha256'])
 def test_refuses_failed_qa(self):
  self.d['automatic_qa_pass']=False;self.save()
  with self.assertRaises(EditorError):export_mp3_final(self.r)
  self.assertFalse((self.r/'final.mp3').exists())
 def test_refuses_failed_edit(self):
  self.d['technical_success']=False;self.save()
  with self.assertRaises(EditorError):export_mp3_final(self.r)
 def test_refuses_external_source(self):
  self.d['output_path']='/tmp/not-this-request.wav';self.save()
  with self.assertRaises(EditorError):export_mp3_final(self.r)
 def test_refuses_nonwav(self):
  self.d['output_path']=str(self.r/'other.mp3');self.save()
  with self.assertRaises(EditorError):export_mp3_final(self.r)
