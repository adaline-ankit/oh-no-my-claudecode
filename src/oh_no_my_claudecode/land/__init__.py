"""PR landing feature — auto-discovered at ``onmc land``.

Provides a safe, automated PR landing loop that:

- Polls merge-state and check runs via ``gh``.
- Rebases when the branch is behind the target.
- Resolves advisory review threads (Sourcery) that block merge.
- Squash-merges when the quality matrix is green and CodeQL has not failed.
- Defers when repo CI contention exceeds a caller-configured ceiling.

Modules
-------
planner   — pure ``next_step(pr_state) -> Step`` function, zero I/O.
driver    — ``land(pr, *, gh, …)`` loop driven by an injectable ``GhProtocol``.
commands  — CLI surface (``register(app)``), auto-discovered by the registry.
"""
