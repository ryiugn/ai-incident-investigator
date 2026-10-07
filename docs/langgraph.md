# LangGraph and durable recovery

`graph.py:build_graph()` is the standalone adaptive graph. Its typed state holds only
the next route; `RunContext` owns data through closures. It is not resumable.

`durable_graph.py:build_durable_graph()` is the interactive graph. Its state contains a
versioned investigation dictionary. `checkpoint_state.py` validates/captures/restores
the public snapshot, evidence, hypotheses, actions, cache, budgets and report. Runtime
clients, connections, keys and locks are rebuilt, not serialized.

```text
validate_alert -> triage -> guard_action -> collect_evidence -> assess
                              |                 ^                |
                              |                 `----------------'
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
