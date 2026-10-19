# @title Showcase: 10 per operation, single attempt, before/after playback
"""Run in the prepared notebook with %run -i /path/to/showcase_colab.py.

Install this checkout's backend first. The original notebook's embedded package
does not contain showcase.py. This cell reuses its models and QA callbacks.
"""
from pathlib import Path
from auk_reliability.core import LocalAuKServer
from auk_reliability.worker import ReliabilityWorker
from auk_reliability.showcase import prepare_showcase, run_showcase, display_showcase

SHOWCASE_MANIFEST = '/content/auk-public-v1/showcase_source_manifest.json'
SHOWCASE_ROOT = Path('/content/auk-showcase')
RESUME_SHOWCASE = False
PER_OPERATION = 10
WALL_CLOCK_SECONDS = 4 * 60 * 60

if 'AUK_WORKER' not in globals():
    raise RuntimeError('Run P1/P2/P4 and restore the reviewed corpus first.')
if 'CHECKPOINT' not in globals() or CHECKPOINT is None:
    raise RuntimeError('Configure the Drive checkpoint before generating the batch.')

frozen = SHOWCASE_ROOT / 'cases.json'
if not RESUME_SHOWCASE:
    prepare_showcase(SHOWCASE_MANIFEST, frozen, per_operation=PER_OPERATION)
elif not frozen.is_file():
    raise FileNotFoundError('Restore cases.json and its run directory before resuming.')

# Close the existing owner before creating another transport. Leave its retry
# configuration untouched; the showcase worker has exactly one attempt.
previous = AUK_WORKER
previous.close()
transport = LocalAuKServer(previous.adapter.binary, previous.adapter.model_dir,
                          SHOWCASE_ROOT / 'runtime', previous.limits,
                          previous.adapter.memory_saver)
AUK_WORKER = ReliabilityWorker(transport, SHOWCASE_ROOT / 'requests',
                               limits=previous.limits, semantic_gate=previous.gate,
                               runtime_profile=previous.runtime_profile, max_attempts=1)
CHECKPOINT.roots['showcase'] = SHOWCASE_ROOT.resolve()
try:
    summary = run_showcase(AUK_WORKER, frozen, SHOWCASE_ROOT / 'run',
                           resume=RESUME_SHOWCASE, checkpoint=CHECKPOINT,
                           wall_clock_budget_seconds=WALL_CLOCK_SECONDS)
    print(summary['status'], summary['overall'])
finally:
    CHECKPOINT.sync()
    AUK_WORKER.close()
display_showcase(SHOWCASE_ROOT / 'run')
