# AI Incident Investigator

A local incident-investigation workbench for engineers: collect operational evidence,
compare fixed and adaptive workflows, and inspect every report's supporting sources.

**Run a real model with your own Anthropic API key, or explore the interface using an
unpaid scripted demo.** The application runs on your computer. Hosted-model mode sends
selected alert/evidence content to Anthropic; it does not host this web application.

**Status: in progress.** The engineering workflow is implemented, but diagnostic
accuracy and a fixed-versus-adaptive winner have not been established. This portfolio
project demonstrates evidence-based investigation workflows and their engineering
tradeoffs. It is not a production incident-response service.

## What it does

- Investigates a frozen incident snapshot using logs, metrics, changes, runbooks and traces.
- Runs a six-query fixed checklist or an adaptive LangGraph investigation.
- Validates structured model outputs and binds citations to immutable evidence records.
- Enforces query, token, time and local spending limits.
- Saves interactive adaptive investigations in SQLite, including exact-query approvals.
- Shows hypotheses, a UTC event timeline, evidence details and comparable run usage.
- Explains LangGraph through recorded steps, actual routes, state changes and evidence links.
- Supports human atomic-claim review, draft persistence and explicit final attestation.

It suggests next checks; it does not execute remediation. Citation integrity is checked
in code; whether a source actually supports a claim requires separate human review.

See the [demo guide](docs/demo.md) and
[verification record](docs/verification.md) for a reproducible portfolio demonstration.

## Quick start

Requirements: Python 3.12+, Node.js 22.12+ with npm, and Git. Docker is optional and is
needed only to generate fresh incidents in the local laboratory or run its integration checks.
Run all commands from the repository root.

```text
git clone https://github.com/ryiugn/ai-incident-investigator.git
cd ai-incident-investigator
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

If PowerShell blocks activation, use `.\.venv\Scripts\python.exe` instead of `python`
in the commands below. If it blocks npm's PowerShell wrapper, use `npm.cmd`.

```text
python -m pip install -r requirements.lock.txt
python -m pip install --no-deps -e .
npm --prefix ui ci
npm --prefix ui run build
```

### Run with your own API key

Obtain a direct Anthropic API key and configure your own account spending controls.
The adapter supports `claude-haiku-4-5-20251001` at the official Anthropic endpoint.
Other providers, proxy endpoints and arbitrary model IDs are not supported.

Set the key in the current terminal without putting it into source code:

```powershell
# PowerShell 7+: masked prompt, no literal key in command history
$env:ANTHROPIC_API_KEY = Read-Host 'Your Anthropic API key' -MaskInput
```

```bash
# Bash: hidden prompt, no literal key in command history
read -rsp 'Your Anthropic API key: ' ANTHROPIC_API_KEY; echo
export ANTHROPIC_API_KEY
```

For other shells, use their environment-variable mechanism. `.env.example` documents
the setting; the server does **not** automatically read `.env` files.

Choose an explicit ceiling in US dollars. The example allocates **$1** to this local ledger:

```text
python -m investigator.server --provider anthropic --approved-budget-usd 1 --archive archive/hosted --ledger archive/hosted/provider-spend.json --port 18090
```

Open **http://127.0.0.1:18090**. Check that the page says **Hosted model enabled**.
Select a replay and click **Start investigation**. Each hosted investigation can incur
API charges, even when evidence is missing or a report cannot be completed.

The key stays in the server process; the browser never accepts it. The server sends
selected evidence to Anthropic and saves report/evidence/request archives locally.
Use synthetic or appropriately sanitized data. Keep the same ledger and ceiling on
restart. Never delete or reset the ledger to bypass its cap. Unknown usage remains
reserved. This is a local estimated cap, not an account-wide billing guarantee.
See [configuration and data handling](docs/configuration.md).

### Unpaid demo and interview fallback

Stop the hosted server with Ctrl+C, then run:

```text
python -m investigator.server --provider scripted-approval --archive archive/demo --port 18090
```

This uses no API key or model calls. Try the dependency-timeout, missing-evidence,
trace and approval fixtures. Demo/stress data are handcrafted. Scripted reports follow
Python rules and demonstrate software behavior, not LLM diagnostic ability.

The [five-minute demo guide](docs/demo.md) covers citations, comparisons, human review,
timelines, approvals and restart recovery. The CLI also supports unpaid replay:

```text
python -m investigator.cli --workflow adaptive --archive archive/cli-demo
python -m investigator.cli --workflow adaptive --missing --archive archive/cli-demo
```

## Architecture

```text
React interface -> FastAPI local queue
                       |-- fixed: predefined collection -> report
                       `-- adaptive: LangGraph decisions -> guards -> tools -> reassess
                                            |                  |
                                  SQLite checkpoint       frozen snapshot
                                  and approval journal    + evidence registry
                                            `-------> cited report -> human review
```

The five tools are `query_logs`, `query_metrics`, `get_changes`, `search_runbooks`,
and `query_traces`. They query validated snapshots, not arbitrary SQL, shell commands
or URLs. The original fixed schedule uses the first four tools. The model can propose
an action, but application validation controls execution.

Expanded queries inside the snapshot horizon require approval in interactive adaptive
runs. Queries outside that horizon are rejected. Completed journal output bridges a
crash before the graph checkpoint; an uncertain dispatched call cannot be retried
automatically. Standalone CLI/evaluation runs and fixed runs are not resumable.

See [architecture and tradeoffs](docs/architecture.md) and
[LangGraph and recovery](docs/langgraph.md).

## Generate fresh local incident evidence

The optional laboratory runs an orders service, PostgreSQL and a shipping service.
It deliberately injects faults and measures their observable signatures. It is separate
from the read-only investigator.

```text
docker compose up -d --build --wait
python -m environment.capture dependency_timeout --output captures/latest
```

Click **Refresh captures** in the UI. The server reads `captures/*/case.json`.
The controller checks healthy baseline requests, injects a fault, freezes observations,
and verifies recovery after cleanup. It also writes `private-label.json`, which belongs
to the evaluator and is not passed to the investigator. Captures are ignored by Git.
Other recipes: `lock_contention`, `pool_exhaustion`, `slow_query`, `config_error`.

```text
docker compose down
```

The local database uses an explicitly demo-only credential in Compose and the capture
controller. These are disposable local services; do not expose them publicly.

## Verification and evaluation

```text
python -m pytest -q
python -m pip check
npm --prefix ui run build
```

The default Python suite makes no paid model calls. Live laboratory checks are opt-in.
Browser checks must target a dedicated scripted server, never your hosted server.
See [test commands and fresh verification results](docs/verification.md).

Private benchmark answers, the historical captured corpus, generated results, named
human reviews, local databases and original Git history are excluded from this public
export. The built-in demos work without them. Evaluation code remains available for
generating a new local corpus; its data and human audit requirements are described in
[evaluation methodology](docs/evaluation.md). The Benchmark screen is initially empty.

## Limitations and next steps

- Real-model integration was exercised during earlier development; this public copy
  has not been retested with paid requests. Hosted tests use deterministic transport doubles.
- No reviewed benchmark establishes diagnostic accuracy, operational savings or an
  adaptive advantage. Passing tests validate software behavior, not investigation quality.
- Evidence selection uses a 16,000-character cap in collection order and can omit useful data.
- Only local single-user operation is supported. There are no accounts, production
  authentication, tenant isolation or public deployment configuration.
- OpenTelemetry recording is local, bounded and manually instrumented. Missing or
  in-flight spans make coverage incomplete. Database spans are client-side operations.
- The captured laboratory is small and synthetic. It is not production incident evidence.
- Next steps are human label/claim audits, separately authorized hosted tests and a
  frozen evaluation protocol before making performance claims.

## Repository map

| Path | Responsibility |
| --- | --- |
| `src/investigator/` | Contracts, tools, providers, workflows, persistence, API and review |
| `ui/` | React/TypeScript interface and browser tests |
| `environment/` | Local fault laboratory, capture controller and trace recorder |
| `benchmark/` | Evaluation and human label-audit code; generated data remain private |
| `tests/` | Offline regression tests and opt-in local integration checks |
| `runbooks/` | Shared troubleshooting references |
| `docs/` | Architecture, setup, demo, testing and evaluation |

## License and attribution

No project license has been selected. Public visibility does not grant a general
open-source reuse license. Dependencies retain their own licenses; see
[dependency attribution](docs/dependencies.md). No third-party libraries are vendored.
