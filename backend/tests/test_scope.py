import json,tempfile,unittest
from pathlib import Path
from unittest import mock
from auk_reliability.policy import ACTIVE_MODES, OPERATIONS, selected_modes
from auk_reliability.dataset import validate_dataset
from auk_reliability.acceptance import benchmark_profiles,recommend_profiles,run_acceptance_suite,configure_acceptance_suite
import test_backend

class ScopeTests(test_backend.BackendTests):
 # Reuse fixture setup without inheriting test cases twice.
 def manifest(self):
  labels={k:'fixture' for k in ['voice_id','accent','microphone','noise','reverb','speaking_speed','duration_bucket','language']};labels['format']='wav'
  from auk_reliability.core import sha256_file
  d={'schema_version':1,'clips':[{'id':'one','audio_path':str(self.source),'sha256':sha256_file(self.source),
    'rights_verified':True,'license':'synthetic unittest only','provenance':'test sine fixture','transcript_verified':True,
    'transcript':'hello world','split':'development','labels':labels}, {'id':'external','audio_path':'missing-enhancer.wav'}],
    'requests':[{'id':'active','clip_id':'one','mode':'voice_editor','operation':'emotion','parameters':self.p},
    {'id':'other','clip_id':'external','mode':'voice_enhancer','operation':'denoise','parameters':{}}]}
  p=self.root/'manifest.json';p.write_text(json.dumps(d));return p
 def test_defaults_exclude_other_owner_and_their_sources(self):
  a=validate_dataset(self.manifest(),acceptance=False)
  self.assertTrue(a['valid']);self.assertEqual(a['request_count'],1);self.assertEqual(a['distinct_sources'],1)
  self.assertEqual(a['excluded_request_count'],1);self.assertEqual(a['scope_modes'],list(ACTIVE_MODES))
 def test_explicit_enhancer_audit_still_supported_and_validated(self):
  a=validate_dataset(self.manifest(),acceptance=False,modes=['voice_enhancer'])
  self.assertFalse(a['valid']);self.assertEqual(a['request_count'],1)
 def test_acceptance_requires_active_ops_and_1000_active_requests(self):
  a=validate_dataset(self.manifest())
  errors=str(a['errors']);self.assertIn('1000',errors);self.assertIn('transcript_editor',errors)
  self.assertNotIn("('voice_enhancer',",errors)
 def test_default_suite_and_report_scope(self):
  configure_acceptance_suite(self.worker,self.manifest(),self.root/'scoped-suite')
  r=run_acceptance_suite(acceptance=False)
  self.assertEqual(r['overall']['request_count'],1);self.assertEqual(r['excluded_request_count'],1)
  self.assertEqual(list(r['by_operation']),['voice_editor/emotion'])
  self.assertIn('Voice Enhancer: out of scope', (self.root/'scoped-suite/REPORT.md').read_text())
 def test_benchmark_recommendations_have_eight_ops_and_no_enhancer_calls(self):
  r=benchmark_profiles(self.worker,self.manifest(),self.root/'bench',per_operation_limit=1)
  self.assertEqual(len(r['rows']),3);self.assertTrue(all(p['mode']=='voice_editor' for _,p in self.adapter.calls))
  self.assertEqual(len(recommend_profiles(r)),8)
  self.assertEqual(len(recommend_profiles(r,modes=tuple(OPERATIONS))),11)
 def test_invalid_scope_or_unknown_manifest_mode_rejected(self):
  for m in [[],['unknown'],['voice_editor','voice_editor'],'voice_editor']:
   with self.assertRaises(ValueError):selected_modes(m)
  p=self.manifest();d=json.loads(p.read_text());d['requests'][1]['mode']='unknown';p.write_text(json.dumps(d))
  with self.assertRaises(ValueError):validate_dataset(p,acceptance=False)

# Only the new scope regressions, plus the original suite separately.
for name in list(ScopeTests.__dict__):
 pass
for name in dir(test_backend.BackendTests):
 if name.startswith('test_') and name not in ScopeTests.__dict__:setattr(ScopeTests,name,None)
