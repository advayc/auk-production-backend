"""Machine-measurement harness for the language and duration tests (no listening claims).

Run inside the production notebook runtime after the worker is set up:
  from limit_tests.run_tests import run_language_tests, run_duration_ladder
Results append to <out>/results.jsonl, so a disconnected run resumes where it stopped.
"""
import json, subprocess, time, traceback
from pathlib import Path

def _dur(p):
    try: return round(float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(p)]).decode()), 2)
    except Exception: return None

def _done(out):
    f = Path(out) / 'results.jsonl'
    return {json.loads(l)['id'] for l in f.read_text().splitlines()} if f.is_file() else set()

def _log(out, row):
    with (Path(out) / 'results.jsonl').open('a') as f: f.write(json.dumps(row, ensure_ascii=False) + '\n')
    print(' | '.join(f'{k}={row.get(k)}' for k in ('id','outcome','reason','tech','qa','latency','in_s','out_s','err','spk','attempts')), flush=True)

def _summ(res, case_id, in_s):
    row = {'id': case_id, 'outcome': res.outcome, 'reason': res.reason, 'tech': res.technical_success,
           'qa': res.automatic_qa_pass, 'latency': round(res.latency_seconds), 'in_s': in_s,
           'out_s': _dur(res.output_path) if res.output_path else None, 'attempts': len(res.attempts)}
    for a in res.attempts[-1:]:
        checks = (a.get('qa') or {}).get('checks', {})
        row['err'] = checks.get('transcript', {}).get('error_rate')
        row['spk'] = checks.get('speaker', {}).get('score')
        row['heard'] = (checks.get('transcript', {}).get('observed') or '')[:200]
        row['attempt_reason'] = a.get('failure_reason')
    return row

def _edit(worker, case_id, src, mode, op, params, in_s, out):
    if case_id in _done(out): return
    try:
        res = worker.edit_audio(src, mode, op, params)
        row = _summ(res, case_id, in_s)
    except Exception as exc:
        row = {'id': case_id, 'outcome': 'exception', 'reason': getattr(exc, 'code', type(exc).__name__),
               'tech': False, 'qa': False, 'in_s': in_s, 'message': str(exc)[:300]}
    _log(out, row)

def _cer(ref, hyp):
    import unicodedata, re
    n = lambda s: ''.join(c for c in unicodedata.normalize('NFKC', s).casefold() if c.isalnum())
    a, b = n(ref), n(hyp)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return round(prev[-1] / max(1, len(a)), 3)

def run_language_tests(worker, transcribe, clips, out, ops=('enhance', 'speed', 'delete')):
    Path(out).mkdir(parents=True, exist_ok=True)
    for c in clips:
        base_id = f"lang-{c['lang']}-{Path(c['path']).stem[-6:]}"
        # baseline: can the QA ASR reproduce the human reference for this language at all?
        if base_id + '-asr' not in _done(out):
            t0 = time.time(); obs = transcribe(Path(c['path']))
            _log(out, {'id': base_id + '-asr', 'outcome': 'baseline_asr', 'lang': c['lang'], 'detected': obs.get('language'),
                       'err': _cer(c['text'], obs['text']), 'ref': c['text'][:160], 'heard': obs['text'][:160], 'in_s': c['secs'], 'latency': round(time.time()-t0)})
        obs = transcribe(Path(c['path'])); asr_text = obs['text'].strip()
        base = {'source_text': asr_text, 'rights_confirmed': True, 'profile': 'base_f32', 'seed': 42}
        if 'enhance' in ops:
            _edit(worker, base_id + '-enhance', c['path'], 'voice_enhancer', 'enhance', dict(base), c['secs'], out)
        if 'speed' in ops:
            _edit(worker, base_id + '-speed', c['path'], 'voice_editor', 'speed', {**base, 'speed_factor': 1.25}, c['secs'], out)
        if 'delete' in ops:
            toks = asr_text.split()
            if len(toks) >= 6:
                target = toks[len(toks)//2]
            else:  # unspaced scripts: delete two characters from the middle
                mid = len(asr_text)//2; target = asr_text[mid:mid+2]
            if asr_text.count(target) == 1:
                edited = ' '.join(asr_text.replace(target, '', 1).split())
                p = {**base, 'segment_start_seconds': 0, 'segment_end_seconds': None, 'segment_text': asr_text,
                     'segment_scope': 'whole_clip', 'text': target, 'edited_segment_text': edited}
                _edit(worker, base_id + '-delete', c['path'], 'transcript_editor', 'delete', p, c['secs'], out)
            else:
                _log(out, {'id': base_id + '-delete', 'outcome': 'skipped_no_unique_target', 'in_s': c['secs']})

def run_duration_ladder(worker, longs, out, steps, ops=('speed', 'delete', 'enhance')):
    Path(out).mkdir(parents=True, exist_ok=True)
    for L in longs:
        if L['target'] not in steps: continue
        txt = L['text']; s = L['secs']
        base = {'source_text': txt, 'rights_confirmed': True, 'profile': 'base_f32', 'seed': 42}
        cid = f"dur-{L['target']}s"
        if 'enhance' in ops: _edit(worker, cid + '-enhance', L['path'], 'voice_enhancer', 'enhance', dict(base), s, out)
        if 'speed' in ops: _edit(worker, cid + '-speed', L['path'], 'voice_editor', 'speed', {**base, 'speed_factor': 1.25}, s, out)
        if 'delete' in ops:
            toks = txt.split(); target = toks[len(toks)//2]
            if txt.split().count(target) == 1 and txt.count(target) == 1:
                edited = ' '.join(txt.replace(target, '', 1).split())
                p = {**base, 'segment_start_seconds': 0, 'segment_end_seconds': None, 'segment_text': txt,
                     'segment_scope': 'whole_clip', 'text': target, 'edited_segment_text': edited}
                _edit(worker, cid + '-delete', L['path'], 'transcript_editor', 'delete', p, s, out)
            else:
                # pick any unique word near the middle
                from collections import Counter
                cnt = Counter(txt.split()); mid = len(toks)//2
                cand = next((w for w in toks[mid:] + toks[:mid] if cnt[w] == 1 and txt.count(w) == 1), None)
                if cand:
                    edited = ' '.join(txt.replace(cand, '', 1).split())
                    p = {**base, 'segment_start_seconds': 0, 'segment_end_seconds': None, 'segment_text': txt,
                         'segment_scope': 'whole_clip', 'text': cand, 'edited_segment_text': edited}
                    _edit(worker, cid + '-delete', L['path'], 'transcript_editor', 'delete', p, s, out)
