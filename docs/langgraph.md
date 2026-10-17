# LangGraph and durable recovery

`graph.py:build_graph()` is the standalone adaptive graph. Its typed state holds only
the next route; `RunContext` owns data through closures. It is not resumable.

`durable_graph.py:build_durable_graph()` is the interactive graph. Its state contains a
versioned investigation dictionary. `checkpoint_state.py` validates/captures/restores
the public snapshot, evidence, hypotheses, actions, cache, budgets and report. Runtime
clients, connections, keys and locks are rebuilt, not serialized.

```text
validate_alert -> triage -> guard_action -> collect_evidence -> assess
                              ^                                  |
                              `----------------------------------'
                              +-> human_approval -> collect or finalize
                              `-> finalize -> end
```

The actual implementation routes reassessment decisions back through `guard_action`.
Each valid proposed action passes tool/schema/scope checks before dispatch. An action
can finalize, abstain or collect. Invalid arguments produce bounded feedback. A valid
query outside the alert but within the snapshot interrupts before execution.

The approval token binds the exact canonical query to a run revision and LangGraph
checkpoint ID. `interrupt()` pauses the approval node. `Command(resume=...)` delivers
the accepted decision. Decline finalizes with an explicit limitation. The approval
node performs no external calls before the interrupt because interrupted nodes replay.

`checkpoint.py:Investigations` uses `AsyncSqliteSaver`, sync durability, an application
execution journal, approval receipts and a nonblocking OS lock. The journal saves
reservations before calls and completed output before the separate graph checkpoint.
If execution restarts in that gap, completed output is reused. If the journal still
says dispatching, the outcome is uncertain: reservations are retained and repetition
is blocked. This is conservative recovery, not an exactly-once guarantee.

Startup restores pending approvals and identifies interrupted work. Resume requires
the same provider and spending ledger binding. Unsupported versions, corrupted state
and missing ledger data report recovery limitations. Execution is serialized for the
local store; it is not a distributed worker service.

See `tests/test_checkpointing.py` for real temporary SQLite and subprocess crash,
approval and concurrency tests. The tests use scripted providers or transport doubles.

## Recorded playback

Workflow extends the node-entry path with completed-boundary records from
`execution.py`: sequence, node, outgoing route, before/after usage and evidence IDs,
new tool events, model-request evidence IDs, report status and hypotheses. Decisions
are identified as produced here or retained from an earlier step. These are observable
outputs, not hidden model reasoning. Raw prompts, keys and evaluator labels are excluded.

Standalone `graph.py` wraps nodes. Interactive `durable_graph.py` records only after
a node returns, then journals the record with its output before the graph checkpoint.
Journal replay reuses saved output without appending another step. Approval interrupts
and unknown dispatch outcomes exit before recording completion. Fixed collection records
returned checklist queries and finalization explicitly outside LangGraph.

Older checkpoints default to an empty `execution_steps` list. Historical entry paths
are never reconstructed into fictional outcomes. A completed boundary means the node
returned, not that a tool succeeded or a diagnosis is correct. Errors, empty/partial
coverage and invalid-argument feedback remain visible. Model input IDs distinguish
supplied evidence from registered records omitted by the 16,000-character policy.

Playback never executes nodes or approves queries. Highlights refer to the selected
recorded boundary, not inferred live activity. Run changes reset playback and evidence.
API polling preserves newer worker completion when it overlaps checkpoint inspection.
