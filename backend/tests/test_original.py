from auk_reliability.core import *
# @title Define the self-test suite (no GPU or model calls)
import io
import unittest
import wave
from unittest import mock


def make_test_wav(path, seconds=1.0, channels=1, amplitude=.2, rate=24000):
    frames = int(rate * seconds)
    samples = array.array('h')
    for i in range(frames):
        value = int(amplitude * 32767 * math.sin(2*math.pi*220*i/rate))
        samples.extend([value] * channels)
    if sys.byteorder != 'little': samples.byteswap()
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(channels); f.setsampwidth(2); f.setframerate(rate); f.writeframes(samples.tobytes())
    return Path(path)


class FakeTransport:
    calls = 0
    fail = False
    def __init__(self, *args): self.has_run=False
    def stop(self): self.has_run=False
    def run(self, profile, input_path, plan):
        type(self).calls += 1
        if type(self).fail: raise EditorError('inference_timeout', 'Simulated timeout')
        # Fixtures test plumbing, not voice editing. Never used by the real UI.
        raw = Path(input_path).read_bytes()
        result = {'audio': base64.b64encode(raw).decode(), 'timing': {'fixture': True}}
        timing = {'inference_seconds': .1, 'server_start_seconds': 0,
                  'first_request_after_start': not self.has_run, 'memory_saver': True}
        self.has_run=True
        return result, timing


class PlannerTests(unittest.TestCase):
    def setUp(self): self.limits=Limits()
    def test_emotion_preserves_duration(self):
        p=build_plan(EditSpec(operation='emotion'),7,self.limits)
        self.assertEqual(p['target_seconds'],7); self.assertTrue(p['preserve_content'])
    def test_speed_sets_duration(self):
        p=build_plan(EditSpec(operation='speed',speed=1.5),9,self.limits)
        self.assertEqual(p['target_seconds'],6)
    def test_rounding_to_20ms(self):
        self.assertEqual(build_plan(EditSpec(instruction='Test',target_seconds=1.001),1,self.limits)['target_seconds'],1.02)
    def test_unknown_operation(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='whatever'),1,self.limits)
    def test_empty_custom(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(),1,self.limits)
    def test_invalid_emotion(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='emotion',emotion='n/a'),1,self.limits)
    def test_duration_budget(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='speed',speed=.75),15,self.limits)
    def test_nan_duration(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(instruction='Test'),float('nan'),self.limits)
    def test_invalid_seed(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(instruction='Test',seed=-1),1,self.limits)
    def test_boolean_seed(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(instruction='Test',seed=True),1,self.limits)
    def test_empty_voice_description(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='voice'),1,self.limits)
    def test_word_replacement(self):
        p=build_plan(EditSpec(operation='replace_words',source_transcript='Meet Tuesday.',old_words='Tuesday',new_words='Thursday'),2,self.limits)
        self.assertEqual(p['expected_transcript'],'Meet Thursday.')
    def test_ambiguous_word_replacement(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='replace_words',source_transcript='yes yes',old_words='yes',new_words='no'),2,self.limits)
    def test_replacement_needs_transcript(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='replace_words',old_words='yes',new_words='no'),2,self.limits)
    def test_conflicting_expected_text(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='emotion',source_transcript='Hello',expected_transcript='Goodbye'),2,self.limits)
    def test_nul_instruction(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(instruction='a\0b'),1,self.limits)
    def test_text_exact_match(self):
        self.assertEqual(compare_transcript('HELLO, world!', 'Hello world')['status'],'no_text_discrepancy_detected')
    def test_text_mismatch(self):
        self.assertEqual(compare_transcript('Tuesday', 'Thursday')['status'],'review_required')
    def test_cjk_metric(self):
        self.assertEqual(compare_transcript('你好世界', '你好')['metric'],'character_error_rate')
    def test_no_empty_expected_text(self):
        with self.assertRaises(EditorError): compare_transcript('!!!', 'Hello')
    def test_speed_duration_conflict(self):
        with self.assertRaises(EditorError): build_plan(EditSpec(operation='speed',speed=2,target_seconds=4),4,self.limits)
    def test_immutable_runtime_pin(self):
        self.assertEqual(len(RUNTIME_SHA256),64); self.assertEqual(len(MODEL_REVISION),40)


class MediaAndJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.wav=make_test_wav(self.root/'voice.wav')
        self.limits=Limits(); self.editors=[]
        FakeTransport.calls=0; FakeTransport.fail=False
    def tearDown(self):
        for e in self.editors: e.close()
        self.tmp.cleanup()
    def editor(self, **kwargs):
        e=VoiceEditor(self.root/'worker', self.root/'binary', self.root/'models',
                      memory_saver=True,provenance={'test':'fixture'},transport_factory=FakeTransport,**kwargs)
        self.editors.append(e); return e
    def test_decode_valid_audio(self):
        data=self.wav.read_bytes()
        self.assertEqual(decode_response({'audio':base64.b64encode(data).decode()},self.limits),data)
    def test_missing_audio_rejected(self):
        with self.assertRaises(EditorError): decode_response({},self.limits)
    def test_bad_base64_rejected(self):
        with self.assertRaises(EditorError): decode_response({'audio':'$$$'},self.limits)
    def test_non_wav_rejected(self):
        with self.assertRaises(EditorError): decode_response({'audio':base64.b64encode(b'x'*100).decode()},self.limits)
    def test_zero_byte_input(self):
        p=self.root/'empty.wav';p.touch()
        with self.assertRaises(EditorError): probe_audio(p,self.limits)
    def test_corrupt_input(self):
        p=self.root/'bad.wav';p.write_bytes(b'not audio')
        with self.assertRaises(EditorError): probe_audio(p,self.limits)
    def test_silent_input(self):
        p=make_test_wav(self.root/'silence.wav',amplitude=0)
        with self.assertRaises(EditorError): prepare_audio(p,self.root/'prepared.wav',0,None,self.limits)
    def test_stereo_downmix(self):
        p=make_test_wav(self.root/'stereo.wav',channels=2)
        result=prepare_audio(p,self.root/'prepared.wav',0,None,self.limits)
        self.assertTrue(any('downmixed' in s for s in result['warnings']))
    def test_partial_clip_explicit_warning(self):
        result=prepare_audio(self.wav,self.root/'prepared.wav',.25,.8,self.limits)
        self.assertTrue(any('NOT spliced' in s for s in result['warnings']))
    def test_oversized_duration_not_silently_trimmed(self):
        small=dataclasses.replace(self.limits,max_input_seconds=.6)
        with self.assertRaises(EditorError): prepare_audio(self.wav,self.root/'prepared.wav',0,None,small)
    def test_wrong_channel(self):
        with self.assertRaises(EditorError): prepare_audio(self.wav,self.root/'prepared.wav',0,None,self.limits,'right')
    def test_output_checks(self):
        self.assertEqual(validate_output(self.wav,1,self.limits)['technical_checks'],'passed')
    def test_wrong_duration(self):
        with self.assertRaises(EditorError): validate_output(self.wav,2,self.limits)
    def test_wrong_sample_rate(self):
        p=make_test_wav(self.root/'rate.wav',rate=16000)
        with self.assertRaises(EditorError): validate_output(p,1,self.limits)
    def test_generated_not_approved(self):
        e=self.editor(); r=e.edit(self.wav,EditSpec(operation='emotion'),rights_confirmed=True)
        self.assertEqual(r['status'],'generated'); self.assertEqual(r['human_review'],'pending')
        self.assertTrue(Path(r['output_path']).is_file())
    def test_idempotent_repeat(self):
        e=self.editor(); spec=EditSpec(operation='emotion')
        a=e.edit(self.wav,spec,rights_confirmed=True); b=e.edit(self.wav,spec,rights_confirmed=True)
        self.assertEqual(a['job_id'],b['job_id']); self.assertTrue(b['cache_hit']);self.assertEqual(FakeTransport.calls,1)
    def test_cache_corruption(self):
        e=self.editor();spec=EditSpec(operation='emotion');a=e.edit(self.wav,spec,rights_confirmed=True)
        Path(a['output_path']).write_bytes(b'changed')
        with self.assertRaises(EditorError):e.edit(self.wav,spec,rights_confirmed=True)
    def test_rights_required(self):
        with self.assertRaises(EditorError): self.editor().edit(self.wav,EditSpec(operation='emotion'))
    def test_commercial_gate(self):
        with self.assertRaises(EditorError): self.editor(commercial=True)
    def test_exclusive_worker_lock(self):
        e=self.editor()
        with self.assertRaises(EditorError):self.editor()
    def test_failed_requires_explicit_retry(self):
        e=self.editor(); spec=EditSpec(operation='emotion');FakeTransport.fail=True
        with self.assertRaises(EditorError):e.edit(self.wav,spec,rights_confirmed=True)
        FakeTransport.fail=False
        with self.assertRaises(EditorError):e.edit(self.wav,spec,rights_confirmed=True)
        r=e.edit(self.wav,spec,rights_confirmed=True,retry_failed=True)
        self.assertEqual(r['attempts'],2);self.assertEqual(r['status'],'generated')
    def test_no_output_after_failure(self):
        e=self.editor();FakeTransport.fail=True
        with self.assertRaises(EditorError): e.edit(self.wav,EditSpec(operation='emotion'),rights_confirmed=True)
        self.assertFalse(list((e.root/'jobs').rglob('output.wav')))
    def test_word_edit_without_qa_blocked(self):
        e=self.editor()
        spec=EditSpec(operation='replace_words',source_transcript='Say yes',old_words='yes',new_words='no')
        with self.assertRaises(EditorError):e.edit(self.wav,spec,rights_confirmed=True)
    def test_approval_explicit(self):
        e=self.editor();r=e.edit(self.wav,EditSpec(operation='emotion'),rights_confirmed=True)
        m=e.review(r['job_id'],approved=True,notes='Test fixture only')
        self.assertEqual(m['human_review'],'approved')
    def test_review_path_traversal(self):
        e=self.editor()
        with self.assertRaises(EditorError):e.review('../bad',approved=True)
    def test_asr_discrepancy_flags_review(self):
        counter=[0]
        def asr(path):
            counter[0]+=1
            return {'text':'Hello world' if counter[0]==1 else 'Goodbye world'}
        e=self.editor(asr=asr,asr_fingerprint='test')
        r=e.edit(self.wav,EditSpec(operation='emotion'),rights_confirmed=True)
        self.assertEqual(r['semantic_validation'],'review_required')
    def test_stale_job_recovery(self):
        e=self.editor();jid=uuid.uuid4().hex
        e.db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(jid,'stale','running',utc_now()));e.db.commit();e.close()
        reopened=self.editor()
        row=reopened.db.execute('SELECT status FROM jobs WHERE job_id=?',(jid,)).fetchone()
        self.assertEqual(row[0],'interrupted')
    def test_sql_injection_like_prompt_is_data(self):
        e=self.editor();r=e.edit(self.wav,EditSpec(instruction="'; DROP TABLE jobs; --"),rights_confirmed=True)
        self.assertEqual(e.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
    def test_job_manifests_do_not_store_base64_response(self):
        e=self.editor();r=e.edit(self.wav,EditSpec(operation='emotion'),rights_confirmed=True)
        m=json.loads((Path(r['job_dir'])/'manifest.json').read_text())
        self.assertNotIn('audio',m);self.assertNotIn(base64.b64encode(self.wav.read_bytes()).decode(),json.dumps(m))


class ArtifactTests(unittest.TestCase):
    def test_parse_lfs_pointer(self):
        digest='a'*64
        self.assertEqual(parse_lfs_pointer(f'version https://git-lfs.github.com/spec/v1\noid sha256:{digest}\nsize 123\n'),(digest,123))
    def test_bad_pointer(self):
        with self.assertRaises(EditorError):parse_lfs_pointer('some html error')
    def test_archive_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'archive.tar.gz'
            with tarfile.open(p,'w:gz') as t:
                m=tarfile.TarInfo('../escape');m.size=1;t.addfile(m,io.BytesIO(b'x'))
            with self.assertRaises(EditorError):safe_extract(p,root/'out')
            self.assertFalse((root/'escape').exists())
    def test_archive_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'archive.tar.gz'
            with tarfile.open(p,'w:gz') as t:
                m=tarfile.TarInfo('link');m.type=tarfile.SYMTYPE;m.linkname='/etc';t.addfile(m)
            with self.assertRaises(EditorError):safe_extract(p,root/'out')
    def test_safe_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'archive.tar.gz'
            with tarfile.open(p,'w:gz') as t:
                m=tarfile.TarInfo('file');m.size=1;t.addfile(m,io.BytesIO(b'x'))
            safe_extract(p,root/'out');self.assertEqual((root/'out'/'file').read_bytes(),b'x')
    def test_canonical_hash_stable(self):
        self.assertEqual(canonical_hash({'b':2,'a':1}),canonical_hash({'a':1,'b':2}))
    def test_local_server_hard_stop(self):
        p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        try:
            ticks=process_start_ticks(p.pid);kill_owned_group(p.pid,ticks);p.wait(timeout=6)
            self.assertIsNotNone(p.returncode)
        finally:
            if p.poll() is None:p.kill();p.wait()
    def test_pid_reuse_guard(self):
        p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
        try:
            kill_owned_group(p.pid,'not-the-start-time');self.assertIsNone(p.poll())
        finally:p.kill();p.wait()


FAKE_HTTP_SCRIPT = r'''#!/usr/bin/env python3
import argparse,base64,json,time
from http.server import BaseHTTPRequestHandler,HTTPServer
p=argparse.ArgumentParser();p.add_argument('--config');p.add_argument('--no-ui',action='store_true');a=p.parse_args()
c=json.load(open(a.config));model_id=c['models'][0]['id']
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def reply(self,obj,status=200):
  data=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):self.reply({'data':[{'id':model_id}]} if self.path=='/v1/models' else {'status':'ok'})
 def do_POST(self):
  r=json.loads(self.rfile.read(int(self.headers['Content-Length'])))['request']
  if r['text']=='HANG':time.sleep(60)
  if r['text']=='ERROR':self.reply({'error':'out of memory'},500);return
  if r['text']=='BAD':self.reply({'foo':'bar'});return
  self.reply({'audio':base64.b64encode(open(r['audio'],'rb').read()).decode()})
HTTPServer((c['host'],c['port']),H).serve_forever()
'''

class TransportIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.binary=self.root/'server';self.binary.write_text(FAKE_HTTP_SCRIPT);self.binary.chmod(0o755)
        self.models=self.root/'models';self.models.mkdir()
        for name in (PROFILE_FILES['base_f32'][1],*SHARED_FILES,*SIDECARS):
            p=self.models/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
        self.wav=make_test_wav(self.root/'voice.wav')
        self.server=LocalAuKServer(self.binary,self.models,self.root/'runtime',
                                  dataclasses.replace(Limits(),startup_timeout=5,inference_timeout=.8),True)
    def tearDown(self):self.server.stop();self.tmp.cleanup()
    def plan(self,instruction='ok'):
        return {'instruction':instruction,'seed':42,'target_seconds':1}
    def test_real_http_request_shape(self):
        r,t=self.server.run('base_f32',self.wav,self.plan())
        self.assertEqual(decode_response(r,Limits()),self.wav.read_bytes())
        self.assertTrue(t['first_request_after_start'])
    def test_warm_request_marker(self):
        self.server.run('base_f32',self.wav,self.plan())
        r,t=self.server.run('base_f32',self.wav,self.plan())
        self.assertFalse(t['first_request_after_start'])
    def test_http_oom_stops_process(self):
        with self.assertRaises(EditorError) as cm:self.server.run('base_f32',self.wav,self.plan('ERROR'))
        self.assertEqual(cm.exception.code,'out_of_memory');self.assertIsNone(self.server.process)
    def test_watchdog_kills_hanging_http_server(self):
        with self.assertRaises(EditorError):self.server.run('base_f32',self.wav,self.plan('HANG'))
        self.assertIsNone(self.server.process);self.assertFalse(self.server.owner_file.exists())
    def test_bad_payload_rejected_after_http_success(self):
        r,_=self.server.run('base_f32',self.wav,self.plan('BAD'))
        with self.assertRaises(EditorError):decode_response(r,Limits())


def run_self_tests():
    suite=unittest.TestSuite()
    for cls in (PlannerTests,MediaAndJobTests,ArtifactTests,TransportIntegrationTests):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful(): raise RuntimeError('Self-tests failed. Do not run inference until fixed.')
    return {'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'scope':'CPU media processing + synthetic/mocked inference plumbing. No AuK or ASR inference.'}
