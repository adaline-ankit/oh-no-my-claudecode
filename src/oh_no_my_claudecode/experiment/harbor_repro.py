"""Pinned reproduction contract for ONMC's bounded Harbor benchmark smoke."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_HARBOR_DOCKER_IMAGE = (
    "python:3.12.13-slim-bookworm"
    "@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
)
HARBOR_REQUIRED_ARTIFACTS = (
    ("trajectory", "agent/trajectory.json", "application/json"),
    ("verifier-reward", "verifier/reward.json", "application/json"),
    ("verifier-stdout", "verifier/test-stdout.txt", "text/plain"),
    ("harbor-result", "result.json", "application/json"),
    ("harbor-config", "config.json", "application/json"),
    ("harbor-lock", "lock.json", "application/json"),
)
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class HarborReproManifest:
    """Validated, content-addressed Harbor/Docker reproduction boundary."""

    source: Path
    source_sha256: str
    repository_root: Path
    payload: dict[str, Any]
    portfolio_path: Path
    docker_image: str
    harbor_version: str

    @property
    def leakage_boundary(self) -> dict[str, Any]:
        return _object(self.payload["leakage_boundary"], "leakage_boundary")

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.source.relative_to(self.repository_root)),
            "sha256": self.source_sha256,
            "baseline": self.payload["baseline"],
            "portfolio": self.payload["portfolio"],
            "execution": self.payload["execution"],
            "artifact_contract": self.payload["artifact_contract"],
            "leakage_boundary": self.leakage_boundary,
            "claim_eligible": False,
        }


def load_harbor_repro_manifest(
    path: Path,
    *,
    repository_root: Path,
    portfolio_path: Path | None = None,
) -> HarborReproManifest:
    """Load a pinned manifest and fail closed on drift or weakened boundaries."""

    root = repository_root.resolve()
    source = path.resolve()
    _require_within(source, root, "reproduction manifest")
    source_bytes = source.read_bytes()
    try:
        raw = json.loads(source_bytes)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Harbor reproduction manifest JSON: {source}") from exc
    payload = _object(raw, "Harbor reproduction manifest")
    if payload.get("schema_version") != "onmc-harbor-repro/v1":
        raise ValueError("unsupported Harbor reproduction manifest schema")
    if payload.get("claim_eligible") is not False:
        raise ValueError("bounded Harbor reproduction manifest must be non-claimable")

    baseline = _object(payload.get("baseline"), "baseline")
    _text(baseline.get("release"), "baseline.release")
    code_sha = _text(baseline.get("code_sha"), "baseline.code_sha")
    if _COMMIT_RE.fullmatch(code_sha) is None:
        raise ValueError("baseline.code_sha must be a full git commit SHA")

    portfolio = _object(payload.get("portfolio"), "portfolio")
    relative_portfolio = Path(_text(portfolio.get("path"), "portfolio.path"))
    if relative_portfolio.is_absolute():
        raise ValueError("portfolio.path must be repository-relative")
    bound_portfolio = (root / relative_portfolio).resolve()
    _require_within(bound_portfolio, root, "portfolio")
    if portfolio_path is not None and portfolio_path.resolve() != bound_portfolio:
        raise ValueError(
            f"reproduction manifest binds {bound_portfolio}, not {portfolio_path.resolve()}"
        )
    portfolio_bytes = bound_portfolio.read_bytes()
    expected_file_sha = _text(portfolio.get("file_sha256"), "portfolio.file_sha256")
    actual_file_sha = hashlib.sha256(portfolio_bytes).hexdigest()
    if expected_file_sha != actual_file_sha:
        raise ValueError(
            f"portfolio file digest mismatch: expected {expected_file_sha}, got {actual_file_sha}"
        )
    portfolio_payload = _object(json.loads(portfolio_bytes), "portfolio document")
    expected_task_set_sha = _text(
        portfolio.get("task_set_sha256"),
        "portfolio.task_set_sha256",
    )
    if portfolio_payload.get("task_set_sha256") != expected_task_set_sha:
        raise ValueError("portfolio task-set digest mismatch")
    tasks = portfolio_payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != portfolio.get("task_count"):
        raise ValueError("portfolio task count mismatch")

    execution = _object(payload.get("execution"), "execution")
    harbor_version = _text(execution.get("harbor_version"), "execution.harbor_version")
    if execution.get("provider") != "docker":
        raise ValueError("execution.provider must be docker")
    docker = _object(execution.get("docker"), "execution.docker")
    image = _text(docker.get("image"), "execution.docker.image")
    digest = _text(docker.get("digest"), "execution.docker.digest")
    if _SHA256_RE.fullmatch(digest) is None:
        raise ValueError("execution.docker.digest must be a sha256 digest")
    docker_image = f"{image}@{digest}"
    if docker_image != DEFAULT_HARBOR_DOCKER_IMAGE:
        raise ValueError("execution Docker image differs from adapter pin")

    artifact_contract = _object(payload.get("artifact_contract"), "artifact_contract")
    required = artifact_contract.get("required")
    expected_required = [
        {"kind": kind, "path": artifact_path, "media_type": media_type}
        for kind, artifact_path, media_type in HARBOR_REQUIRED_ARTIFACTS
    ]
    if required != expected_required:
        raise ValueError("artifact_contract.required differs from importer contract")
    if artifact_contract.get("non_empty") is not True:
        raise ValueError("artifact contract must reject empty files")
    if artifact_contract.get("content_address") != "sha256":
        raise ValueError("artifact contract must content-address files with sha256")

    leakage = _object(payload.get("leakage_boundary"), "leakage_boundary")
    if leakage.get("publication_eligible") is not False:
        raise ValueError("free smoke leakage boundary must not be publication eligible")
    if leakage.get("independent_audit") != "missing":
        raise ValueError("free smoke must record the missing independent leakage audit")
    _nonempty_text_list(leakage.get("agent_visible"), "leakage_boundary.agent_visible")
    _nonempty_text_list(leakage.get("withheld"), "leakage_boundary.withheld")
    _nonempty_text_list(leakage.get("limitations"), "leakage_boundary.limitations")

    return HarborReproManifest(
        source=source,
        source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        repository_root=root,
        payload=payload,
        portfolio_path=bound_portfolio,
        docker_image=docker_image,
        harbor_version=harbor_version,
    )


def require_digest_pinned_image(image: str) -> str:
    """Return *image* only when it includes an immutable sha256 digest."""

    name, separator, digest = image.rpartition("@")
    if not name or separator != "@" or _SHA256_RE.fullmatch(digest) is None:
        raise ValueError("Harbor Docker image must include an immutable sha256 digest")
    return image


def _require_within(path: Path, root: Path, label: str) -> None:
    if not path.is_relative_to(root):
        raise ValueError(f"{label} path escapes repository root: {path}")


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value


def _nonempty_text_list(value: object, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a non-empty list")
    for item in value:
        _text(item, label)


__all__ = [
    "DEFAULT_HARBOR_DOCKER_IMAGE",
    "HARBOR_REQUIRED_ARTIFACTS",
    "HarborReproManifest",
    "load_harbor_repro_manifest",
    "require_digest_pinned_image",
]
