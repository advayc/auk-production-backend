# PROBE-1 (2026-11-11): single-clip improvement probe for 'Why 2-Minute Podcast Clips
# Dominate Attention' through the PRODUCTION voice_enhancer path, seed 42, base_q8,
# repo @0107eed. Difference vs RB1: the FULL request folder (per-chunk dry/wet wavs,
# premaster, output, attempt records) is uploaded durably to Drive so the wet component
# can be inspected and reblended CPU-side without regeneration.
# Hypotheses under test (labels from agent analysis, NOT established): (a) soft function
# words in this clip show bottom-decile mel-energy retention in the RB1 output;
# (b) two candidate mechanisms - wet drops the word vs wet carries a cleaner quieter
# version - are indistinguishable without the wet track, which this probe preserves.
import base64, hashlib, io, json, os, site, subprocess, sys, time
from pathlib import Path

print('PROBE_START', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), flush=True)
RBROOT = Path('/content/rprobe'); RBROOT.mkdir(exist_ok=True)
REPO = RBROOT / 'repo'
if not (REPO / '.git').exists():
    subprocess.run(['git','clone','--quiet','https://github.com/advayc/auk-production-backend', str(REPO)], check=True)
subprocess.run(['git','-C',str(REPO),'checkout','--quiet','0107eed'], check=True)
sys.path.insert(0, str(REPO / 'backend'))
from auk_reliability.core import (Limits, gpu_details, setup_runtime, setup_models,
                                  LocalAuKServer, setup_asr, probe_audio)
from auk_reliability.colab import setup_optional_speaker_qa
from auk_reliability.qa import SemanticQAGate
from auk_reliability.worker import ReliabilityWorker

GPU = gpu_details(); print('GPU', GPU, flush=True)
assert GPU['compute_capability'] == '7.5', 'This prebuilt needs a T4 runtime.'
subprocess.run([sys.executable,'-m','pip','install','--quiet',
    'nvidia-cublas-cu12==12.8.4.1','nvidia-cuda-runtime-cu12==12.8.90','nvidia-cufft-cu12==11.3.3.83'], check=True)
libdirs = []
for root in set(site.getsitepackages() + [site.getusersitepackages()]):
    for comp in ('cublas','cuda_runtime','cufft'):
        p = Path(root)/'nvidia'/comp/'lib'
        if p.is_dir(): libdirs.append(str(p))
os.environ['LD_LIBRARY_PATH'] = ':'.join(libdirs + [os.environ.get('LD_LIBRARY_PATH','')])

LIMITS = Limits()
BINARY, RUNTIME_LOCK = setup_runtime(RBROOT, mode='t4_prebuilt', gpu=GPU)
MODEL_DIR, MODEL_LOCK = setup_models(RBROOT, ['base_q8'])
print('PROBE_SETUP_OK', flush=True)

from google.colab import auth as _colab_auth
_colab_auth.authenticate_user()
import google.auth as _gauth
from googleapiclient.discovery import build as _gbuild
from googleapiclient.http import MediaFileUpload as _MFU
_creds, _ = _gauth.default(scopes=['https://www.googleapis.com/auth/drive'])
_drv = _gbuild('drive','v3',credentials=_creds,cache_discovery=False)

ZIP_ID = '1Wn4LSlhGslf9ERUtUC4_OqN4i2VLlzfb'
zpath = RBROOT / 'inputs.zip'
with open(zpath, 'wb') as f:
    f.write(_drv.files().get_media(fileId=ZIP_ID).execute())
import zipfile
SRC = RBROOT / 'inputs'
with zipfile.ZipFile(zpath) as z:
    names = [n for n in z.namelist() if 'Why 2-Minute' in n]
    assert len(names) == 1, names
    z.extract(names[0], SRC)
src = next(SRC.rglob('*.mp3'))
print('PROBE_INPUT', src.name, flush=True)

PARENT = '1091Wijeibp9Y7jGnxJNV8CknHmshjRpy'  # auk-realinput bench folder
_f = _drv.files().create(body={'name':'auk-improve-probe-2026-11-11',
    'mimeType':'application/vnd.google-apps.folder','parents':[PARENT]}, fields='id').execute()
FOLDER = _f['id']
print('PROBE_FOLDER', FOLDER, flush=True)
def upload(local, name=None):
    r = _drv.files().create(body={'name': name or Path(local).name, 'parents':[FOLDER]},
        media_body=_MFU(str(local)), fields='id').execute()
    print('PROBE_UPLOAD', name or Path(local).name, r['id'], flush=True)

shared_asr, asr_fp = setup_asr(RBROOT / 'shared-qa', LIMITS, 'en')
speaker_cb, spk_fp, spk_setup = setup_optional_speaker_qa(RBROOT / 'shared-speaker-qa', enabled=True)
transport = LocalAuKServer(BINARY, MODEL_DIR, RBROOT / 'shared-runtime', LIMITS, True)
runtime_profile = {'runtime': RUNTIME_LOCK, 'model': MODEL_LOCK, 'gpu': GPU, 'simulation': False,
                   'asr_fingerprint': asr_fp, 'speaker_fingerprint': spk_fp,
                   'benchmark': 'improve-probe-2026-11-11', 'generator_profile': 'base_q8'}
worker = ReliabilityWorker(transport, RBROOT / 'requests',
    semantic_gate=SemanticQAGate(shared_asr, speaker_cb), runtime_profile=runtime_profile)
print('PROBE_WORKER_OK', flush=True)

obs = shared_asr(src)
stext = obs.get('text','') if isinstance(obs, dict) else str(obs)
t0 = time.monotonic()
res = worker.edit_audio(src, 'voice_enhancer', 'enhance',
    {'rights_confirmed': True, 'source_text': stext, 'seed': 42, 'profile': 'base_q8'})
rdir = Path(res.request_dir)
print('PROBE_REQUEST_DIR', rdir, 'latency', round(time.monotonic()-t0,1), flush=True)

# durable preservation: every artifact a controlled reblend could need
for p in sorted(rdir.rglob('*')):
    if p.is_file():
        upload(p, p.name if p.parent == rdir else f'{p.parent.name}--{p.name}')
rec = json.loads((rdir / 'attempts.json').read_text())[0]
print('PROBE_ATTEMPT', json.dumps({'technical_success': rec['technical_success'],
    'decision': rec.get('decision'), 'qa_pass': rec.get('automatic_qa_pass'),
    'failure_reason': rec.get('failure_reason')}), flush=True)
print('PROBE_DONE folder', FOLDER, flush=True)
