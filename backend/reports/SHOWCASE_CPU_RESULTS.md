# Showcase CPU validation — 2026-10-19

393 tests discovered: 392 passed, one skipped on macOS (Python 3.11.15,
NumPy 1.26.4, FFmpeg/FFprobe available). Runtime: 116.494 seconds.

The skipped test is the existing
`test_original.ArtifactTests.test_local_server_hard_stop`, which uses Linux
`/proc` to verify process ownership. Its Linux implementation was not changed.
Local HTTP integration tests ran with loopback access enabled. The full suite
is also configured in `.github/workflows/tests.yml` for Ubuntu/Python 3.11.

New coverage: 90 operation scenarios (ten per operation across voice and
transcript editing), and 12 showcase-selection/execution checks. Scenario
tests exercise the worker with real WAV/FFmpeg processing and simulated model
responses plus canned ASR/speaker scores. No GPU generation or human listening
quality is established by this CPU result.

Command from the repository root, using the existing Python 3.11 environment:

```python
import sys, unittest
import test_original
if sys.platform != 'linux':
    test_original.ArtifactTests.test_local_server_hard_stop = unittest.skip(
        'Linux /proc process ownership contract'
    )(test_original.ArtifactTests.test_local_server_hard_stop)
suite = unittest.defaultTestLoader.discover('backend/tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
```

Set `PYTHONPATH=backend:backend/tests` when running the above snippet. This
platform skip was applied in the invoking process; existing test files and
production behavior were not modified.
