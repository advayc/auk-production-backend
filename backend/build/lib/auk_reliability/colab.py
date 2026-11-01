"""Bind the notebook's pinned audio.cpp transport; no hidden model substitutions."""
from pathlib import Path
import json, hashlib, subprocess, os, sys
from .core import LocalAuKServer, Limits, setup_asr, atomic_json, command, make_venv

def worker_from_notebook(editor, root, *, semantic_gate=None, max_attempts=3):
 from .worker import ReliabilityWorker
 from .qa import SemanticQAGate
 gate=semantic_gate or SemanticQAGate(transcriber=editor.asr)
 # Separate instance retains independent result folders. Close editor first to avoid two GPU owners.
 editor.close()
 transport=LocalAuKServer(editor.transport.binary,editor.transport.model_dir,Path(root)/'runtime',editor.limits,editor.transport.memory_saver)
 return ReliabilityWorker(transport,Path(root)/'requests',limits=editor.limits,semantic_gate=gate,
  runtime_profile={**editor.provenance,'simulation':False},max_attempts=max_attempts)

SPEAKER_TORCH_VERSION='2.6.0'
SPEAKER_NUMPY_VERSION='2.2.6'

def speaker_environment_name(version=None):
 version=version or sys.version_info
 if not (3,10) <= tuple(version[:2]) <= (3,13):
  raise RuntimeError('Speaker QA supports Python 3.10-3.13; disable it on other runtimes.')
 return f'venv-py{version[0]}{version[1]}-torch260'

SPEAKER_REVISION='0f99f2d0ebe89ac095bcc5903c4dd8f72b367286'
SPEAKER_SCRIPT=r'''
import os,sys,json,subprocess
os.environ['CUDA_VISIBLE_DEVICES']='-1'
os.environ['HF_HUB_OFFLINE']='1'
import torch
from speechbrain.inference.speaker import EncoderClassifier
model_dir,a,b,out=sys.argv[1:]
model=EncoderClassifier.from_hparams(source=model_dir,savedir=model_dir+'/runtime',run_opts={'device':'cpu'})
def load(path):
 r=subprocess.run(['ffmpeg','-v','error','-nostdin','-xerror','-i',path,'-ac','1','-ar','16000','-f','f32le','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45,check=True)
 import numpy as np
 data=np.frombuffer(r.stdout,dtype='<f4').copy()
 if not data.size or not np.isfinite(data).all():raise ValueError('invalid speaker QA input')
 return torch.from_numpy(data).unsqueeze(0)
with torch.no_grad():
 x=model.encode_batch(load(a),normalize=False);y=model.encode_batch(load(b),normalize=False)
 score=torch.nn.functional.cosine_similarity(x,y,dim=-1).item()
with open(out,'w') as f:json.dump({'score':score},f,allow_nan=False)
'''

def setup_speaker_qa(root, *, timeout=180):
 """CPU isolated QA with pinned primary dependencies and model commit. GPU inference not run here."""
 import tempfile
 root=Path(root);root.mkdir(parents=True,exist_ok=True);venv=root/speaker_environment_name();py=venv/'bin/python'
 py=make_venv(venv)
 lock=venv/'requirements.lock.txt'
 if not lock.is_file():
  command([str(py),'-m','pip','install','torch=='+SPEAKER_TORCH_VERSION,'torchaudio=='+SPEAKER_TORCH_VERSION,'--index-url','https://download.pytorch.org/whl/cpu'],timeout=900)
  command([str(py),'-m','pip','install','speechbrain==1.0.3','huggingface-hub==0.28.1','numpy=='+SPEAKER_NUMPY_VERSION],timeout=600)
  lock.write_text(command([str(py),'-m','pip','freeze'],timeout=30))
 elif lock.read_text()!=command([str(py),'-m','pip','freeze'],timeout=30):raise RuntimeError('Speaker QA environment changed; explicitly recreate it.')
 model=root/SPEAKER_REVISION
 command([str(py),'-c',"from huggingface_hub import snapshot_download; import sys; snapshot_download('speechbrain/spkrec-ecapa-voxceleb',revision=sys.argv[1],local_dir=sys.argv[2])",SPEAKER_REVISION,str(model)],timeout=600)
 # The model config uses upstream file URLs; rewrite only those exact references to the pinned local snapshot.
 yaml=model/'hyperparams.yaml';text=yaml.read_text()
 for name in ('embedding_model.ckpt','mean_var_norm_emb.ckpt','classifier.ckpt','label_encoder.txt'):
  text=text.replace('!ref <pretrained_path>/'+name,str((model/name).resolve()))
 yaml.write_text(text)
 script=root/'score_speaker.py';script.write_text(SPEAKER_SCRIPT)
 fingerprint=hashlib.sha256((lock.read_text()+SPEAKER_REVISION+SPEAKER_SCRIPT).encode()).hexdigest()
 atomic_json(root/'qa.lock.json',{'model_revision':SPEAKER_REVISION,'fingerprint':fingerprint,'environment':venv.name,'python':list(sys.version_info[:3]),
   'files':{str(p.relative_to(model)):hashlib.sha256(p.read_bytes()).hexdigest() for p in model.rglob('*') if p.is_file() and '.cache' not in p.parts}})
 def similarity(a,b):
  fd,name=tempfile.mkstemp(suffix='.json',dir=root);os.close(fd)
  try:
   command([str(py),str(script),str(model),str(a),str(b),name],timeout=timeout)
   return float(json.loads(Path(name).read_text())['score'])
  finally:Path(name).unlink(missing_ok=True)
 # Validate imports, pinned weights, FFmpeg and the scoring path before advertising availability.
 import wave, math, array
 with tempfile.TemporaryDirectory(dir=root) as smoke_dir:
  smoke=Path(smoke_dir)/'smoke.wav'
  samples=array.array('h',(int(3000*math.sin(i*2*math.pi*220/16000)) for i in range(16000)))
  if sys.byteorder != 'little': samples.byteswap()
  with wave.open(str(smoke),'wb') as w:
   w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(samples.tobytes())
  score=similarity(smoke,smoke)
  if not math.isfinite(score) or not -1 <= score <= 1.0001:
   raise RuntimeError('Speaker QA smoke score is invalid.')
 return similarity,fingerprint

def setup_optional_speaker_qa(root, *, enabled=True, timeout=180):
 """Never make unavailable identity checks look successful. Strict setup remains available."""
 if not enabled:
  return None,'unavailable',{'status':'disabled','reason':'disabled_by_configuration'}
 try:
  callback,fingerprint=setup_speaker_qa(root,timeout=timeout)
  return callback,fingerprint,{'status':'ready','model_revision':SPEAKER_REVISION}
 except Exception as exc:
  # Do not store subprocess stderr, paths, credentials or remote response text in provenance.
  return None,'unavailable',{'status':'unavailable','reason':getattr(exc,'code',type(exc).__name__),
    'next_step':'Check the isolated speaker-QA environment; identity-required requests remain unverified.'}
