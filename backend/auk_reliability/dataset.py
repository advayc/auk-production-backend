import json, math
from pathlib import Path
from .core import Limits, probe_audio, sha256_file, EditorError, build_plan
from .policy import OPERATIONS, plan_request, selected_modes
DIMENSIONS=('voice_id','accent','microphone','noise','reverb','speaking_speed','format','duration_bucket','language')

def validate_dataset(path, *, acceptance=True, modes=None):
 path=Path(path).resolve();data=json.loads(path.read_text())
 if not isinstance(data,dict) or data.get('schema_version')!=1:raise ValueError('Expected schema_version=1 with clips and requests.')
 modes=selected_modes(modes);all_requests=data.get('requests',[])
 requests=[r for r in all_requests if r.get('mode') in modes]
 # Unknown modes are errors, never silently omitted as another owner's work.
 if any(r.get('mode') not in OPERATIONS for r in all_requests):raise ValueError('Manifest contains unsupported mode')
 used_clips={r.get('clip_id') for r in requests}
 clips=[c for c in data.get('clips',[]) if c.get('id') in used_clips];errors=[];ids={};hashes=set();levels={d:set() for d in DIMENSIONS};coverage=set()
 for c in clips:
  cid=c.get('id');raw=Path(c.get('audio_path',''));audio=(path.parent/raw).resolve() if not raw.is_absolute() else raw
  try:
   if not cid or cid in ids:raise ValueError('Missing or duplicate clip id')
   digest=sha256_file(audio);meta=probe_audio(audio,Limits());hashes.add(digest)
   if c.get('sha256')!=digest:raise ValueError('Missing or mismatching SHA-256')
   if c.get('rights_verified') is not True or not c.get('license') or not c.get('provenance'):raise ValueError('Missing verified rights/license/provenance')
   if c.get('transcript_verified') is not True or not c.get('transcript'):raise ValueError('Human-checked transcript required')
   if not c.get('split'):raise ValueError('Missing held-out/development split')
   labels=c.get('labels',{})
   for d in DIMENSIONS:
    if not isinstance(labels.get(d),str) or not labels[d].strip() or 'unreviewed' in labels[d] or labels[d] in ('unknown','pending'):raise ValueError('Missing dimension '+d)
    levels[d].add(labels[d])
   if data.get('supported_languages') and labels['language'] not in data['supported_languages']:raise ValueError('Language outside supported_languages')
   if labels['format'].lower().lstrip('.')!=audio.suffix.lower().lstrip('.'):raise ValueError('Format label does not match file extension')
   ids[cid]={**c,'audio_path':str(audio),'duration':meta['duration_seconds']};hashes.add(digest)
  except Exception as e:errors.append({'clip':cid,'error':str(e)})
 request_ids=set()
 for r in requests:
  try:
   if not r.get('id') or r['id'] in request_ids:raise ValueError('Request ID missing/duplicated')
   request_ids.add(r['id']);c=ids[r['clip_id']];p=dict(r['parameters'])
   if p.get('source_text')!=c['transcript']:raise ValueError('source_text differs from verified clip transcript')
   if acceptance and c['split']!='held_out':raise ValueError('Acceptance clips must be held_out')
   start=p.get('segment_start_seconds',0) if r['mode']=='transcript_editor' else p.get('start_seconds',0)
   end=p.get('segment_end_seconds') if r['mode']=='transcript_editor' else p.get('end_seconds',c['duration'])
   if end is None or not math.isfinite(float(start)) or not math.isfinite(float(end)) or not 0<=float(start)<float(end)<=c['duration']+.001:raise ValueError('Invalid selected interval')
   plan_request(r['mode'],r['operation'],p,float(end)-float(start),Limits())
   if r['mode']=='transcript_editor':
    if p.get('segment_scope')=='whole_clip':
     if float(start)!=0 or abs(float(end)-c['duration'])>.02 or p.get('segment_text','').strip()!=c['transcript'].strip() or not c['transcript_verified']:
      raise ValueError('Whole-clip scope needs full-clip interval and the human-verified clip transcript')
    elif p.get('alignment_verified') is not True:raise ValueError('Segment alignment not human verified')
   if not isinstance(p.get('seed',42),int):raise ValueError('Invalid seed')
   coverage.add((r['mode'],r['operation']))
  except Exception as e:errors.append({'request':r.get('id'),'error':str(e)})
 if acceptance:
  if len(hashes)<100:errors.append({'dataset':'At least 100 distinct source-file hashes required.'})
  if len(requests)<1000:errors.append({'dataset':'At least 1000 valid requests required.'})
  missing=set((m,o) for m in modes for o in OPERATIONS[m])-coverage
  if missing:errors.append({'dataset':'Missing operations: '+str(sorted(missing))})
  for d,values in levels.items():
   if d!='language' and len(values)<2:errors.append({'dataset':'Insufficient '+d+' variation (minimum 2 audited values).'})
  if not data.get('coverage_reviewed_by') or not data.get('supported_languages'):
   errors.append({'dataset':'Require coverage_reviewed_by and supported_languages; labels alone do not prove representativeness.'})
 return {'valid':not errors,'errors':errors,'distinct_sources':len(hashes),'request_count':len(requests),
   'scope_modes':list(modes),'excluded_request_count':len(all_requests)-len(requests),'coverage':sorted(coverage),'levels':{k:sorted(v) for k,v in levels.items()},'manifest_sha256':sha256_file(path),
   'clips':ids,'requests':requests,'data':data}
