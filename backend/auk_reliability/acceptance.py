from __future__ import annotations
import dataclasses, json, csv, math, time, collections, platform, sys, os
from pathlib import Path
from .core import atomic_json, sha256_file, command, WallClockAbort
from .dataset import validate_dataset
from .policy import OPERATIONS, PROFILES, selected_modes
from .durable import balanced_cases, execution_signature, prepare_run, add_artifact_hashes
_default_suite=None

def configure_acceptance_suite(worker, manifest, output_dir, *, modes=None):
 global _default_suite
 _default_suite=(worker,manifest,output_dir,selected_modes(modes))

def percentile(values,p):
 if not values:return None
 v=sorted(values);i=(len(v)-1)*p;lo=math.floor(i);hi=math.ceil(i)
 return v[lo]+(v[hi]-v[lo])*(i-lo)

def summarize(rows):
 n=len(rows);lat=[r['latency_seconds'] for r in rows]
 fail=collections.Counter(r['reason'] for r in rows if r.get('reason'))
 return {'request_count':n,'joint_success_rate':sum(r['technical_success'] and r['automatic_qa_pass'] and r.get('semantic_success') is True for r in rows)/n if n else 0,
 'technical_success_rate':sum(bool(r['technical_success']) for r in rows)/n if n else 0,
 'automatic_qa_pass_rate':sum(bool(r['automatic_qa_pass']) for r in rows)/n if n else 0,
 'semantic_success_rate':sum(r.get('semantic_success') is True for r in rows)/n if n else 0,
 'semantic_unreviewed_count':sum(r.get('semantic_success') is None for r in rows),
 'p50_latency_seconds':percentile(lat,.5),'p95_latency_seconds':percentile(lat,.95),
 'failure_categories':dict(fail),'failed_outputs':[{'id':r['case_id'],'request_dir':r['request_dir'],
 'paths':[p for a in r['attempts'] for p in a['artifact_paths']]} for r in rows if not r['automatic_qa_pass'] or r.get('semantic_success') is not True]}

def environment(worker):
 return {'python':sys.version,'platform':platform.platform(),'runtime_profile':worker.runtime_profile,
 'ffmpeg':command(['ffmpeg','-version']).splitlines()[0],'backend_version':__import__('auk_reliability').__version__,
 'gpu_measurements':worker.runtime_profile.get('gpu',{}),'simulation':worker.runtime_profile.get('simulation',False)}

def load_review(folder, result):
 path=Path(folder)/'review.json'
 if not path.is_file():return None
 review=json.loads(path.read_text())
 # Review is an evaluation record, never an authorization or instruction source.
 if not result.output_path or review.get('output_sha256')!=sha256_file(Path(result.output_path)):
  return None
 if not review.get('reviewer') or review.get('passed') not in (True,False):return None
 return review['passed']

def run_acceptance_suite(worker=None, manifest=None, output_dir=None, *, acceptance=True, modes=None, resume=False, checkpoint=None, wall_clock_budget_seconds=None):
 if worker is None:
  if _default_suite is None:raise RuntimeError('Call configure_acceptance_suite(worker, manifest, output_dir) first.')
  worker,manifest,output_dir,configured_modes=_default_suite
  if modes is None:modes=configured_modes
 audit=validate_dataset(manifest,acceptance=acceptance,modes=modes)
 if wall_clock_budget_seconds is not None:worker.set_deadline(wall_clock_budget_seconds)
 out=Path(output_dir)
 signature=execution_signature(worker,audit['manifest_sha256'],'acceptance',audit['requests'])
 rows=prepare_run(out,signature,resume,'requests.jsonl')
 atomic_json(out/'dataset_audit.json',{k:v for k,v in audit.items() if k not in ('clips','requests','data')})
 if not audit['valid']:raise ValueError('Dataset preflight failed; see '+str(out/'dataset_audit.json'))
 env=environment(worker);atomic_json(out/'environment.json',env)
 rate=worker.runtime_profile.get('gpu_hourly_rate_usd')
 if rate is not None and (not isinstance(rate,(float,int)) or not math.isfinite(rate) or rate<0):raise ValueError('GPU hourly rate must be nonnegative and finite.')
 suite_began=time.monotonic()
 completed={r['case_id'] for r in rows}
 if len(completed)!=len(rows):raise ValueError('Duplicate resumed acceptance cases')
 stopped_early=None
 for case in audit['requests']:
  if case['id'] in completed:continue
  p=dict(case['parameters']);p.setdefault('profile','base_f32');begin=time.monotonic()
  try:
   result=worker.edit_audio(audit['clips'][case['clip_id']]['audio_path'],case['mode'],case['operation'],p)
   row=dataclasses.asdict(result);row['semantic_success']=load_review(result.request_dir,result)
  except WallClockAbort:
   # Budget stop: no row for this case; a later resume re-runs it. Partial attempts stay in the request folder.
   stopped_early='wall_clock_budget';break
  except Exception as e:
   # Valid preflight cases that fail in the worker remain in the denominator.
   row={'request_id':None,'outcome':'failed','technical_success':False,'automatic_qa_pass':False,
    'semantic_success':None,'output_path':None,'reason':getattr(e,'code',type(e).__name__),
    'profile':p['profile'],'latency_seconds':time.monotonic()-begin,'attempts':[],
    'request_dir':getattr(e,'request_dir',None),'error_detail':str(e)[:1800]}
  row.update({'case_id':case['id'],'clip_id':case['clip_id'],'mode':case['mode'],'operation':case['operation']})
  add_artifact_hashes(row);rows.append(row)
  with (out/'requests.jsonl').open('a') as f:f.write(json.dumps(row,allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
  with (out/'request_attempts.jsonl').open('a') as f:
   for attempt in row['attempts']:f.write(json.dumps({'case_id':case['id'],**attempt},allow_nan=False)+'\n')
  if checkpoint:checkpoint.sync()
 if stopped_early and checkpoint:checkpoint.sync()
 groups={}
 for m in audit['scope_modes']:
  for op in OPERATIONS[m]:
   group=[r for r in rows if r['mode']==m and r['operation']==op]
   if group:groups[m+'/'+op]=summarize(group)
 elapsed=sum(r['latency_seconds'] for r in rows);overall=summarize(rows)
 complete=len(rows)==len(audit['requests'])
 summary={'scope_modes':audit['scope_modes'],'excluded_request_count':audit['excluded_request_count'],'overall':overall,'by_operation':groups,'environment':env,'manifest_sha256':audit['manifest_sha256'],
  'elapsed_seconds':elapsed,'resume_supported':True,'complete':complete,'stopped_early':stopped_early,'gpu_cost_usd':elapsed/3600*rate if rate is not None else None,
  'cost_note':'Sum of measured request latencies using supplied hourly rate; excludes setup/downloads, reviews, idle time and checkpoint overhead. Unknown rate is not zero.',
  'technical_acceptance_pass':bool(complete and acceptance and len(rows)>=1000 and audit['distinct_sources']>=100 and not env['simulation'] and overall['technical_success_rate']>=.99),
  'acceptance_pass':False,'status':'GPU_RESULTS_REQUIRE_QUALITY_REVIEW','source_count':audit['distinct_sources']}
 # Full acceptance also requires every operation to meet gates. No unreviewed output is a semantic success.
 summary['acceptance_pass']=bool(summary['technical_acceptance_pass'] and groups and
   all(g['technical_success_rate']>=.99 and g['automatic_qa_pass_rate']>=.99 and g['semantic_success_rate']>=.99 for g in groups.values()))
 if env['simulation']:summary['status']='SIMULATED_TEST_ONLY'
 if summary['acceptance_pass']:summary['status']='MEASURED_ACCEPTANCE_PASS'
 _add_strict_gate(summary)
 write_report(out,rows,summary)
 if checkpoint:checkpoint.sync()
 return summary

def write_report(out,rows,summary):
 atomic_json(out/'summary.json',summary)
 columns=['case_id','clip_id','mode','operation','profile','outcome','technical_success','automatic_qa_pass','semantic_success','latency_seconds','reason','output_path','request_dir']
 with (out/'requests.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
 lines=['# AuK acceptance report', '', 'Scope: '+', '.join(summary.get('scope_modes', [])),
 'Voice Enhancer: out of scope, owned by another engineer.',
 'Excluded requests: '+str(summary.get('excluded_request_count',0)), '', 'Status: '+summary['status'],
 'Technical gate: '+str(summary['technical_acceptance_pass']), 'Full quality gate: '+str(summary['acceptance_pass']), 'Observed perfect gate: '+str(summary.get('observed_perfect_pass',False)),
 '', '| Mode / operation | Requests | Technical | Auto QA | Semantic reviewed pass | P50 s | P95 s |',
 '|---|---:|---:|---:|---:|---:|---:|']
 for name,g in summary['by_operation'].items():
  lines.append(f"| {name} | {g['request_count']} | {g['technical_success_rate']:.2%} | {g['automatic_qa_pass_rate']:.2%} | {g['semantic_success_rate']:.2%} | {g['p50_latency_seconds']:.2f} | {g['p95_latency_seconds']:.2f} |")
 lines+=['','Cost USD: '+str(summary['gpu_cost_usd']),summary['cost_note'],'','## Failure review']
 for row in rows:
  if not row['automatic_qa_pass'] or row.get('semantic_success') is not True:
   lines.append(f"- {row['case_id']}: {row['reason'] or 'human_review_pending'}; request folder: {row['request_dir']}")
   for a in row['attempts']:
    lines.append(f"  - attempt {a['attempt']}: {a['failure_reason']}; artifacts: "+', '.join(a['artifact_paths']))
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n')

def refresh_reviews(output_dir):
 """Recompute reviewed quality gates after reviewing saved outputs, without another inference run."""
 out=Path(output_dir);summary=json.loads((out/'summary.json').read_text());rows=[]
 for line in (out/'requests.jsonl').read_text().splitlines():
  r=json.loads(line)
  if r['request_dir']:
   from .worker import Result
   allowed={f.name for f in dataclasses.fields(Result)}
   result=Result(**{k:v for k,v in r.items() if k in allowed});r['semantic_success']=load_review(r['request_dir'],result)
  rows.append(r)
 summary['overall']=summarize(rows)
 for name in summary['by_operation']:
  summary['by_operation'][name]=summarize([r for r in rows if r['mode']+'/'+r['operation']==name])
 summary['acceptance_pass']=bool(summary['technical_acceptance_pass'] and all(
  g['technical_success_rate']>=.99 and g['automatic_qa_pass_rate']>=.99 and g['semantic_success_rate']>=.99 for g in summary['by_operation'].values()))
 if summary['acceptance_pass']:summary['status']='MEASURED_ACCEPTANCE_PASS'
 _add_strict_gate(summary)
 write_report(out,rows,summary);return summary

def benchmark_profiles(worker, manifest, output_dir, *, per_operation_limit=30, modes=None, resume=False, checkpoint=None, wall_clock_budget_seconds=None):
 if per_operation_limit<1:raise ValueError('per_operation_limit must be positive')
 if wall_clock_budget_seconds is not None:worker.set_deadline(wall_clock_budget_seconds)
 audit=validate_dataset(manifest,acceptance=False,modes=modes)
 if not audit['valid']:raise ValueError('Benchmark dataset invalid: '+str(audit['errors']))
 cases=balanced_cases(audit,per_operation_limit)
 signature=execution_signature(worker,audit['manifest_sha256'],'benchmark',cases)
 out=Path(output_dir);rows=prepare_run(out,signature,resume,'benchmark_progress.jsonl')
 completed={(r['case_id'],r['profile']) for r in rows}
 if len(completed)!=len(rows):raise ValueError('Duplicate resumed benchmark cases')
 stopped_early=None
 for case in cases:
  key=(case['mode'],case['operation'])
  for profile in PROFILES:
   if (case['id'],profile) in completed:continue
   p={**case['parameters'],'profile':profile};began=time.monotonic()
   try:
    result=worker.edit_audio(audit['clips'][case['clip_id']]['audio_path'],*key,p);row=dataclasses.asdict(result)
    row['semantic_success']=load_review(result.request_dir,result)
   except WallClockAbort:
    # Budget stop: no row for this (case, profile); a later resume re-runs it. Partial attempts stay in the request folder.
    stopped_early='wall_clock_budget';break
   except Exception as e:
    row={'technical_success':False,'automatic_qa_pass':False,'semantic_success':None,'latency_seconds':time.monotonic()-began,
     'reason':getattr(e,'code',type(e).__name__),'request_dir':getattr(e,'request_dir',None),'attempts':[],'output_path':None,'profile':profile,
     'error_detail':str(e)[:1800]}
   row.update({'mode':key[0],'operation':key[1],'case_id':case['id'],'clip_id':case['clip_id']})
   add_artifact_hashes(row);rows.append(row)
   with (out/'benchmark_progress.jsonl').open('a') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n');stream.flush();os.fsync(stream.fileno())
   atomic_json(out/'benchmark.json',{'scope_modes':audit['scope_modes'],'excluded_request_count':audit['excluded_request_count'],'rows':rows,
    'environment':environment(worker),'manifest_sha256':audit['manifest_sha256'],'complete':False,'sampling':'speaker_round_robin'})
   if checkpoint:checkpoint.sync()
  if stopped_early:break
 if stopped_early and checkpoint:checkpoint.sync()
 result={'scope_modes':audit['scope_modes'],'excluded_request_count':audit['excluded_request_count'],'rows':rows,'environment':environment(worker),
  'manifest_sha256':audit['manifest_sha256'],'complete':len(rows)==len(cases)*len(PROFILES),'sampling':'speaker_round_robin',
  'stopped_early':stopped_early,
  'coverage':{m+'/'+op:{'requests':len([c for c in cases if (c['mode'],c['operation'])==(m,op)]),
    'unique_sources':len({c['clip_id'] for c in cases if (c['mode'],c['operation'])==(m,op)}),
    'speakers':len({audit['clips'][c['clip_id']]['labels']['voice_id'] for c in cases if (c['mode'],c['operation'])==(m,op)})}
    for m in audit['scope_modes'] for op in OPERATIONS[m]}}
 atomic_json(out/'benchmark.json',result)
 atomic_json(out/'recommendations.json',recommend_profiles(result))
 if checkpoint:checkpoint.sync()
 return result

def _add_strict_gate(summary):
 groups=summary['by_operation'];overall=summary['overall']
 summary['observed_perfect_pass']=bool(summary['technical_acceptance_pass'] and groups and
  all(g['technical_success_rate']==1 and g['automatic_qa_pass_rate']==1 and g['semantic_success_rate']==1 and g['semantic_unreviewed_count']==0 for g in groups.values()))
 summary['quality_target_note']='100% observed joint technical, automatic-QA and human-quality pass on the frozen valid set, not a guarantee on unseen inputs.'
 summary['joint_success_rate']=overall['joint_success_rate']

def recommend_profiles(benchmark, *, min_requests=1000, technical_floor=.99, qa_floor=.99, semantic_floor=.99, modes=None):
 result={};simulation=benchmark['environment'].get('simulation',False)
 for mode in selected_modes(modes if modes is not None else benchmark.get('scope_modes')):
  for op in OPERATIONS[mode]:
   candidates=[];stats={}
   for profile in PROFILES:
    rows=[r for r in benchmark['rows'] if (r['mode'],r['operation'],r['profile'])==(mode,op,profile)]
    g=summarize(rows);stats[profile]=g
    if not simulation and len(rows)>=min_requests and g['technical_success_rate']>=technical_floor and g['automatic_qa_pass_rate']>=qa_floor and g['semantic_success_rate']>=semantic_floor:
     candidates.append((g['p95_latency_seconds'],profile))
   result[mode+'/'+op]={'recommended_profile':min(candidates)[1] if candidates else None,
    'status':'measured' if candidates else 'not_qualified','profile_results':stats,
    'reason':None if candidates else 'Need real representative GPU runs, calibrated QA and reviewed quality; no automatic fastest-profile guess.'}
 return result
