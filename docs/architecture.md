# Architecture and engineering decisions

## Boundaries

The optional capture controller sends requests to orders, which accesses PostgreSQL
and shipping. Orders records logs and raw metric samples; manual OpenTelemetry spans
cover requests, pool acquisition, database calls and shipping. Capture freezes a time
window and attaches shared runbooks. The investigator receives this public snapshot,
not the controller's private fault recipe or benchmark answer.

React calls the FastAPI API to list cases, start and inspect runs, navigate citations,
review claims and compare runs. The API maintains a bounded local queue. Fixed work
uses `run_investigation`; interactive adaptive work uses `Investigations` and a durable
LangGraph. Standalone adaptive CLI/evaluator work uses the non-resumable graph.

## Evidence and tools

`contracts.py` and `snapshot.py` validate allowed fields, services, identifiers and
timezone-aware windows. `telemetry.py` supplies five constrained read-only tools.
There is no arbitrary shell, SQL, filesystem, URL or fault-control tool.

`evidence.py` hashes canonical content, snapshot namespace, source identities and
provenance into stable evidence IDs. The registry stores serialized content and returns
copies. A log keeps its ID across overlapping queries; aggregate metric IDs include
the window, aggregation settings and source lineage. IDs provide integrity, not semantic support.

Durations are raw observations even where names end in `_p95`; query-time buckets use
nearest-rank p95. Event counts are summed; sampled gauges use max. Missing buckets are
explicit gaps. Empty samples do not mean measured zero.

## Providers and validation

`ScriptedProvider` implements deterministic example logic. `AnthropicProvider` uses
the SDK's structured JSON output, with retries disabled. The provider-facing schema
is transformed for compatibility; the original Pydantic contract is checked afterward.
Only current-request evidence IDs may appear in citations. One output repair is shared
across a run. A failed final assessment produces an explicit operational error report.

`RunContext.payload()` selects up to 16,000 characters of evidence in collection order
and reports omissions. This predictable policy may exclude later useful observations.
The prompt treats evidence text as untrusted; application tool validation remains the
enforced boundary if the model follows malicious instructions embedded in a log.

## Resource and execution policy

Default maximums: 8 tool dispatches, 10 model requests, 30,000 input tokens, 5,000 output
tokens and 90 seconds active time. Tools have a 3-second timeout and provider calls a
20-second timeout. One model request and 1,000 output tokens are reserved for reporting;
the remaining input/time budget can still prevent finalization.

The fixed checklist performs logs, three metric groups, changes over the snapshot
horizon and keyword runbook search. It does not automatically request traces.
Adaptive runs loop through triage, guards, collection and reassessment. Duplicate
queries use the cache, and two no-progress steps stop the loop.

Interactive adaptive window expansion requires exact human approval, within the frozen
horizon. SQLite plus an execution journal preserves state. Unknown dispatch outcomes
retain reservations and block automatic replay. OS locks serialize execution across
processes; review writes use revisions to reject stale saves. See [LangGraph](langgraph.md).

## Human review and comparison

`review.py` inventories report prose. Humans split factual text into atomic claims,
classify support and cite evidence. Finalization requires complete judgments, a name
and an explicit attestation. The code enforces submission completeness, not reviewer
expertise or the truth of the judgment. Drafts and revisions are kept in SQLite and
bound to exact report/evidence hashes.

`comparison.py` requires matching snapshot, alert and configuration fingerprints,
matching provider, and one fixed/one adaptive run for a compatible pair. It displays
resources, evidence and review coverage without inferring a winner or benchmark accuracy.

Hypotheses have stable IDs and update histories. `timeline.py` displays UTC event time,
metric intervals/gaps, trace spans, alert boundaries and expanded windows. Collection
order is separate; temporal proximity alone cannot establish causation.

## Scope limitations

Workflow now exposes completed node boundaries and fixed checklist steps, including
actual routes, evidence inputs, outcomes, decision provenance and state changes. Links
lead to run-scoped evidence, report citations, hypotheses and the UTC timeline. Playback
is collection order; the timeline is observation time. See [LangGraph](langgraph.md).
The records add local serialization overhead. This remains a bounded local workbench,
not a streaming distributed tracing service. Historical missing metadata stays missing.

No production authentication, accounts, streaming, background live monitoring or
remediation. Captures are short and synthetic. Trace buffers are bounded and local;
cutoff overlap, in-flight work, missing parents, unavailable services, overflow and
recorder restarts make coverage incomplete. Database spans describe client operations,
not server execution plans. Hosted integration and diagnostic evaluation are separate
questions; the current release does not claim production reliability or model accuracy.
