"""Durable checkpoint/resume for onmc loop runs.

After each iteration the engine persists the full loop state to a small JSON
file under ``.onmc/loop-state/<sha8>.json``.  The file name is derived from a
SHA-256 of ``goal + verify_command`` so the same logical run always maps to the
same file, regardless of other flags.

The file is written atomically: the engine writes to a ``.tmp`` sibling then
renames it into place, so an interrupted write never corrupts a previously good
checkpoint.

When ``--resume`` is passed (or ``OnmcService.loop(resume=True)``) the engine:

1. Loads the checkpoint for the matching sha8.
2. Skips iterations 1..N (where N = iterations already recorded).
3. Continues from iteration N+1 with all prior state intact (consecutive_losses,
   signature_counts, recorded_memory_ids, etc.).

On converged or terminal stop the checkpoint is removed.  A partial run
(e.g. wall-time, cost) leaves the checkpoint in place so a later ``--resume``
can continue it.

Checkpoint JSON schema (version "1")
--------------------------------------
::

    {
      "schema_version": "1",
      "goal": "<full goal text>",
      "verify_command": "<verify command>",
      "iterations": [<IterationContract as dict>, ...],
      "recorded_memory_ids": ["mid1", ...],
      "total_tokens": 42,
      "total_cost_usd": 0.05,
      "consecutive_losses": 2,
      "escalation_level": 1,
      "signature_counts": {"abc123": 1, ...},
      "consecutive_same_error": 0,
      "last_error_head": "FAILED: ..."
    }

Design note
-----------
The store is extracted into a Protocol so tests can inject an in-memory fake
without touching the filesystem.  ``FileCheckpointStore`` is the default; tests
use ``InMemoryCheckpointStore``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from oh_no_my_claudecode.loop.models import IterationContract

_SCHEMA_VERSION = "1"
_CHECKPOINT_DIR_NAME = "loop-state"


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _loop_spec_sha8(goal: str, verify_command: str) -> str:
    """Return the first 8 hex chars of SHA-256(goal + "||" + verify_command)."""
    digest = hashlib.sha256(f"{goal}||{verify_command}".encode()).hexdigest()
    return digest[:8]


# ---------------------------------------------------------------------------
# State snapshot (what we persist after each iteration)
# ---------------------------------------------------------------------------


class CheckpointState:
    """Mutable snapshot of mid-run loop state.

    The engine reads this on resume and writes it after every iteration.
    All fields correspond 1:1 to local variables inside ``run_loop``.
    """

    __slots__ = (
        "goal",
        "verify_command",
        "iterations",
        "recorded_memory_ids",
        "total_tokens",
        "total_cost_usd",
        "consecutive_losses",
        "escalation_level",
        "signature_counts",
        "consecutive_same_error",
        "last_error_head",
    )

    def __init__(
        self,
        *,
        goal: str,
        verify_command: str,
        iterations: list[IterationContract],
        recorded_memory_ids: list[str],
        total_tokens: int,
        total_cost_usd: float,
        consecutive_losses: int,
        escalation_level: int,
        signature_counts: dict[str, int],
        consecutive_same_error: int,
        last_error_head: str | None,
    ) -> None:
        self.goal = goal
        self.verify_command = verify_command
        self.iterations = iterations
        self.recorded_memory_ids = recorded_memory_ids
        self.total_tokens = total_tokens
        self.total_cost_usd = total_cost_usd
        self.consecutive_losses = consecutive_losses
        self.escalation_level = escalation_level
        self.signature_counts = signature_counts
        self.consecutive_same_error = consecutive_same_error
        self.last_error_head = last_error_head

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict ready for JSON encoding."""
        return {
            "schema_version": _SCHEMA_VERSION,
            "goal": self.goal,
            "verify_command": self.verify_command,
            "iterations": [asdict(c) for c in self.iterations],
            "recorded_memory_ids": self.recorded_memory_ids,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "consecutive_losses": self.consecutive_losses,
            "escalation_level": self.escalation_level,
            "signature_counts": self.signature_counts,
            "consecutive_same_error": self.consecutive_same_error,
            "last_error_head": self.last_error_head,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CheckpointState:
        """Deserialise from a plain dict (e.g. loaded from JSON)."""
        raw_iterations: list[dict[str, Any]] = data.get("iterations", [])
        iterations = [
            IterationContract(
                iteration=c["iteration"],
                prediction=c["prediction"],
                action_summary=c["action_summary"],
                files_touched=c["files_touched"],
                verify_passed=c["verify_passed"],
                verify_output=c["verify_output"],
                outcome=c["outcome"],
                tokens=c.get("tokens"),
                route_decision=c.get("route_decision"),
            )
            for c in raw_iterations
        ]
        return cls(
            goal=data["goal"],
            verify_command=data["verify_command"],
            iterations=iterations,
            recorded_memory_ids=data.get("recorded_memory_ids", []),
            total_tokens=data.get("total_tokens", 0),
            total_cost_usd=data.get("total_cost_usd", 0.0),
            consecutive_losses=data.get("consecutive_losses", 0),
            escalation_level=data.get("escalation_level", 0),
            signature_counts=data.get("signature_counts", {}),
            consecutive_same_error=data.get("consecutive_same_error", 0),
            last_error_head=data.get("last_error_head"),
        )


# ---------------------------------------------------------------------------
# CheckpointStore Protocol
# ---------------------------------------------------------------------------


class CheckpointStore(Protocol):
    """Injectable checkpoint persistence interface.

    Tests inject ``InMemoryCheckpointStore``; production uses
    ``FileCheckpointStore``.
    """

    def save(self, sha8: str, state: CheckpointState) -> None:
        """Atomically persist *state* keyed by *sha8*."""
        ...

    def load(self, sha8: str) -> CheckpointState | None:
        """Load state for *sha8*, or return ``None`` if none exists."""
        ...

    def clear(self, sha8: str) -> None:
        """Delete the checkpoint for *sha8* (idempotent)."""
        ...


# ---------------------------------------------------------------------------
# File-based implementation (production default)
# ---------------------------------------------------------------------------


class FileCheckpointStore:
    """Persists checkpoints as JSON files under ``.onmc/loop-state/``."""

    def __init__(self, repo_root: Path) -> None:
        self._dir = repo_root / ".onmc" / _CHECKPOINT_DIR_NAME

    def _path(self, sha8: str) -> Path:
        return self._dir / f"{sha8}.json"

    def save(self, sha8: str, state: CheckpointState) -> None:
        """Atomically write *state* to disk (write-then-rename)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        target = self._path(sha8)
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, target)  # atomic on POSIX and Windows (Python 3.3+)
        except Exception:  # noqa: BLE001
            # Best-effort: never abort the loop because a checkpoint write failed.
            with contextlib.suppress(Exception):
                tmp.unlink(missing_ok=True)

    def load(self, sha8: str) -> CheckpointState | None:
        """Load from disk; returns ``None`` when no checkpoint exists."""
        path = self._path(sha8)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return CheckpointState.from_dict(data)
        except Exception:  # noqa: BLE001
            return None

    def clear(self, sha8: str) -> None:
        """Delete the checkpoint file (idempotent)."""
        with contextlib.suppress(Exception):
            self._path(sha8).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# In-memory implementation (for tests)
# ---------------------------------------------------------------------------


class InMemoryCheckpointStore:
    """In-memory checkpoint store for deterministic tests."""

    def __init__(self) -> None:
        self._data: dict[str, CheckpointState] = {}

    def save(self, sha8: str, state: CheckpointState) -> None:
        """Store a deep copy (round-trips through dict serialisation)."""
        self._data[sha8] = CheckpointState.from_dict(state.to_dict())

    def load(self, sha8: str) -> CheckpointState | None:
        """Return the saved state, or ``None``."""
        raw = self._data.get(sha8)
        if raw is None:
            return None
        # Return a fresh copy to avoid aliasing bugs in tests.
        return CheckpointState.from_dict(raw.to_dict())

    def clear(self, sha8: str) -> None:
        """Remove the entry (idempotent)."""
        self._data.pop(sha8, None)

    @property
    def stored_keys(self) -> list[str]:
        """Return all currently stored sha8 keys (for test assertions)."""
        return list(self._data.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    "CheckpointState",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
    "_loop_spec_sha8",
]
