"""Pure, typed core for the ``onmc memstage`` write-approval queue.

Design
------
This module is **side-effect-light and deterministic**:

- Pending proposals live under ``.onmc/memstage/pending/`` — one JSON file per
  proposal named ``<id>.json``.  The id is derived from the proposal content
  (SHA-1 of kind+title+summary hex, first 16 chars) combined with a monotonic
  queue sequence number so two identical proposals can coexist while still being
  content-addressable and clock-free (offline, reproducible).
- Audit records live under ``.onmc/memstage/audit/`` — one JSON file per
  decision, named ``<seq>-<proposal_id>.json``.  The sequence number is derived
  from the count of existing audit files at decision time (monotonic, no clock
  needed).
- No external dependencies — pure stdlib (``json``, ``hashlib``, ``difflib``).
- The real memory record path (:meth:`OnmcService.add_manual_memory`) is called
  on approve; memstage is an opt-in queue in front of it, not a replacement.

Terminology
-----------
``StagedProposal``
    A pending memory write waiting for human review.

``AuditRecord``
    The outcome of an approve or reject decision.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

ProposalStatus = Literal["pending", "approved", "rejected"]

_PENDING_DIRNAME = "pending"
_AUDIT_DIRNAME = "audit"
_MEMSTAGE_ROOT = ".onmc/memstage"


@dataclass(slots=True)
class StagedProposal:
    """A proposed memory write waiting for human approval.

    Fields
    ------
    id:
        Content-derived, deterministic identifier.  Derived from a SHA-1 of
        ``kind+title+summary`` combined with a monotonic queue index so two
        identical proposals still get unique ids.
    kind:
        Memory kind (e.g. ``"doc_fact"``, ``"decision"``).  Validated by the
        caller against :class:`MemoryKind` values.
    title:
        Short title for the proposed memory entry.
    summary:
        Full body of the proposed memory entry.
    reason:
        Optional human-readable justification for why this write is proposed.
    staged_at:
        ISO-8601 UTC timestamp string, or ``""`` when unavailable (offline).
    seq:
        Monotonic sequence number — position in the queue at staging time.
    """

    id: str
    kind: str
    title: str
    summary: str
    reason: str = ""
    staged_at: str = ""
    seq: int = 0

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable mapping for this proposal."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StagedProposal:
        """Reconstruct a proposal from its serialised form, tolerating extras."""
        seq = data.get("seq", 0)
        return cls(
            id=str(data["id"]),
            kind=str(data.get("kind", "")),
            title=str(data.get("title", "")),
            summary=str(data.get("summary", "")),
            reason=str(data.get("reason", "")),
            staged_at=str(data.get("staged_at", "")),
            seq=int(seq) if isinstance(seq, (int, float, str)) else 0,
        )


@dataclass(slots=True)
class AuditRecord:
    """Outcome of an approve or reject decision.

    Fields
    ------
    seq:
        Monotonic sequence number of the audit event.
    proposal_id:
        Id of the proposal this decision applies to.
    decision:
        ``"approved"`` or ``"rejected"``.
    reason:
        Human-readable justification for the decision (optional on approve,
        recommended on reject).
    memory_id:
        The id of the memory entry created on approve; ``""`` on reject.
    """

    seq: int
    proposal_id: str
    decision: Literal["approved", "rejected"]
    reason: str = ""
    memory_id: str = ""

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable mapping for this audit record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AuditRecord:
        """Reconstruct an audit record, tolerating extras."""
        seq = data.get("seq", 0)
        decision = str(data.get("decision", "rejected"))
        if decision not in ("approved", "rejected"):
            decision = "rejected"
        return cls(
            seq=int(seq) if isinstance(seq, (int, float, str)) else 0,
            proposal_id=str(data.get("proposal_id", "")),
            decision=decision,  # type: ignore[arg-type]
            reason=str(data.get("reason", "")),
            memory_id=str(data.get("memory_id", "")),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _pending_dir(repo_root: Path) -> Path:
    return repo_root / _MEMSTAGE_ROOT / _PENDING_DIRNAME


def _audit_dir(repo_root: Path) -> Path:
    return repo_root / _MEMSTAGE_ROOT / _AUDIT_DIRNAME


def _pending_path(repo_root: Path, proposal_id: str) -> Path:
    return _pending_dir(repo_root) / f"{proposal_id}.json"


def _audit_path(repo_root: Path, seq: int, proposal_id: str) -> Path:
    return _audit_dir(repo_root) / f"{seq:06d}-{proposal_id}.json"


# ---------------------------------------------------------------------------
# Id derivation
# ---------------------------------------------------------------------------


def _content_hash(kind: str, title: str, summary: str) -> str:
    """SHA-1 of ``kind+title+summary`` (first 16 hex chars)."""
    content = f"{kind}\x00{title}\x00{summary}"
    return hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def _next_seq(repo_root: Path) -> int:
    """Count existing pending proposals to get the next monotonic index."""
    pending = _pending_dir(repo_root)
    if not pending.is_dir():
        return 0
    return sum(1 for p in pending.iterdir() if p.suffix == ".json")


def _proposal_id(kind: str, title: str, summary: str, seq: int) -> str:
    """Deterministic proposal id: ``ms-<content_hash>-<seq>``."""
    return f"ms-{_content_hash(kind, title, summary)}-{seq:04d}"


# ---------------------------------------------------------------------------
# Audit sequence
# ---------------------------------------------------------------------------


def _next_audit_seq(repo_root: Path) -> int:
    """Count existing audit records to get the next monotonic audit sequence."""
    audit = _audit_dir(repo_root)
    if not audit.is_dir():
        return 0
    return sum(1 for p in audit.iterdir() if p.suffix == ".json")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _load_proposal(repo_root: Path, proposal_id: str) -> StagedProposal | None:
    path = _pending_path(repo_root, proposal_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return StagedProposal.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None


def _save_proposal(repo_root: Path, proposal: StagedProposal) -> None:
    path = _pending_path(repo_root, proposal.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal.to_dict(), indent=2) + "\n", encoding="utf-8")


def _remove_proposal(repo_root: Path, proposal_id: str) -> None:
    import contextlib  # noqa: PLC0415

    path = _pending_path(repo_root, proposal_id)
    with contextlib.suppress(FileNotFoundError, OSError):
        path.unlink()


def _save_audit(repo_root: Path, record: AuditRecord) -> None:
    path = _audit_path(repo_root, record.seq, record.proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def stage(
    repo_root: Path,
    *,
    kind: str,
    title: str,
    summary: str,
    reason: str = "",
    staged_at: str = "",
) -> StagedProposal:
    """Stage a proposed memory write into the pending queue.

    Does NOT write to the memory store — the proposal sits in the queue until a
    human approves or rejects it.

    Parameters
    ----------
    repo_root:
        Root of the git repository (where ``.onmc/`` lives).
    kind:
        Memory kind string (e.g. ``"doc_fact"``).
    title:
        Short title for the proposed memory entry.
    summary:
        Full body of the proposed memory entry.
    reason:
        Optional human-readable justification for why this write is proposed.
    staged_at:
        ISO-8601 UTC timestamp string. Pass ``""`` to omit the wall-clock.

    Returns
    -------
    StagedProposal
        The proposal that was staged (id is deterministic given content + seq).

    Raises
    ------
    ValueError
        If *kind*, *title*, or *summary* is empty / whitespace-only.
    """
    kind = kind.strip()
    title = title.strip()
    summary = summary.strip()
    if not kind:
        msg = "kind must not be empty"
        raise ValueError(msg)
    if not title:
        msg = "title must not be empty"
        raise ValueError(msg)
    if not summary:
        msg = "summary must not be empty"
        raise ValueError(msg)

    seq = _next_seq(repo_root)
    proposal_id = _proposal_id(kind, title, summary, seq)
    proposal = StagedProposal(
        id=proposal_id,
        kind=kind,
        title=title,
        summary=summary,
        reason=reason.strip(),
        staged_at=staged_at,
        seq=seq,
    )
    _save_proposal(repo_root, proposal)
    return proposal


def list_pending(repo_root: Path) -> list[StagedProposal]:
    """Return all pending proposals in deterministic order (by seq, then id).

    Returns an empty list when the queue directory is absent.
    """
    pending_dir = _pending_dir(repo_root)
    if not pending_dir.is_dir():
        return []
    proposals: list[StagedProposal] = []
    for path in sorted(pending_dir.iterdir()):
        if path.suffix != ".json":
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            proposals.append(StagedProposal.from_dict(data))
        except (KeyError, TypeError, ValueError):
            continue
    proposals.sort(key=lambda p: (p.seq, p.id))
    return proposals


def get(repo_root: Path, proposal_id: str) -> StagedProposal | None:
    """Return a single pending proposal by id, or ``None`` if not found."""
    return _load_proposal(repo_root, proposal_id)


def diff(repo_root: Path, proposal_id: str) -> str:
    """Return a unified-diff style rendering of the proposed entry.

    The diff compares an empty baseline (the entry does not yet exist in the
    store) against the proposed content. This makes the intent visible: every
    line in the diff is something that *would* be added on approve.

    Returns
    -------
    str
        Unified-diff lines joined by newlines. Returns an error string when
        the proposal id is not found (never raises so callers can echo it
        directly).
    """
    proposal = _load_proposal(repo_root, proposal_id)
    if proposal is None:
        return f"error: no pending proposal with id {proposal_id!r}"

    before_lines: list[str] = []
    after_lines = [
        f"kind:    {proposal.kind}",
        f"title:   {proposal.title}",
        f"summary: {proposal.summary}",
    ]
    if proposal.reason:
        after_lines.append(f"reason:  {proposal.reason}")

    delta = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile="(none)",
            tofile=f"proposed/{proposal_id}",
            lineterm="",
        )
    )
    if not delta:
        return "(empty diff)"
    return "\n".join(delta)


def approve(
    repo_root: Path,
    proposal_id: str,
    *,
    service: object,
) -> AuditRecord:
    """Approve a staged proposal and persist it to the memory store.

    Calls the real memory record path (``OnmcService.add_manual_memory``) so the
    entry lands in the SQLite store with full metadata. The proposal is then
    removed from the pending queue and an audit record is written.

    Parameters
    ----------
    repo_root:
        Root of the git repository.
    proposal_id:
        Id of the pending proposal to approve.
    service:
        An ``OnmcService`` instance (passed in so this module stays dependency-
        light; the caller imports and instantiates it).

    Returns
    -------
    AuditRecord
        The audit record written for this approval.

    Raises
    ------
    LookupError
        If no pending proposal with *proposal_id* exists.
    ValueError
        If the memory kind is not a valid :class:`MemoryKind` value.
    """
    proposal = _load_proposal(repo_root, proposal_id)
    if proposal is None:
        msg = f"no pending proposal with id {proposal_id!r}"
        raise LookupError(msg)

    # Import lazily to keep this module side-effect-light at load time.
    from oh_no_my_claudecode.models.memory import MemoryKind  # noqa: PLC0415

    kind_values = {k.value for k in MemoryKind}
    if proposal.kind not in kind_values:
        valid = ", ".join(sorted(kind_values))
        msg = f"unknown memory kind {proposal.kind!r}; must be one of: {valid}"
        raise ValueError(msg)

    from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

    if not isinstance(service, OnmcService):
        msg = f"service must be an OnmcService instance, got {type(service).__name__}"
        raise TypeError(msg)

    memory_entry = service.add_manual_memory(
        kind=MemoryKind(proposal.kind),
        title=proposal.title,
        summary=proposal.summary,
        source_ref=f"memstage:{proposal_id}",
    )

    _remove_proposal(repo_root, proposal_id)

    seq = _next_audit_seq(repo_root)
    record = AuditRecord(
        seq=seq,
        proposal_id=proposal_id,
        decision="approved",
        memory_id=memory_entry.id,
    )
    _save_audit(repo_root, record)
    return record


def reject(
    repo_root: Path,
    proposal_id: str,
    *,
    reason: str = "",
) -> AuditRecord:
    """Reject a staged proposal, dropping it and keeping an audit trail.

    The proposal is removed from the pending queue. An audit record is written
    so the decision is traceable.

    Parameters
    ----------
    repo_root:
        Root of the git repository.
    proposal_id:
        Id of the pending proposal to reject.
    reason:
        Optional human-readable justification for the rejection.

    Returns
    -------
    AuditRecord
        The audit record written for this rejection.

    Raises
    ------
    LookupError
        If no pending proposal with *proposal_id* exists.
    """
    proposal = _load_proposal(repo_root, proposal_id)
    if proposal is None:
        msg = f"no pending proposal with id {proposal_id!r}"
        raise LookupError(msg)

    _remove_proposal(repo_root, proposal_id)

    seq = _next_audit_seq(repo_root)
    record = AuditRecord(
        seq=seq,
        proposal_id=proposal_id,
        decision="rejected",
        reason=reason.strip(),
    )
    _save_audit(repo_root, record)
    return record


def list_audit(repo_root: Path) -> list[AuditRecord]:
    """Return all audit records in monotonic sequence order.

    Returns an empty list when the audit directory is absent.
    """
    audit_dir = _audit_dir(repo_root)
    if not audit_dir.is_dir():
        return []
    records: list[AuditRecord] = []
    for path in sorted(audit_dir.iterdir()):
        if path.suffix != ".json":
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            records.append(AuditRecord.from_dict(data))
        except (KeyError, TypeError, ValueError):
            continue
    records.sort(key=lambda r: r.seq)
    return records
