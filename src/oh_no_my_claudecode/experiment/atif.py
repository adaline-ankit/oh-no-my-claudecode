"""ATIF artifact validation for agent-neutral Harbor imports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from oh_no_my_claudecode.experiment.contracts import ArtifactRef

__all__ = [
    "AtifArtifact",
    "atif_artifact_from_mapping",
]


@dataclass(frozen=True, slots=True)
class AtifArtifact:
    """Content-addressed Agent Trajectory Interchange Format artifact."""

    path: str
    ref: ArtifactRef
    schema: str = "atif"

    def __post_init__(self) -> None:
        if not self.path.strip():
            raise ValueError("atif.path must not be empty")
        if self.schema != "atif":
            raise ValueError("atif.schema must be 'atif'")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "path": self.path,
            **self.ref.to_dict(),
        }


def atif_artifact_from_mapping(data: Mapping[str, object]) -> AtifArtifact:
    """Validate a JSON-like ATIF artifact pointer."""

    return AtifArtifact(
        path=_string(data.get("path"), "atif.path"),
        schema=_string(data.get("schema", "atif"), "atif.schema"),
        ref=ArtifactRef(
            sha256=_string(data.get("sha256"), "atif.sha256"),
            media_type=_string(data.get("media_type", "application/json"), "atif.media_type"),
            size_bytes=_integer(data.get("size_bytes"), "atif.size_bytes"),
        ),
    )


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value
