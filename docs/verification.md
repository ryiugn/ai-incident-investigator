# Verification — 7 October 2026

Fresh checks were run against the clean public copy on Windows with Python 3.12.14,
Node 22.20.0 and npm 10.9.3. A new virtual environment was installed from the Python
lockfile, the package was installed editable, and npm dependencies were installed with
`npm ci`. No original benchmark data, credentials or user archives were used.

| Check | Result |
| --- | --- |
| Fresh Python lockfile and editable installation | Passed |
| `python -m pip check` | No broken requirements |
| Full Python suite in the fresh environment | **133 passed, 6 skipped** (30.83 seconds) |
| TypeScript check and Vite production build | Passed |
| Playwright, one worker, local scripted server | **15 passed** (22.0 seconds) |
| Documented unpaid adaptive CLI examples | Diagnosis and insufficient-evidence outcomes archived successfully; zero API spend |
| Real Anthropic requests | Not run for this release; requires a user's own key and explicit spending authorization |
| Docker HTTP/PostgreSQL fault and trace integration | Six opt-in checks skipped; not freshly verified for this release |

The label-audit tests previously depended on private benchmark files. They now generate
a tiny synthetic corpus in temporary directories; the same seven audit/attestation
regressions pass without publishing private answers. App runtime code was retained.

The Python suite includes temporary SQLite stores and subprocess crash/restart tests.
Provider transport doubles verify contracts, endpoint restrictions and reservations;
they cannot establish actual hosted availability or investigation accuracy. Browser
tests cover evidence navigation, saved runs, fixed/adaptive comparison, approvals,
decline, drafts/finalization, hypotheses, trace timelines and narrow-screen layout.
Automated review judgments are explicitly test fixtures, not real human assessments.

## Repeat ordinary checks

After the README setup, from the repository root:

```text
python -m pytest -q
python -m pip check
npm --prefix ui run build
```

Keep `RUN_LIVE` and `TRACE_ORDERS_URL` unset for ordinary tests. Tests make no paid calls.
The suite requires a writable temporary directory and permission to run subprocesses
and local sockets for recovery tests. The results above are completed test runs.

## Repeat browser checks

Chrome must be installed (the Playwright configuration uses the `chrome` channel).
In one terminal, start a dedicated unpaid server with a fresh test archive:

```text
python -m investigator.server --provider scripted-approval --archive work/browser-tests --port 18108
```

In another terminal, set the target explicitly. **Do not target a hosted/paid server.**

```powershell
$env:INVESTIGATOR_URL='http://127.0.0.1:18108'
npm.cmd --prefix ui run test:e2e -- --workers=1
```

```bash
INVESTIGATOR_URL=http://127.0.0.1:18108 npm --prefix ui run test:e2e -- --workers=1
```

These tests create investigations and test review records. Keep their archive separate
from actual work and do not interpret the generated judgments as human review.

## Optional real local integration checks

This starts a separate test stack on ports 18180, 18181 and 55434. It injects controlled
faults into that stack, not production services. Wait until the orders health endpoint
at `http://127.0.0.1:18180/health` reports ready before running the verifier.

```text
docker compose -p aii-public-test -f environment/compose.traces-test.yaml up -d --build
python -m environment.verify_local
docker compose -p aii-public-test -f environment/compose.traces-test.yaml down
```

Successful software checks do not measure model correctness, causal reasoning quality,
incident-resolution savings or production reliability. Those require separate evaluation.
