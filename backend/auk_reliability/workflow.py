"""Colab dataset and handoff helpers. No inference, invented labels or automatic approvals."""
from pathlib import Path
import csv, json, zipfile, stat, collections
from .core import sha256_file, atomic_json, probe_audio, Limits
from .dataset import validate_dataset, DIMENSIONS
from .policy import ACTIVE_MODES, OPERATIONS, PROFILES
from .acceptance import recommend_profiles

AUDIO_EXTENSIONS = {'.wav','.mp3','.flac','.m4a','.mp4','.mov','.ogg','.opus','.webm'}
CLIP_FIELDS = ['id','audio_path','transcript','transcript_verified','rights_verified','license','provenance','split', *DIMENSIONS,
 'alignment_verified','segment_start_seconds','segment_end_seconds','segment_text','replace_old','replace_new','insert_text','insert_anchor','insert_position','delete_text']

def extract_bundle(archive, destination, *, max_bytes=2*1024**3):
 """Extract a reviewed local ZIP, rejecting traversal, symlinks, duplicates and oversized payloads."""
 root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(archive) as z:
  names=set();total=0
  for info in z.infolist():
   dest=(root/info.filename).resolve();total+=info.file_size
   if (not dest.is_relative_to(root) or '\\' in info.filename or
       stat.S_ISLNK(info.external_attr >> 16) or info.filename in names or total>max_bytes):
    raise ValueError('Unsafe or oversized corpus ZIP')
   names.add(info.filename)
  if len(names)>20000:raise ValueError('Too many ZIP entries')
  for info in z.infolist():
   dest=root/info.filename
   if dest.exists() and not info.is_dir():raise FileExistsError('Bundle would overwrite '+str(dest))
  z.extractall(root)
 return root

def make_clip_template(root, csv_path):
 """Inventory source audio. Every review flag remains false and every unknown label stays unknown."""
 root=Path(root).resolve();csv_path=Path(csv_path)
 if csv_path.exists():raise FileExistsError('Template would overwrite reviewed metadata')
 rows=[]
 for i,p in enumerate(sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS)):
  row={k:'' for k in CLIP_FIELDS};row.update(id=f'clip-{i+1:04d}',audio_path=str(p.relative_to(csv_path.parent.resolve())),
    transcript_verified='false',rights_verified='false',alignment_verified='false',split='held_out',format=p.suffix[1:].lower(),insert_position='after')
  for k in DIMENSIONS:
   if not row[k]:row[k]='unknown'
  rows.append(row)
 if not rows:raise ValueError('No supported audio files found')
 csv_path.parent.mkdir(parents=True,exist_ok=True)
 with csv_path.open('w',newline='',encoding='utf-8') as f:
  writer=csv.DictWriter(f,fieldnames=CLIP_FIELDS);writer.writeheader();writer.writerows(rows)
 return len(rows)

def _flag(value):return str(value).strip().lower()=='true'

def build_manifest(csv_path, manifest_path, *, reviewer, languages=('en',)):
 """Ten valid request templates per fully reviewed clip. Does not invent transcript edit alignment."""
 if not reviewer.strip() or not languages:raise ValueError('Name the coverage reviewer and supported languages')
 csv_path=Path(csv_path).resolve();target=Path(manifest_path).resolve();clips=[];requests=[]
 with csv_path.open(newline='',encoding='utf-8-sig') as f:
  reader=csv.DictReader(f)
  if not set(CLIP_FIELDS)<=set(reader.fieldnames or []):raise ValueError('Missing required clips.csv columns')
  for row in reader:
   cid=row['id'].strip();audio=(csv_path.parent/row['audio_path']).resolve()
   if not audio.is_file():raise FileNotFoundError(audio)
   c={'id':cid,'audio_path':str(audio),'sha256':sha256_file(audio),'transcript':row['transcript'].strip(),
      'transcript_verified':_flag(row['transcript_verified']),'rights_verified':_flag(row['rights_verified']),
      'license':row['license'],'provenance':row['provenance'],'split':row['split'],
      'labels':{k:row[k].strip() for k in DIMENSIONS}}
   clips.append(c);base={'source_text':c['transcript'],'rights_confirmed':c['rights_verified'],'seed':42,'profile':'base_f32'}
   # Ten distinct edits; 100 genuinely different sources yield 1000 requests, not copies of a single request.
   variants=[('emotion',{'emotion':'calm'}),('voice_characteristics',{'description':'warm, slightly deeper voice'}),
      ('whisper',{}),('speed',{'speed_factor':1.25}),('custom',{'instruction':'Keep every word but sound more confident.','semantic_contract':{'preserve_transcript':True}}),
      ('emotion',{'emotion':'excited'}),('speed',{'speed_factor':.8})]
   for index,(op,params) in enumerate(variants):
    requests.append({'id':cid+'-voice-'+str(index+1),'clip_id':cid,'mode':'voice_editor','operation':op,'parameters':{**base,**params}})
   seg=row['segment_text'].strip()
   try:start=float(row['segment_start_seconds']);end=float(row['segment_end_seconds'])
   except ValueError as exc:raise ValueError(cid+': supply checked segment start/end seconds') from exc
   interval={**base,'segment_start_seconds':start,'segment_end_seconds':end,'segment_text':seg,'alignment_verified':_flag(row['alignment_verified'])}
   if (row.get('segment_scope') or '').strip()=='whole_clip':
    # Whole-clip scope: no human timestamps involved; alignment is not claimed as human-verified.
    interval['segment_scope']='whole_clip';interval['alignment_verified']=False
   before=row['replace_old'];after=row['replace_new'];delete=row['delete_text'];anchor=row['insert_anchor'];text=row['insert_text'];position=row['insert_position']
   edits=[('replace',{'original_text':before,'replacement_text':after,'edited_segment_text':seg.replace(before,after,1)}),
      ('insert',{'text':text,'anchor':anchor,'position':position,'edited_segment_text':seg.replace(anchor,(text+' '+anchor) if position=='before' else (anchor+' '+text),1)}),
      ('delete',{'text':delete,'edited_segment_text':' '.join(seg.replace(delete,'',1).split())})]
   for op,params in edits:requests.append({'id':cid+'-'+op,'clip_id':cid,'mode':'transcript_editor','operation':op,'parameters':{**interval,**params}})
 data={'schema_version':1,'coverage_reviewed_by':reviewer,'supported_languages':list(languages),'clips':clips,'requests':requests}
 atomic_json(target,data)
 return validate_dataset(target,modes=ACTIVE_MODES)

def save_review(request_dir, *, reviewer, passed, notes=''):
 if not reviewer.strip() or type(passed) is not bool:raise ValueError('Supply reviewer and boolean passed after listening')
 folder=Path(request_dir);result=json.loads((folder/'result.json').read_text());output=result.get('output_path')
 if not output or not Path(output).is_file():raise ValueError('No selected QA-passing output to review')
 record={'reviewer':reviewer,'passed':passed,'notes':notes,'output_sha256':sha256_file(Path(output))}
 atomic_json(folder/'review.json',record);return record

def refresh_benchmark(path):
 from .acceptance import load_review
 from .worker import Result
 import dataclasses
 path=Path(path);data=json.loads(path.read_text());allowed={f.name for f in dataclasses.fields(Result)}
 for row in data['rows']:
  if row.get('request_dir') and row.get('request_id'):
   result=Result(**{k:v for k,v in row.items() if k in allowed});row['semantic_success']=load_review(row['request_dir'],result)
 atomic_json(path,data);return data

def candidate_profiles(benchmark, *, minimum_per_operation=30, require_perfect=True):
 """Measured shortlist only, never production qualification. Cannot lower the quality gates."""
 if benchmark.get('complete') is False:raise ValueError('Benchmark interrupted; finish a complete run before selection')
 if minimum_per_operation<30:raise ValueError('At least 30 per operation/profile for screening')
 if require_perfect:
  result=recommend_profiles(benchmark,min_requests=minimum_per_operation,technical_floor=1.0,qa_floor=1.0,semantic_floor=1.0)
 else:result=recommend_profiles(benchmark,min_requests=minimum_per_operation)
 for row in result.values():
  row['status']='candidate_requires_held_out_acceptance' if row['recommended_profile'] else 'not_qualified'
 return result

def apply_candidates(manifest, candidates, output_path):
 data=json.loads(Path(manifest).read_text())
 for r in data['requests']:
  if r['mode'] not in ACTIVE_MODES:continue
  recommendation=candidates.get(r['mode']+'/'+r['operation'],{})
  profile=recommendation.get('recommended_profile')
  if profile not in PROFILES:raise ValueError('No reviewed candidate for '+r['mode']+'/'+r['operation'])
  r['parameters']['profile']=profile
 atomic_json(Path(output_path),data);return output_path

def write_handoff(acceptance_dir, benchmark_file, output_dir):
 """Derive the production recommendation from actual benchmark + selected-profile acceptance."""
 out=Path(output_dir);out.mkdir(parents=True,exist_ok=True);suite=json.loads((Path(acceptance_dir)/'summary.json').read_text())
 bench=refresh_benchmark(benchmark_file);candidates=candidate_profiles(bench)
 rows=[json.loads(line) for line in (Path(acceptance_dir)/'requests.jsonl').read_text().splitlines()]
 config={}
 for key,screen in candidates.items():
  used={r['profile'] for r in rows if r['mode']+'/'+r['operation']==key}
  candidate=screen['recommended_profile']
  matched=used=={candidate} and candidate is not None
  qualified=bool(matched and suite.get('observed_perfect_pass') and not suite['environment'].get('simulation'))
  config[key]={'recommended_profile':candidate if qualified else None,'screening_candidate':candidate,
      'status':'measured_candidate_passed_held_out_acceptance' if qualified else 'not_qualified',
      'acceptance_profiles':sorted(used),'screening':screen,'note':'Sample-based evidence, not a future success guarantee.'}
 atomic_json(out/'production_config.json',config)
 failures={k:v['failure_categories'] for k,v in suite['by_operation'].items()}
 atomic_json(out/'failure_breakdown.json',failures)
 text=['# AuK delivery status','','Scope: AI Voice Editor + Transcript Editor. Enhancer excluded.',
    'Acceptance status: '+suite['status'],'Technical gate: '+str(suite['technical_acceptance_pass']),
    'Full quality gate: '+str(suite['acceptance_pass']),'','## Known failure cases']
 for key,count in failures.items():text.append('- '+key+': '+json.dumps(count))
 text += ['', '## Remaining release blockers',
    '- Attribute/naturalness QA is not calibrated. Human review is still required; this does not meet a promise to detect every semantic failure automatically.',
    '- Qwen2.5-Omni-3B commercial-use clearance must be obtained from the licensor.',
    '- Fresh T4 rerun, durable deployment, authentication, queue/storage and monitoring are separate production checks.',
    '- Transcript edits use checked fixed-duration intervals; rushed insertions and audible seams need review.',
    '- Colab allocation cost requires the real hourly rate; full-session cost includes setup time not included in inference reports.']
 (out/'KNOWN_FAILURES.md').write_text('\n'.join(text)+'\n')
 return config


def make_whole_clip_csv(source_csv, output_csv):
 """Write a SEPARATE copy of clips CSV using each clip's whole transcript as the transcript-edit window.
 Never overwrites source_csv or an existing output. Rows whose edit targets are not unique in the whole
 transcript, or longer than the 15 s input limit, are reported, not silently changed."""
 import csv, subprocess, json as _json
 src=Path(source_csv).resolve();dst=Path(output_csv).resolve()
 if dst==src or dst.exists():raise FileExistsError('Output must be a new file; reviewed CSVs are never overwritten')
 if dst.parent!=src.parent:raise ValueError('Keep the copy beside the source CSV so relative audio paths stay valid')
 with src.open(newline='') as f:
  reader=csv.DictReader(f);fields=list(reader.fieldnames or []);rows=list(reader)
 if 'segment_scope' not in fields:fields.append('segment_scope')
 problems=[]
 for row in rows:
  audio=(src.parent/row['audio_path']).resolve()
  out=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(audio)],text=True)
  duration=float(_json.loads(out)['format']['duration']);text=row['transcript'].strip()
  row['segment_scope']='';why=[]
  if duration>15.0:why.append('longer than 15 s window limit')
  if row.get('transcript_verified','').strip().lower() not in ('true','1','yes'):why.append('transcript not human verified')
  for column in ('replace_old','delete_text','insert_anchor'):
   if row.get(column,'').strip() and text.count(row[column].strip())!=1:why.append(column+' not unique in whole transcript')
  if why:problems.append({'id':row['id'],'reasons':why});continue
  row.update(segment_start_seconds='0',segment_end_seconds=repr(round(duration,6)),segment_text=text,alignment_verified='false',segment_scope='whole_clip')
 with dst.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 return {'written':str(dst),'whole_clip_rows':len(rows)-len(problems),'rows_left_unchanged':problems}
