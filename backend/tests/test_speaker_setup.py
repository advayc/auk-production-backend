import unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from auk_reliability import colab
from auk_reliability.qa import SemanticQAGate
from auk_reliability.core import EditorError
class SpeakerSetupTests(unittest.TestCase):
 def test_python313_environment(self):
  self.assertEqual(colab.speaker_environment_name((3,13)), 'venv-py313-torch260')
 def test_unsupported_python(self):
  with self.assertRaises(RuntimeError): colab.speaker_environment_name((3,14))
 def test_matching_cpu_versions(self):
  self.assertEqual(colab.SPEAKER_TORCH_VERSION,'2.6.0')
  self.assertEqual(colab.SPEAKER_NUMPY_VERSION,'2.2.6')
 def test_disabled_no_install(self):
  with patch.object(colab,'setup_speaker_qa') as setup:
   cb,fp,status=colab.setup_optional_speaker_qa('/unused',enabled=False)
  setup.assert_not_called();self.assertIsNone(cb);self.assertEqual(fp,'unavailable');self.assertEqual(status['status'],'disabled')
 def test_install_failure_degrades(self):
  with patch.object(colab,'setup_speaker_qa',side_effect=EditorError('process_failed','private stderr')):
   cb,fp,status=colab.setup_optional_speaker_qa('/unused')
  self.assertIsNone(cb);self.assertEqual(fp,'unavailable');self.assertEqual(status['reason'],'process_failed');self.assertNotIn('private stderr',str(status))
 def test_runtime_failure_degrades(self):
  with patch.object(colab,'setup_speaker_qa',side_effect=RuntimeError('failed')):
   self.assertEqual(colab.setup_optional_speaker_qa('/unused')[2]['status'],'unavailable')
 def test_ready(self):
  cb=lambda a,b:.9
  with patch.object(colab,'setup_speaker_qa',return_value=(cb,'fingerprint')):
   self.assertEqual(colab.setup_optional_speaker_qa('/unused'),(cb,'fingerprint',{'status':'ready','model_revision':colab.SPEAKER_REVISION}))
 def test_missing_identity_is_not_a_pass(self):
  r=SemanticQAGate(lambda p:'hello').check('source','output',{'expected_transcript':'hello','identity_required':True})
  self.assertFalse(r['automatic_pass']);self.assertIn('speaker_qa_unavailable',r['unverified'])
