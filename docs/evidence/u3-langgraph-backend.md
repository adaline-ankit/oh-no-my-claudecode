# U3 Optional LangGraph Backend Evidence

Date: 2026-07-26

## Status

U3 now has a fail-closed optional LangGraph backend boundary over the canonical
ONMC `RunSpec`. The native backend remains the default and imports/runs without
LangGraph.

The checkout and its `uv.lock` do not contain `langgraph` or
`langgraph-checkpoint-sqlite`, and the local environment cannot import them.
Following the offline execution constraint, this change does not guess a
version, modify `pyproject.toml`, regenerate `uv.lock`, or install an optional
package from the network.

Therefore:

- ONMC-owned scheduling semantics are exercised through an injected,
  dependency-free graph driver.
- The dependency-present LangGraph/SQLite adapter is implemented behind guarded
  imports.
- Its real-library smoke test is present but skipped in this environment.
- Dependency-present parity is **not claimed as locally verified** until a
  maintainer selects and locks reviewed LangGraph and SQLite-checkpointer
  versions and runs that smoke test.

## Contract evidence

| Contract | Local evidence |
|---|---|
| Native remains default | Importing `oh_no_my_claudecode.runtime` and running `NativeExecutionBackend` succeeds with LangGraph absent. |
| Fail closed | Selecting `LangGraphExecutionBackend` without the optional packages raises `LangGraphUnavailableError` before creating or changing a run. |
| Terminal parity | The offline graph driver produces the same status, `spec_digest`, ordered `NodeResult` values, run state, and node states as the native backend. |
| Branching DAG parity | A deterministic fan-out/fan-in fixture preserves native topological result order through the offline graph driver. |
| Approval interrupt | ONMC persists the run/node approval interrupt before the handler; resume after approval invokes the side effect once; another replay reuses the result. |
| Cancellation | A persisted operator cancellation returns the same terminal state as native execution without invoking any node handler. |
| Crash replay | Crashes after `plan`, `execute`, or `verify` resume through persisted ONMC results without invoking any handler twice. |
| Idempotency authority | Node results are written under ONMC's idempotency contract before graph-level completion; replay checks those results before handler invocation. |
| Checkpoint schema | Checkpoint state carries a version and `RunSpec` digest. Unknown versions and digest mismatches fail without mutating the supplied prior state. |
| SQLite checkpoints | The guarded real driver compiles `NodeSpec` dependencies into LangGraph edges and uses a run-id-keyed SQLite checkpointer when both optional packages are importable. |

## Verification

The authoritative local commands for this branch are:

```text
PYTHONPATH=.:src .venv/bin/python -m pytest -q \
  tests/test_langgraph_backend.py \
  tests/test_runtime_contracts.py \
  tests/test_durable_runtime.py

.venv/bin/ruff check .
.venv/bin/mypy src
```

The LangGraph real-library test is expected to report one skip in this offline,
dependency-absent environment. A future dependency-locking PR must turn that
skip into a pass before advertising real LangGraph parity.
