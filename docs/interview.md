# Explain and demonstrate the investigator

## 60–90 second introduction

AI Incident Investigator is a local workbench for investigating a frozen incident
snapshot. It asks whether adaptive evidence collection can produce more useful,
supported reports than a fixed checklist. That research question is still open.

Both workflows use constrained read-only tools for logs, metrics, changes, runbooks
and traces. The fixed baseline follows six queries. Adaptive investigation uses
LangGraph to route model decisions through guards, collection and reassessment.
Application code validates arguments, enforces budgets and checks that citations
refer to evidence actually supplied to the model.

Interactive adaptive runs can pause for approval before expanding a query window.
LangGraph checkpoints and an application journal preserve state. If an external call's
outcome is unknown after interruption, its reservation remains and automatic replay is
blocked. The interface lets me step through recorded execution and inspect the evidence.

A valid evidence ID does not prove a claim is true. The unpaid demo proves orchestration;
real-provider operation and diagnostic quality require separate verification and review.

Add a personal contribution sentence only after identifying what you personally designed,
implemented, tested and reviewed. Do not infer sole authorship or manual contribution
from repository ownership. Explain the use of AI assistance accurately.

## Five-minute walkthrough

| Time | Action | Explain |
|---|---|---|
| 0:00–0:40 | Start the dependency demo, adaptive | Handcrafted frozen evidence and scripted provider; no API spend. Symptom is not diagnosis. |
| 0:40–1:40 | Workflow: triage, guard, collect | Actual route, proposed query, new evidence and budget counters. Retained decisions are not new model calls. |
| 1:40–2:20 | Open step evidence | Inspect payload and coverage. Empty samples are not zero; source IDs establish integrity, not support. |
| 2:20–3:00 | Report/citations, hypotheses and timeline | Separate collection order from UTC event time and observations from causal claims. |
| 3:00–3:50 | Expanded-window demo and approval controls | Exact query saved; approval resumes the same thread. Decline leaves a limitation. Restart only with the same provider/archive. |
| 3:50–4:30 | Fixed run and Workflow comparison | Same case, provider and configuration. Compare tools, requests, latency and estimated cost without naming a winner. |
| 4:30–5:00 | State ownership and stopping | LangGraph routes/checkpoints; application code owns permissions, budgets and validation. Explain unknown outcomes and evaluation gaps. |

## Interview questions and accurate answers

**Why LangGraph instead of a while loop?** A loop could implement standalone policy.
LangGraph makes transitions explicit and supplies checkpoint/interrupt/resume primitives
for approval. It adds serialization/recovery complexity; it does not replace safety code.

**What are the nodes and edges?** Standalone: validate_alert, triage, guard_action,
collect_evidence, assess, finalize. Interactive adds human_approval. Assess goes back
through guard_action. Guards collect, request approval, provide validation feedback or
finalize. Exhaustion also routes to finalization. See `graph.py:build_graph` and
`durable_graph.py:build_durable_graph` under `src/investigator`.

**What is state?** Standalone graph state holds a route; RunContext lives in a closure.
Durable state holds a versioned investigation dictionary captured by `checkpoint_state.py`.
Evidence, usage, caches, hypotheses and decisions are application data. Clients, keys
and locks are runtime objects and are reconstructed.

**Who chooses and bounds tools?** Adaptive model output proposes one structured action.
Application code validates tool, schema, service, scope and limits. There is no shell,
SQL, arbitrary URL or fault-control tool. Fixed collection uses `baseline.py:schedule`.

**How does resume work?** Expanded queries interrupt before collection. The approval
token binds the exact query to revision/checkpoint. A receipt persists before
Command(resume=...). Approval does not override hard limits. See `checkpoint.py:drive`.

**What if a call fails?** Standalone tool timeouts have bounded retries. Interactive
uncertain dispatches retain reservations and block automatic retry. Invalid output
gets at most one shared repair. Failed finalization produces an operational partial
outcome. See `runner.py:model`, `dispatch` and `finalize`.

**Is it exactly once?** No. The journal bridges completed-output/checkpoint crash gaps,
but cannot know what happened externally during a crash. It refuses uncertain replay.

**What does a citation prove?** An immutable registered record was supplied to that
request. Semantic support is separate. One timeout log supports an observed timeout,
not an increased error rate without request/error counts and a comparison interval.

**Why reject comparisons?** `comparison.py:compare_runs` requires matching snapshot,
alert, configuration and provider plus one fixed/one adaptive run. Disjoint incident
timeframes cannot support a common incident comparison. Compatible runs remain
descriptive until actual evaluation/review supports a quality conclusion.

**Does adaptive win?** Not established. Fewer tools can coexist with more model calls,
latency or cost. Retain all scheduled failures and analyze capture groups rather than
treating variants/repeats as independent observations.

**Main limitations?** Short synthetic captures, finite local trace buffers, collection-
order evidence truncation, single-user execution, no production authentication or
remediation, and incomplete empirical evaluation.

## Understanding checkpoints — one at a time

1. A shipping timeout is observed. What can you say, and what remains unknown?
2. Why include a revision and checkpoint ID in an approval token?
3. Why retain a reservation after an unknown provider outcome?
4. How can a valid citation support an incorrect claim?
5. Why are repeated variants from one capture not independent cases?

Answer in your own words before checking the explanations above. Use dedicated
walkthrough checkpoints so implementation can continue between discussions.
