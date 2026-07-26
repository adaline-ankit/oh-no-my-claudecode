"""Versioned, dependency-free state codec for runtime graph checkpoints."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from oh_no_my_claudecode.runtime.contracts import RuntimeContractError

CHECKPOINT_SCHEMA_VERSION = 1
_FIELDS = frozenset({"schema_version", "spec_digest", "completed_node_ids"})


class CheckpointCodecError(RuntimeContractError):
    """Raised when persisted graph state cannot be decoded safely."""


@dataclass(frozen=True, slots=True)
class RuntimeCheckpoint:
    """Validated ONMC-owned state stored inside a graph checkpoint."""

    spec_digest: str
    completed_node_ids: tuple[str, ...]
    schema_version: int = CHECKPOINT_SCHEMA_VERSION


def encode_checkpoint(
    *,
    spec_digest: str,
    completed_node_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    """Encode current runtime state using only portable JSON-like values."""
    if not spec_digest:
        raise CheckpointCodecError("checkpoint spec_digest must be non-empty")
    _validate_node_ids(completed_node_ids)
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "spec_digest": spec_digest,
        "completed_node_ids": list(completed_node_ids),
    }


def decode_checkpoint(
    payload: Mapping[str, object],
    *,
    expected_spec_digest: str,
) -> RuntimeCheckpoint:
    """Validate checkpoint state without mutating the caller's payload."""
    if set(payload) != _FIELDS:
        raise CheckpointCodecError("checkpoint fields do not match the current schema")
    version = payload["schema_version"]
    if not isinstance(version, int) or isinstance(version, bool):
        raise CheckpointCodecError("checkpoint schema_version must be an integer")
    if version != CHECKPOINT_SCHEMA_VERSION:
        raise CheckpointCodecError(f"unsupported checkpoint schema: {version}")
    digest = payload["spec_digest"]
    if not isinstance(digest, str) or not digest:
        raise CheckpointCodecError("checkpoint spec_digest must be a non-empty string")
    if digest != expected_spec_digest:
        raise CheckpointCodecError("checkpoint RunSpec digest does not match the active run")
    raw_node_ids = payload["completed_node_ids"]
    if not isinstance(raw_node_ids, list):
        raise CheckpointCodecError("checkpoint completed_node_ids must be an array")
    node_ids = tuple(raw_node_ids)
    _validate_node_ids(node_ids)
    return RuntimeCheckpoint(
        schema_version=version,
        spec_digest=digest,
        completed_node_ids=node_ids,
    )


def _validate_node_ids(node_ids: tuple[object, ...]) -> None:
    if any(not isinstance(node_id, str) or not node_id for node_id in node_ids):
        raise CheckpointCodecError(
            "checkpoint completed_node_ids must contain non-empty strings"
        )
    if len(set(node_ids)) != len(node_ids):
        raise CheckpointCodecError("checkpoint completed_node_ids must be unique")
