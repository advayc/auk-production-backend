"""Standalone prepared-runtime entry point; never requires Colab notebook globals."""
import json, subprocess, sys, site, os
from pathlib import Path
from .core import Limits,gpu_details,setup_runtime,setup_models,setup_asr,LocalAuKServer
from .colab import setup_optional_speaker_qa
from .qa import SemanticQAGate
from .worker import ReliabilityWorker
from .acceptance import run_acceptance_suite
from .durable import Checkpoint

def run_config(config_path, *, resume=False):
 config=json.loads(Path(config_path).read_text())
 if config.get('run_generation') is not True:raise ValueError('Explicit run_generation=true required in config')
 if config.get('commercial_use') and config.get('commercial_license_confirmed') is not True:raise ValueError('Commercial clearance required')
 root=Path(config['work_dir']);root.mkdir(parents=True,exist_ok=True);gpu=gpu_details()
 if gpu['compute_capability']!='7.5':raise ValueError('This release targets T4 only')
 subprocess.run([sys.executable,'-m','pip','install','nvidia-cublas-cu12==12.8.4.1','nvidia-cuda-runtime-cu12==12.8.90','nvidia-cufft-cu12==11.3.3.83'],check=True)
 dirs=[str(Path(p)/'nvidia'/c/'lib') for p in site.getsitepackages()+[site.getusersitepackages()] for c in ('cublas','cuda_runtime','cufft') if (Path(p)/'nvidia'/c/'lib').is_dir()]
 os.environ['LD_LIBRARY_PATH']=':'.join(dirs+[os.environ.get('LD_LIBRARY_PATH','')])
 limits=Limits();binary,runtime=setup_runtime(root,mode='t4_prebuilt',gpu=gpu);models,model=setup_models(root,['base_f32','base_q8','flash_f16'])
 asr,af=setup_asr(root/'shared-qa',limits,config.get('language','en'))
 speaker,sf,setup=setup_optional_speaker_qa(root/'shared-speaker-qa',enabled=True)
 if speaker is None:raise ValueError('Speaker QA unavailable')
 profile={'runtime':runtime,'model':model,'gpu':gpu,'simulation':False,'asr_fingerprint':af,'speaker_fingerprint':sf,'speaker_setup':setup}
 if config.get('gpu_hourly_rate_usd') is not None:profile['gpu_hourly_rate_usd']=config['gpu_hourly_rate_usd']
 worker=ReliabilityWorker(LocalAuKServer(binary,models,root/'shared-runtime',limits,True),root/'shared-requests',semantic_gate=SemanticQAGate(asr,speaker),runtime_profile=profile)
 cp=Checkpoint(config['backup_dir'],{'backend':root,'dataset':Path(config['dataset_dir']),'runs':Path(config['runs_dir'])})
 cp.sync()
 try:return run_acceptance_suite(worker,config['manifest'],config['output_dir'],modes=('voice_editor','transcript_editor'),resume=resume,checkpoint=cp)
 finally:cp.sync();worker.close()
