#!/usr/bin/env python3
"""Copy real showcase source/output WAVs into the repo's local review gallery."""
import argparse
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GALLERY = ROOT / 'demos' / 'audio_review'


def export_audio(run_dir, manifest_path, *, replace=False):
    run_dir = Path(run_dir).resolve()
    manifest = json.loads(Path(manifest_path).read_text())
    environment_path = run_dir / 'environment.json'
    if not environment_path.is_file():
        raise FileNotFoundError(f'Missing runtime provenance: {environment_path}')
    environment = json.loads(environment_path.read_text())
    if environment.get('simulation') is not False:
        raise ValueError('Only explicitly nonsimulated model runs can be exported as audio demos.')
    clips = {clip['id']: clip for clip in manifest['clips']}
    requests = {case['id']: case for case in manifest['requests']}
    rows = [json.loads(line) for line in (run_dir / 'requests.jsonl').read_text().splitlines() if line.strip()]
    if len(rows) != len(requests) or {row['case_id'] for row in rows} != set(requests):
        raise ValueError('The showcase run must contain exactly one result row for every frozen case.')
    coverage = {}
    for case in requests.values():
        key = (case['mode'], case['operation'])
        coverage[key] = coverage.get(key, 0) + 1
    if len(coverage) != 9 or any(count != 10 for count in coverage.values()):
        raise ValueError('Audio export requires exactly ten cases for each of the nine showcase operations.')
    if not replace and (GALLERY / 'assets').exists():
        raise FileExistsError(f'{GALLERY / "assets"} already exists; pass --replace to rebuild the gallery.')
    assets = GALLERY / 'assets'
    if assets.exists():
        shutil.rmtree(assets)
    assets.mkdir(parents=True)
    entries = []
    for row in rows:
        case = requests[row['case_id']]
        folder = assets / case['mode'] / case['operation']
        folder.mkdir(parents=True, exist_ok=True)
        before_source = Path(row['request_dir']) / 'input.wav' if row.get('request_dir') else None
        before = None
        if before_source and before_source.is_file():
            before = folder / f'{case["id"]}-before.wav'
            shutil.copy2(before_source, before)
        after_source = Path(row['output_path']) if row.get('output_path') else None
        after = None
        if after_source and after_source.is_file() and row.get('automatic_qa_pass'):
            after = folder / f'{case["id"]}-after.wav'
            shutil.copy2(after_source, after)
        clip = clips[case['clip_id']]
        entries.append({
            'id': case['id'], 'operation': f'{case["mode"]} / {case["operation"]}',
            'title': f'{case["mode"]} / {case["operation"]} · {case["id"]}',
            'request': json.dumps(case['parameters'], ensure_ascii=False, sort_keys=True),
            'before': before.relative_to(GALLERY).as_posix() if before else None,
            'after': after.relative_to(GALLERY).as_posix() if after else None,
            'automatic_qa_pass': bool(row.get('automatic_qa_pass')),
            'human_review': row.get('semantic_success'),
            'source_clip': clip['id'],
        })
    js = '// Generated from a real, nonsimulated showcase run. Human review remains separate.\n'
    js += 'window.AUK_AUDIO_REVIEW = ' + json.dumps(entries, ensure_ascii=False, indent=2) + ';\n'
    (GALLERY / 'review_data.js').write_text(js)
    print(f'Exported {len(entries)} cases: {sum(bool(x["after"]) for x in entries)} QA-passing outputs with audio.')
    print(f'Open {GALLERY / "index.html"} in a browser to review them.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', help='Colab showcase run directory, containing requests.jsonl')
    parser.add_argument('manifest', help='Frozen cases.json used for that run')
    parser.add_argument('--replace', action='store_true', help='Replace existing generated audio assets')
    args = parser.parse_args()
    export_audio(args.run_dir, args.manifest, replace=args.replace)


if __name__ == '__main__':
    main()
