"""Fetch CC-licensed test audio for the language and duration tests.

FLEURS (Google, CC BY 4.0): short clips in several languages, with reference text.
LibriSpeech dev-clean (CC BY 4.0): one speaker's consecutive utterances, joined into long clips.
Everything downloads at runtime; nothing is stored in this repo.
"""
import csv, io, json, os, subprocess, sys, tarfile, urllib.request
from pathlib import Path

FLEURS = {'en': 'en_us', 'es': 'es_419', 'fr': 'fr_fr', 'de': 'de_de', 'hi': 'hi_in',
          'zh': 'cmn_hans_cn', 'ja': 'ja_jp', 'ar': 'ar_eg', 'pt': 'pt_br'}

def fleurs(root: Path, per_lang: int = 2, lo: float = 7.0, hi: float = 13.0) -> list[dict]:
    out = []
    for code, cfg in FLEURS.items():
        d = root / 'fleurs' / code; d.mkdir(parents=True, exist_ok=True)
        meta_path = d / 'meta.json'
        if meta_path.is_file():
            out += json.loads(meta_path.read_text()); continue
        base = f'https://huggingface.co/datasets/google/fleurs/resolve/main/data/{cfg}/'
        tsv = urllib.request.urlopen(base + 'test.tsv', timeout=60).read().decode()
        cand = {}
        for line in tsv.strip().split('\n'):
            r = line.split('\t'); secs = int(r[5]) / 16000
            if lo <= secs <= hi and len(cand) < 60: cand[r[1]] = dict(lang=code, file=r[1], text=r[2], secs=round(secs, 2), gender=r[6])
        got = []
        tf = tarfile.open(fileobj=urllib.request.urlopen(base + 'audio/test.tar.gz', timeout=120), mode='r|gz')
        for m in tf:
            name = os.path.basename(m.name)
            if name in cand and len(got) < per_lang:
                (d / name).write_bytes(tf.extractfile(m).read())
                got.append({**cand[name], 'path': str(d / name)})
                if len(got) >= per_lang: break
        meta_path.write_text(json.dumps(got, ensure_ascii=False, indent=1)); out += got
    return out

def librispeech_long(root: Path, targets=(20, 30, 45, 60, 90, 120, 180, 300, 600, 1200)) -> list[dict]:
    d = root / 'libri'; d.mkdir(parents=True, exist_ok=True)
    idx = d / 'long.json'
    if idx.is_file(): return json.loads(idx.read_text())
    tf = tarfile.open(fileobj=urllib.request.urlopen('https://www.openslr.org/resources/12/dev-clean.tar.gz', timeout=120), mode='r|gz')
    spk = None; files = []; trans = {}
    for m in tf:
        if not m.isfile(): continue
        parts = m.name.split('/')
        if spk is None and m.name.endswith('.flac'): spk = parts[-3]
        if spk is None or parts[-3] != spk:
            if len(files) > 30: break
            continue
        if m.name.endswith('.flac'):
            p = d / os.path.basename(m.name); p.write_bytes(tf.extractfile(m).read()); files.append(p)
        elif m.name.endswith('.trans.txt'):
            for line in tf.extractfile(m).read().decode().splitlines():
                k, t = line.split(' ', 1); trans[k] = t.lower()
    files.sort()
    def dur(p): return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(p)]).decode())
    durs = {p: dur(p) for p in files}
    sil = d / 'sil.wav'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','anullsrc=r=16000:cl=mono','-t','0.4',str(sil)], check=True)
    res = []
    for t in targets:
        sel, tot, i = [], 0.0, 0
        while tot < t:
            p = files[i % len(files)]; sel.append(p); tot += durs[p] + 0.4; i += 1
        lst = d / f'list{t}.txt'
        lst.write_text(''.join(f"file '{p}'\nfile '{sil}'\n" for p in sel))
        out = d / f'long_{t}s.flac'
        subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(lst),'-ar','16000','-ac','1',str(out)], check=True)
        text = ' '.join(trans[p.stem] for p in sel)
        res.append({'target': t, 'path': str(out), 'secs': round(dur(out), 1), 'text': text, 'utterances': len(sel)})
    idx.write_text(json.dumps(res, ensure_ascii=False)); return res
