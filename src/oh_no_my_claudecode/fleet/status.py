from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time
from typing import Any

from oh_no_my_claudecode.ledger.accounting import LedgerSummary, load_receipts, summarize_receipts

ACTIVE_STATUSES = frozenset({"pending", "running"})
STALE_CLAIM_SECONDS = 4 * 60 * 60


@dataclass(frozen=True, slots=True)
class UnitCounts:
    total: int = 0
    pending: int = 0
    running: int = 0
    done: int = 0
    failed: int = 0
    aborted: int = 0

    @property
    def active(self) -> int:
        return self.pending + self.running


@dataclass(frozen=True, slots=True)
class SwarmSummary:
    swarm_id: str
    agent: str
    started_at: str
    stop_reason: str
    counts: UnitCounts


@dataclass(frozen=True, slots=True)
class FleetStatus:
    swarms: list[SwarmSummary] = field(default_factory=list)
    active_claims: int = 0
    receipt_count: int = 0
    ledger: LedgerSummary | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        if self.ledger is not None:
            ledger = data.get("ledger")
            if isinstance(ledger, dict):
                ledger["cost_label"] = self.ledger.cost_label
        return data


@dataclass(frozen=True, slots=True)
class FleetDoctorIssue:
    severity: str
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class FleetDoctorReport:
    ok: bool
    issues: list[FleetDoctorIssue] = field(default_factory=list)
    status: FleetStatus | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def fleet_status(repo_root: Path, *, swarm_id: str | None = None) -> FleetStatus:
    manifests = _load_manifests(repo_root, swarm_id=swarm_id)
    receipts = load_receipts(repo_root, scope="project")
    claims = _active_claims(repo_root, now=time())
    swarms = [_summarize_manifest(sid, manifest) for sid, manifest in manifests]
    swarms.sort(key=lambda swarm: (swarm.started_at, swarm.swarm_id), reverse=True)
    return FleetStatus(
        swarms=swarms,
        active_claims=len(claims),
        receipt_count=len(receipts),
        ledger=summarize_receipts(receipts, scope="project"),
    )


def fleet_doctor(
    repo_root: Path,
    *,
    now: float | None = None,
    stale_claim_seconds: int = STALE_CLAIM_SECONDS,
) -> FleetDoctorReport:
    current_time = time() if now is None else now
    status = fleet_status(repo_root)
    issues: list[FleetDoctorIssue] = []
    for swarm in status.swarms:
        if swarm.stop_reason == "running" and swarm.counts.active == 0:
            issues.append(
                FleetDoctorIssue(
                    severity="warning",
                    title="swarm marked running but has no active units",
                    detail=swarm.swarm_id,
                )
            )
    for claim in _active_claims(repo_root, now=current_time):
        acquired_at = _as_float(claim.get("acquired_at"))
        if acquired_at is not None and current_time - acquired_at > stale_claim_seconds:
            issues.append(
                FleetDoctorIssue(
                    severity="warning",
                    title="stale active claim",
                    detail=f"{claim.get('owner', '?')} owns {claim.get('path', '?')}",
                )
            )
    return FleetDoctorReport(ok=not issues, issues=issues, status=status)


def _load_manifests(
    repo_root: Path,
    *,
    swarm_id: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    swarm_root = repo_root / ".onmc" / "swarm"
    if not swarm_root.exists():
        return []
    paths = (
        [swarm_root / swarm_id / "manifest.json"]
        if swarm_id
        else sorted(swarm_root.glob("*/manifest.json"))
    )
    manifests: list[tuple[str, dict[str, Any]]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            manifests.append((path.parent.name, payload))
    return manifests


def _summarize_manifest(swarm_id: str, manifest: dict[str, Any]) -> SwarmSummary:
    units = manifest.get("units")
    raw_units = units if isinstance(units, dict) else {}
    statuses = [
        str(unit.get("status", "pending"))
        for unit in raw_units.values()
        if isinstance(unit, dict)
    ]
    counts = UnitCounts(
        total=len(statuses),
        pending=sum(1 for status in statuses if status == "pending"),
        running=sum(1 for status in statuses if status == "running"),
        done=sum(1 for status in statuses if status == "done"),
        failed=sum(1 for status in statuses if status == "failed"),
        aborted=sum(1 for status in statuses if status == "aborted"),
    )
    return SwarmSummary(
        swarm_id=str(manifest.get("swarm_id") or swarm_id),
        agent=str(manifest.get("agent") or "unknown"),
        started_at=str(manifest.get("started_at") or ""),
        stop_reason=str(manifest.get("stop_reason") or "running"),
        counts=counts,
    )


def _active_claims(repo_root: Path, *, now: float) -> list[dict[str, Any]]:
    path = repo_root / ".onmc" / "claims.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    claims = payload.get("claims") if isinstance(payload, dict) else []
    if not isinstance(claims, list):
        return []
    active: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        expires_at = _as_float(claim.get("expires_at"))
        if expires_at is None or expires_at <= now:
            continue
        active.append(claim)
    return active


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
