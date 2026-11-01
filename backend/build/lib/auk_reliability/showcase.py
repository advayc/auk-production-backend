"""Small, source-balanced demo batches. These are not acceptance benchmarks."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .acceptance import run_acceptance_suite
from .core import atomic_json, canonical_hash
from .dataset import validate_dataset
from .policy import ACTIVE_MODES, OPERATIONS, selected_modes


def select_cases(audit, *, per_operation=10, modes=None):
    """Cover every selected operation, preferring unused speakers and recordings.

    Seed/profile changes alone do not count as new demonstrations. Missing
    coverage is an error, so a short batch cannot masquerade as 10 per operation.
    """
    modes = selected_modes(modes)
    if any(m not in ACTIVE_MODES for m in modes):
        raise ValueError('Showcase covers voice_editor and transcript_editor only')
    if type(per_operation) is not int or per_operation < 1:
        raise ValueError('per_operation must be a positive integer')
    if not audit['valid']:
        raise ValueError('Dataset preflight failed: ' + str(audit['errors']))
    selected = []
    for mode in modes:
        for operation in OPERATIONS[mode]:
            unique = {}
            for case in audit['requests']:
                if (case['mode'], case['operation']) != (mode, operation):
                    continue
                clip = audit['clips'][case['clip_id']]
                params = {k: v for k, v in case['parameters'].items()
                          if k not in ('seed', 'profile')}
                key = canonical_hash({'source': clip['sha256'], 'parameters': params})
                if key not in unique or case['id'] < unique[key]['id']:
                    unique[key] = case
            pool = list(unique.values())
            if len(pool) < per_operation:
                raise ValueError(f'{mode}/{operation}: need {per_operation} distinct cases; found {len(pool)}')
            speakers, sources = Counter(), Counter()
            for _ in range(per_operation):
                def rank(case):
                    clip = audit['clips'][case['clip_id']]
                    return (sources[clip['sha256']], speakers[clip['labels']['voice_id']], case['id'])
                case = min(pool, key=rank)
                pool.remove(case)
                clip = audit['clips'][case['clip_id']]
                sources[clip['sha256']] += 1
                speakers[clip['labels']['voice_id']] += 1
                selected.append(deepcopy(case))
    return selected


def prepare_showcase(manifest, destination, *, per_operation=10, modes=None):
    """Freeze reviewed cases and absolute source paths before spending GPU time."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    audit = validate_dataset(manifest, acceptance=False, modes=modes)
    cases = select_cases(audit, per_operation=per_operation, modes=modes)
    used = {c['clip_id'] for c in cases}
    data = deepcopy(audit['data'])
    data['clips'] = [{k: v for k, v in c.items() if k != 'duration'}
                     for cid, c in audit['clips'].items() if cid in used]
    data['requests'] = cases
    data['showcase'] = {'source_manifest_sha256': audit['manifest_sha256'],
                        'per_operation': per_operation, 'acceptance_benchmark': False}
    atomic_json(destination, data)
    return cases


def run_showcase(worker, manifest, output_dir, *, resume=False, checkpoint=None,
                 wall_clock_budget_seconds=None):
    """Exactly one attempt per case; retain failed cases and human-review status."""
    if worker.max_attempts != 1:
        raise ValueError('Create a dedicated showcase worker with max_attempts=1')
    if worker.runtime_profile.get('simulation') is not False:
        raise ValueError('Real demo generation requires an explicitly nonsimulated runtime')
    data = json.loads(Path(manifest).read_text())
    count = data.get('showcase', {}).get('per_operation')
    modes = tuple(dict.fromkeys(c['mode'] for c in data['requests']))
    audit = validate_dataset(manifest, acceptance=False, modes=modes)
    expected = select_cases(audit, per_operation=count, modes=modes)
    if len(expected) != len(data['requests']):
        raise ValueError('Frozen showcase contains extra or duplicate cases')
    deadline = worker.deadline
    try:
        return run_acceptance_suite(
            worker, manifest, output_dir, acceptance=False, modes=modes,
            resume=resume, checkpoint=checkpoint,
            wall_clock_budget_seconds=wall_clock_budget_seconds)
    finally:
        worker.deadline = deadline


def display_showcase(output_dir):
    """Inline before/after players, including failed-attempt diagnostics."""
    from IPython.display import Audio, Markdown, display
    for line in (Path(output_dir) / 'requests.jsonl').read_text().splitlines():
        row = json.loads(line)
        display(Markdown(f"### {row['case_id']} — {row['mode']}/{row['operation']}"))
        print('Technical:', row['technical_success'], '| Automatic QA:', row['automatic_qa_pass'],
              '| Human review:', row.get('semantic_success'), '| Reason:', row.get('reason'))
        folder = Path(row['request_dir']) if row.get('request_dir') else None
        before = folder / 'input.wav' if folder else None
        if before and before.is_file():
            print('Before (selected input interval)')
            display(Audio(filename=str(before)))
        if row.get('output_path'):
            print('After — listen for the requested effect, correct words, identity, and seams')
            display(Audio(filename=row['output_path']))
        else:
            print('No QA-passing output selected. Inspect attempts in', row.get('request_dir'))
