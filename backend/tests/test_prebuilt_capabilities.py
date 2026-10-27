import unittest, tempfile
from pathlib import Path
from unittest import mock
from auk_reliability import core
from auk_reliability.core import EditorError, PREBUILT_CAPABILITIES, setup_runtime

class PrebuiltCapabilityTests(unittest.TestCase):
 def test_capability_set_is_sm75_and_sm89(self):
  # The checksum-pinned release archive embeds SM75+SM89 SASS; the guard must
  # accept exactly the GPUs the pinned bytes can serve (T4 and L4).
  self.assertEqual(PREBUILT_CAPABILITIES, frozenset({'7.5', '8.9'}))
 def test_unsupported_gpu_rejected_before_download(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(EditorError) as ctx:
    setup_runtime(Path(d), mode='t4_prebuilt', gpu={'compute_capability': '9.0'})
   self.assertEqual(ctx.exception.code, 'wrong_gpu')
 def test_l4_sm89_passes_the_guard(self):
  # A passing guard proceeds to the pinned-archive download; stub the download
  # with a sentinel so the test proves acceptance without any network access.
  sentinel = RuntimeError('download-would-start')
  with tempfile.TemporaryDirectory() as d:
   with mock.patch.object(core, 'download_file', side_effect=sentinel):
    with self.assertRaises(RuntimeError):
     setup_runtime(Path(d), mode='t4_prebuilt', gpu={'compute_capability': '8.9'})

if __name__ == '__main__':
 unittest.main()
