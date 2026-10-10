"""Explicit local-to-Drive checkpoints. No credentials, generation, or automatic reviews."""
from pathlib import Path
import json, os, shutil, hashlib, datetime
from .core import atomic_json, sha256_file

SKIP_PARTS={'venv','models','model-cache','__pycache__','.git','shared-runtime'}
class Checkpoint:
 def __init__(self, destination, roots):
  self.destination=Path(destination);self.destination.mkdir(parents=True,exist_ok=True)
  self.roots={k:Path(v).resolve() for k,v in roots.items()}
  if any(not k.replace('-','').replace('_','').isalnum() for k in roots):raise ValueError('Invalid root label')
  if any(self.destination.resolve().is_relative_to(p) for p in self.roots.values()):raise ValueError('Backup must be outside working roots')
 def sync(self):
  inventory=[]
  for label,root in self.roots.items():
   if not root.exists():continue
   for source in sorted(root.rglob('*')):
    rel=source.relative_to(root)
    # Exclude only this downloaded speaker model in backend backups.
    if label=='backend' and rel.parts[:2]==('shared-speaker-qa','0f99f2d0ebe89ac095bcc5903c4dd8f72b367286'):continue
    if any(part in SKIP_PARTS or part.startswith(('deliverables-','venv-')) for part in rel.parts) or source.name=='.worker.lock':continue
    if source.suffix in ('.gguf','.ckpt','.bin','.safetensors'):continue
    if source.is_symlink():raise ValueError('Checkpoint refuses symlinks: '+str(source))
    if not source.is_file():continue
    target=self.destination/label/rel;target.parent.mkdir(parents=True,exist_ok=True)
    digest=sha256_file(source)
    if not target.exists() or sha256_file(target)!=digest:
     tmp=target.with_name(target.name+'.partial');shutil.copyfile(source,tmp)
     if sha256_file(tmp)!=digest:raise RuntimeError('Backup checksum mismatch')
     os.replace(tmp,target)
    inventory.append({'path':str(Path(label)/rel),'sha256':digest,'bytes':source.stat().st_size})
  atomic_json(self.destination/'checkpoint.json',{'schema':1,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':inventory,'excluded':sorted(SKIP_PARTS),'roots':{k:str(v) for k,v in self.roots.items()}})
  return {'verified_files':len(inventory),'destination':str(self.destination)}
 def restore(self, only=None):
  """Restore a snapshot. only=('dataset','runs') restores just those labels and ignores others
  (read-only use of an older backup; e.g. never mix an old backend into a newer one)."""
  manifest=json.loads((self.destination/'checkpoint.json').read_text())
  if only is not None:
   only=set(only)
   if not only<=set(self.roots):raise ValueError('only= names an unknown root label')
   manifest=dict(manifest,files=[r for r in manifest['files'] if Path(r['path']).parts[0] in only])
  # Validate the whole snapshot before restoring anything. Never overwrite changed local files.
  pending=[]
  for record in manifest['files']:
   rel=Path(record['path'])
   if rel.is_absolute() or '..' in rel.parts or rel.parts[0] not in self.roots:raise ValueError('Unsafe checkpoint entry')
   source=self.destination/rel;target=self.roots[rel.parts[0]]/Path(*rel.parts[1:])
   if sha256_file(source)!=record['sha256']:raise ValueError('Corrupt checkpoint '+str(rel))
   if target.exists() and sha256_file(target)!=record['sha256']:raise FileExistsError('Restore conflict '+str(target))
   pending.append((source,target))
  for source,target in pending:
   target.parent.mkdir(parents=True,exist_ok=True)
   if not target.exists():shutil.copyfile(source,target)
  return {'restored_files':len(pending)}

def balanced_cases(audit, limit):
 """Round-robin speakers, then recordings, then variants. No repeated clip until all eligible clips used."""
 from collections import defaultdict
 groups=defaultdict(lambda:defaultdict(lambda:defaultdict(list)))
 for case in audit['requests']:
  clip=audit['clips'][case['clip_id']]
  if clip['split'] not in ('dev','development'):raise ValueError('Benchmark requires development clips, never held_out')
  groups[(case['mode'],case['operation'])][clip['labels']['voice_id']][case['clip_id']].append(case)
 selected=[]
 for key,speakers in sorted(groups.items()):
  queues={sp:[] for sp in sorted(speakers)}
  for sp,clips in speakers.items():
   # Variant rounds avoid duplicating a source before the other sources of that speaker.
   for j in range(max(len(v) for v in clips.values())):
    for cid in sorted(clips):
     if j<len(clips[cid]):queues[sp].append(clips[cid][j])
  count=0
  while count<limit and any(queues.values()):
   for sp in sorted(queues):
    if queues[sp] and count<limit:selected.append(queues[sp].pop(0));count+=1
 return selected

def assert_split_disjoint(dev_manifest, held_manifest):
 dev=json.loads(Path(dev_manifest).read_text());held=json.loads(Path(held_manifest).read_text())
 for field in ('sha256','voice_id'):
  a={c.get(field) if field=='sha256' else c.get('labels',{}).get(field) for c in dev['clips']}
  b={c.get(field) if field=='sha256' else c.get('labels',{}).get(field) for c in held['clips']}
  if not a or not b or None in a|b or a&b:raise ValueError('Dev/held-out overlap or missing '+field)
 return True

def execution_signature(worker, manifest_hash, kind, cases):
 from .core import canonical_hash
 profile=worker.runtime_profile
 return canonical_hash({'manifest':manifest_hash,'kind':kind,'cases':cases,'backend':__import__('auk_reliability').__version__,
  'package_hashes':{x.name:sha256_file(x) for x in sorted(Path(__file__).parent.glob('*.py'))},'runtime':profile.get('runtime'),'model':profile.get('model'),'asr':profile.get('asr_fingerprint'),
  'speaker':profile.get('speaker_fingerprint'),'simulation':profile.get('simulation',False),'max_attempts':getattr(worker,'max_attempts',None)})

def prepare_run(out, signature, resume, progress_name):
 out=Path(out)
 if out.exists():
  if not resume:raise FileExistsError('Run exists. Choose a new directory or explicitly resume.')
  if json.loads((out/'resume.json').read_text())['signature']!=signature:raise ValueError('Resume signature changed; use new run')
 else:
  if resume:raise FileNotFoundError('Restore the checkpoint before resuming')
  out.mkdir(parents=True);atomic_json(out/'resume.json',{'signature':signature})
 rows=[]
 path=out/progress_name
 if path.exists():
  lines=path.read_text().splitlines()
  for index,line in enumerate(lines):
   try:row=json.loads(line)
   except json.JSONDecodeError:
    # Only an interrupted final append may be trimmed. Interior corruption is an error.
    if index!=len(lines)-1:raise
    path.write_text('\n'.join(lines[:index])+('\n' if index else ''));break
   for name,digest in row.get('artifact_hashes',{}).items():
    if not Path(name).is_file() or sha256_file(Path(name))!=digest:raise ValueError('Missing/changed resume artifact: '+name)
   if row.get('output_path') and not row.get('artifact_hashes'):raise ValueError('Resume output lacks integrity record')
   rows.append(row)
 return rows

def add_artifact_hashes(row):
 paths=set(p for a in row.get('attempts',[]) for p in a.get('artifact_paths',[]))
 if row.get('output_path'):paths.add(row['output_path'])
 folder=row.get('request_dir')
 if folder:
  paths.update(str(p) for p in Path(folder).rglob('*') if p.is_file() and p.name!='review.json')
 row['artifact_hashes']={p:sha256_file(Path(p)) for p in sorted(paths) if Path(p).is_file()}
 return row
