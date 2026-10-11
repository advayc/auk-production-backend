from __future__ import annotations
import dataclasses, time, uuid, threading, math, wave, fcntl
from pathlib import Path
from .core import (Limits, EditorError, WallClockAbort, LocalAuKServer, atomic_json, atomic_bytes, sha256_file,
 scoped_limits, probe_audio, prepare_audio, validate_output, decode_response, command, utc_now)
from .policy import plan_request, RETRYABLE, PROFILES
from .qa import SemanticQAGate
from .segment import normalize_recording, verify_alignment, splice
from .transplant import insert_transplant, localized_transplant
from .diagnostics import outside_interval_pcm_exact, classify_transcript_disagreement
from .seam import seam_report

@dataclasses.dataclass
class Result:
 request_id: str
 outcome: str
 technical_success: bool
 automatic_qa_pass: bool
 semantic_success: bool | None
 output_path: str | None
 reason: str | None
 profile: str
 latency_seconds: float
 attempts: list
 request_dir: str

class ReliabilityWorker:
 """Single-worker backend with bounded retries and isolated request artifacts."""
 def __init__(self, adapter, root, *, limits=Limits(), semantic_gate=None, runtime_profile=None, max_attempts=3):
  if max_attempts not in (1,2,3): raise ValueError('max_attempts must be 1-3')
  self.adapter=adapter;self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
  self.limits=limits;self.gate=semantic_gate or SemanticQAGate();self.runtime_profile=runtime_profile or {}
  self.max_attempts=max_attempts;self.lock=threading.Lock();self.deadline=None
  self.lockfile=(self.root/'.worker.lock').open('a+')
  try:fcntl.flock(self.lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError as exc:
   self.lockfile.close();raise EditorError('worker_busy','Another process owns this backend root.') from exc
 def set_deadline(self, budget_seconds):
  if budget_seconds is None:self.deadline=None;return
  if not isinstance(budget_seconds,(int,float)) or not math.isfinite(budget_seconds) or budget_seconds<=0:
   raise ValueError('wall_clock_budget_seconds must be a positive finite number of seconds.')
  self.deadline=time.monotonic()+budget_seconds
 def edit_audio(self, input_audio, mode, operation, parameters):
  if not self.lock.acquire(False): raise EditorError('worker_busy','One edit already runs in this worker.')
  try: return self._edit(input_audio,mode,operation,parameters)
  finally:self.lock.release()
 def _edit(self, input_audio, mode, operation, p):
  # v033: evidence-bounded scope for nonverbal_remove (see core.scoped_limits); all
  # other operations keep the default conservative caps. Scoped limits flow through
  # preparation, planning and output validation for this request only.
  limits=scoped_limits(self.limits, operation)
  p=dict(p);profile=p.get('profile','base_f32')
  if profile not in PROFILES: raise EditorError('unknown_profile','Use base_f32, base_q8 or flash_f16.')
  source=Path(input_audio).resolve();meta=probe_audio(source,limits);digest=sha256_file(source)
  start=p.get('segment_start_seconds',0) if mode=='transcript_editor' else p.get('start_seconds',0)
  end=p.get('segment_end_seconds') if mode=='transcript_editor' else p.get('end_seconds')
  whole_clip=mode=='transcript_editor' and p.get('segment_scope')=='whole_clip'
  if whole_clip:
   if float(start)!=0 or (end is not None and abs(float(end)-meta['duration_seconds'])>.02):
    raise EditorError('whole_clip_interval','Whole-clip scope must use start 0 and the full clip duration.')
   end=meta['duration_seconds']
  if mode=='transcript_editor' and end is None: raise EditorError('missing_interval','Transcript editing requires explicit segment_start/end_seconds.')
  localized=mode=='transcript_editor' and not whole_clip
  if localized:
   src_txt=p.get('source_text','');seg_txt=p.get('segment_text','')
   if not seg_txt or src_txt.count(seg_txt)!=1:
    raise EditorError('localized_segment_not_unique','Localized edits need segment_text to occur exactly once in source_text.')
   full_edited=src_txt.replace(seg_txt,p.get('edited_segment_text',''),1)
  rid=uuid.uuid4().hex;folder=self.root/rid;folder.mkdir()
  request_started=time.monotonic();attempts=[];selected=None;technical=False;qa_pass=False;reason=None
  atomic_json(folder/'request.json',{'id':rid,'mode':mode,'operation':operation,'parameters':p,
    'source_sha256':digest,'source_path':str(source),'runtime_profile':self.runtime_profile,'created_at':utc_now()})
  prepared=folder/'input.wav'
  try:
   prep=prepare_audio(source,prepared,start,end,limits)
   plan=plan_request(mode,operation,p,prep['signal']['duration_seconds'],limits)
   if sha256_file(source)!=digest:raise EditorError('source_changed','Source changed during preparation.')
   if mode=='transcript_editor':verify_alignment(prepared,p,self.gate.transcriber)
  except Exception as exc:
   atomic_json(folder/'preflight_failure.json',{'reason':getattr(exc,'code',type(exc).__name__),'message':str(exc)})
   exc.request_dir=str(folder)
   raise
  full=folder/'normalized-source.wav'
  if mode=='transcript_editor':full_duration=normalize_recording(source,full,limits)
  if localized:
   # Localized edits generate from the full clip (speaker context intact) and
   # transplant the changed phrase back into the verified interval. The old
   # standalone-segment generation lost speaker identity (A/B 2026-10-17).
   plan_full=plan_request(mode,operation,{**p,'segment_scope':'whole_clip','segment_text':src_txt,
    'edited_segment_text':full_edited},full_duration,limits)
   gen_input=full;active_plan=plan_full
  else:
   gen_input=prepared;active_plan=plan
  for number in range(1,self.max_attempts+1):
   if self.deadline is not None and time.monotonic()>=self.deadline:
    raise WallClockAbort(f'Wall-clock budget exhausted before attempt {number} of request {rid}.')
   if hasattr(self.adapter,'deadline'):self.adapter.deadline=self.deadline
   ad=folder/f'attempt-{number:02d}';ad.mkdir();began=time.monotonic()
   active_plan['seed']=(p.get('seed',42)+number-1)%(2**31)
   record={'attempt':number,'seed':plan['seed'],'model_profile':profile,'runtime_profile':self.runtime_profile,
      'started_at':utc_now(),'technical_success':False,'automatic_qa_pass':False,'failure_reason':None,
      'artifact_paths':[],'plan':dict(plan),'selected':False}
   raw=ad/'raw.wav';out=ad/'output.wav'
   try:
    response,timing=self.adapter.run(profile,gen_input,active_plan);record['model_timing']=timing
    atomic_bytes(raw,decode_response(response,self.limits));record['artifact_paths'].append(str(raw))
    checks=validate_output(raw,active_plan['target_seconds'],limits)
    if checks['signal']['near_full_scale_fraction']>.005:raise EditorError('clipped_output','Clipping exceeds application QA threshold.')
    if checks['signal']['rms_dbfs']< -55:raise EditorError('quiet_output','Output is below application audibility threshold.')
    command(['ffmpeg','-v','error','-nostdin','-xerror','-i',str(raw),'-c:a','pcm_s16le','-y',str(out)],timeout=self.limits.ffmpeg_timeout)
    validate_output(out,active_plan['target_seconds'],limits);record['artifact_paths'].append(str(out))
    if mode=='transcript_editor' and whole_clip:
     final=out;record['splice']={'skipped':'whole_clip scope: the output replaces the entire clip; unchanged-region identity is not applicable'}
    elif mode=='transcript_editor':
     final=ad/'spliced.wav'
     record['splice']=localized_transplant(full,out,self.gate.transcriber,float(start),float(end),src_txt,full_edited,final)
     record['artifact_paths'].append(str(final))
     try:
      _seam_bounds=record['splice'].get('source_cut_seconds',[float(start),float(end)])
      record['seam']=seam_report(final,_seam_bounds)
     except Exception as seam_exc:record['seam_error']=getattr(seam_exc,'code',type(seam_exc).__name__)
    else:final=out
    record['technical_success']=True;technical=True
    if localized:
     qa=self.gate.check(full,final,active_plan);record['qa']=qa
    else:
     qa=self.gate.check(prepared,out,plan);record['qa']=qa
    qa_pass=qa['automatic_pass'];record['automatic_qa_pass']=qa_pass
    if qa_pass:selected=str(final);record['selected']=True;reason=None
    else:
     reason='qa_unverified' if qa['unverified'] else 'qa_failed';record['failure_reason']=reason
     if (mode=='transcript_editor' and operation=='insert' and self.gate.transcriber is not None
         and qa.get('checks',{}).get('transcript',{}).get('passed') is False):
      # Sentence-restart salvage: keep the cleanly spoken [anchor+insert] span from this
      # attempt's full-context generation and transplant it into the original. The candidate
      # must pass the same unchanged QA gates before it can be selected; any alignment
      # ambiguity fails closed and the attempt keeps its original failure.
      try:
       candidate=ad/'candidate.wav'
       tinfo=insert_transplant(prepared,out,self.gate.transcriber,p.get('anchor',''),p.get('text',''),p.get('position'),candidate)
       salvage_qa=self.gate.check(prepared,candidate,plan)
       record['salvage']={**tinfo,'qa':salvage_qa};record['artifact_paths'].append(str(candidate))
       if salvage_qa['automatic_pass']:
        selected=str(candidate);record['selected']=True;qa_pass=True;reason=None
        record['automatic_qa_pass']=True;record['failure_reason']=None
      except Exception as salvage_exc:
       record['salvage_error']=getattr(salvage_exc,'code',type(salvage_exc).__name__)
    if localized and reason=='qa_failed':
     try:
      _outside=outside_interval_pcm_exact(full,final,float(start),float(end))
      record['outside_interval_pcm_exact']=_outside
      _txw=(qa.get('checks',{}).get('transcript',{}) or {}).get('words')
      _cut=(record.get('splice') or {}).get('source_cut_seconds')
      _cls=classify_transcript_disagreement(qa,outside_exact=_outside,cut=_cut,timed_words=_txw)
      if _cls:record['failure_class']=_cls
     except Exception as cls_exc:record['classification_error']=getattr(cls_exc,'code',type(cls_exc).__name__)
   except Exception as exc:
    reason=getattr(exc,'code',type(exc).__name__);record['failure_reason']=reason
    record['error_detail']=str(exc)[:1800]
    # A technically valid artifact is never lost merely because later QA failed.
    qa_pass=False
   record['latency_seconds']=time.monotonic()-began;attempts.append(record)
   atomic_json(ad/'attempt.json',record)
   atomic_json(folder/'attempts.json',attempts)
   if selected or reason not in RETRYABLE:break
   if number<self.max_attempts:
    self.adapter.stop();time.sleep(min(.25*2**(number-1),1))
  result=Result(rid,'qa_pass_review_pending' if selected else ('review_required' if technical else 'failed'),
   technical,qa_pass,None,selected,reason,profile,time.monotonic()-request_started,attempts,str(folder))
  atomic_json(folder/'result.json',dataclasses.asdict(result));return result
 def close(self):
  if self.lockfile.closed:return
  self.adapter.stop();fcntl.flock(self.lockfile,fcntl.LOCK_UN);self.lockfile.close()

_default_worker=None

def configure_default_worker(worker):
 global _default_worker
 _default_worker=worker

def edit_audio(input_audio,mode,operation,parameters):
 if _default_worker is None:raise EditorError('worker_not_configured','Configure a worker first.')
 return _default_worker.edit_audio(input_audio,mode,operation,parameters)
