"""Pure, typed core for the ``onmc skillguard`` write-approval queue.

Design
------
This module is **side-effect-light and deterministic**:

- Pending proposals live under ``.onmc/skillguard/pending/`` — one JSON file per
  proposal named ``<id>.json``.  The id is derived from the proposal content
  (SHA-1 of op+name+content hex, first 16 chars) combined with a monotonic
  queue sequence number so two identical proposals can coexist while still being
  content-addressable and clock-free (offline, reproducible).
- Audit records live under ``.onmc/skillguard/audit/`` — one JSON file per
  decision, named ``<seq>-<proposal_id>.json``.  The sequence number is derived
  from the count of existing audit files at decision time (monotonic, no clock
  needed).
- No external dependencies — pure stdlib (``json``, ``hashlib``, ``difflib``).
- The real skill storage path (``storage.add_skill`` / ``storage.update_skill`` /
  ``storage.delete_skill``) is called on approve; skillguard is an opt-in queue
  in front of it, not a replacement.

Terminology
-----------
``StagedSkillProposal``
    A pending skill write waiting for human review.

``SkillAuditRecord``
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

SkillOp = Literal["create", "edit", "delete"]
ProposalStatus = Literal["pending", "approved", "rejected"]

_PENDING_DIRNAME = "pending"
_AUDIT_DIRNAME = "audit"
_SKILLGUARD_ROOT = ".onmc/skillguard"


@dataclass(slots=True)
class StagedSkillProposal:
    """A proposed skill write waiting for human approval.

    Fields
    ------
    id:
        Content-derived, deterministic identifier.  Derived from a SHA-1 of
        ``op+name+content`` combined with a monotonic queue index so two
        identical proposals still get unique ids.
    op:
        The operation being proposed: ``"create"``, ``"edit"``, or ``"delete"``.
    name:
        Name of the skill being targeted.
    content:
        Full proposed body of the skill.  Empty string for ``delete`` proposals.
    reason:
        Optional human-readable justification for why this write is proposed.
    staged_at:
        ISO-8601 UTC timestamp string, or ``""`` when unavailable (offline).
    seq:
        Monotonic sequence number — position in the queue at staging time.
    """

    id: str
    op: str
    name: str
    content: str
    reason: str = ""
    staged_at: str = ""
    seq: int = 0

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable mapping for this proposal."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> StagedSkillProposal:
        """Reconstruct a proposal from its serialised form, tolerating extras."""
        seq = data.get("seq", 0)
        return cls(
            id=str(data["id"]),
            op=str(data.get("op", "create")),
            name=str(data.get("name", "")),
            content=str(data.get("content", "")),
            reason=str(data.get("reason", "")),
            staged_at=str(data.get("staged_at", "")),
            seq=int(seq) if isinstance(seq, (int, float, str)) else 0,
        )


@dataclass(slots=True)
class SkillAuditRecord:
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
    skill_id:
        The id of the skill entry created/updated on approve; ``""`` on reject
        or delete.
    """

    seq: int
    proposal_id: str
    decision: Literal["approved", "rejected"]
    reason: str = ""
    skill_id: str = ""

    def to_dict(self) -> dict[str, object]:
        """JSON-serialisable mapping for this audit record."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SkillAuditRecord:
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
            skill_id=str(data.get("skill_id", "")),
        )


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _pending_dir(repo_root: Path) -> Path:
    return repo_root / _SKILLGUARD_ROOT / _PENDING_DIRNAME


def _audit_dir(repo_root: Path) -> Path:
    return repo_root / _SKILLGUARD_ROOT / _AUDIT_DIRNAME


def _pending_path(repo_root: Path, proposal_id: str) -> Path:
    return _pending_dir(repo_root) / f"{proposal_id}.json"


def _audit_path(repo_root: Path, seq: int, proposal_id: str) -> Path:
    return _audit_dir(repo_root) / f"{seq:06d}-{proposal_id}.json"


# ---------------------------------------------------------------------------
# Id derivation
# ---------------------------------------------------------------------------


def _content_hash(op: str, name: str, content: str) -> str:
    """SHA-1 of ``op+name+content`` (first 16 hex chars)."""
    raw = f"{op}\x00{name}\x00{content}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]  # noqa: S324


def _next_seq(repo_root: Path) -> int:
    """Count existing pending proposals to get the next monotonic index."""
    pending = _pending_dir(repo_root)
    if not pending.is_dir():
        return 0
    return sum(1 for p in pending.iterdir() if p.suffix == ".json")


def _proposal_id(op: str, name: str, content: str, seq: int) -> str:
    """Deterministic proposal id: ``sg-<content_hash>-<seq>``."""
    return f"sg-{_content_hash(op, name, content)}-{seq:04d}"


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


def _load_proposal(repo_root: Path, proposal_id: str) -> StagedSkillProposal | None:
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
        return StagedSkillProposal.from_dict(data)
    except (KeyError, TypeError, ValueError):
        return None


def _save_proposal(repo_root: Path, proposal: StagedSkillProposal) -> None:
    path = _pending_path(repo_root, proposal.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposal.to_dict(), indent=2) + "\n", encoding="utf-8")


def _remove_proposal(repo_root: Path, proposal_id: str) -> None:
    import contextlib  # noqa: PLC0415

    path = _pending_path(repo_root, proposal_id)
    with contextlib.suppress(FileNotFoundError, OSError):
        path.unlink()


def _save_audit(repo_root: Path, record: SkillAuditRecord) -> None:
    path = _audit_path(repo_root, record.seq, record.proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Skill content lookup (reads the real skill store)
# ---------------------------------------------------------------------------


def _current_skill_content(repo_root: Path, name: str) -> str:
    """Return the body of the named skill from the store, or '' if absent.

    Loads SQLiteStorage lazily so this module stays side-effect-light at
    import time.  Returns empty string when the skill does not exist (used as
    the diff baseline for create proposals).
    """
    try:
        from oh_no_my_claudecode.storage.sqlite import SQLiteStorage  # noqa: PLC0415

        db_path = repo_root / ".onmc" / "memory.db"
        if not db_path.exists():
            return ""
        storage = SQLiteStorage(db_path)
        skills = storage.list_skills()
        for sk in skills:
            if sk.name == name:
                return sk.body
    except Exception:  # noqa: BLE001
        return ""
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def stage(
    repo_root: Path,
    *,
    op: str,
    name: str,
    content: str,
    reason: str = "",
    staged_at: str = "",
) -> StagedSkillProposal:
    """Stage a proposed skill change into the pending queue.

    Does NOT write to the skill store — the proposal sits in the queue until a
    human approves or rejects it.

    Parameters
    ----------
    repo_root:
        Root of the git repository (where ``.onmc/`` lives).
    op:
        The operation to propose: ``"create"``, ``"edit"``, or ``"delete"``.
    name:
        Name of the skill being targeted.
    content:
        Full proposed body of the skill.  Pass ``""`` for delete proposals.
    reason:
        Optional human-readable justification for why this change is proposed.
    staged_at:
        ISO-8601 UTC timestamp string. Pass ``""`` to omit the wall-clock.

    Returns
    -------
    StagedSkillProposal
        The proposal that was staged (id is deterministic given content + seq).

    Raises
    ------
    ValueError
        If *op* is not one of ``create``, ``edit``, ``delete``; or if *name*
        is empty; or if *content* is empty for a non-delete proposal.
    """
    op = op.strip()
    name = name.strip()
    content = content  # preserve leading/trailing whitespace for diff fidelity

    valid_ops = {"create", "edit", "delete"}
    if op not in valid_ops:
        msg = f"op must be one of {sorted(valid_ops)!r}, got {op!r}"
        raise ValueError(msg)
    if not name:
        msg = "name must not be empty"
        raise ValueError(msg)
    if op != "delete" and not content.strip():
        msg = "content must not be empty for create/edit proposals"
        raise ValueError(msg)

    seq = _next_seq(repo_root)
    proposal_id = _proposal_id(op, name, content, seq)
    proposal = StagedSkillProposal(
        id=proposal_id,
        op=op,
        name=name,
        content=content,
        reason=reason.strip(),
        staged_at=staged_at,
        seq=seq,
    )
    _save_proposal(repo_root, proposal)
    return proposal


def list_pending(repo_root: Path) -> list[StagedSkillProposal]:
    """Return all pending proposals in deterministic order (by seq, then id).

    Returns an empty list when the queue directory is absent.
    """
    pending_dir = _pending_dir(repo_root)
    if not pending_dir.is_dir():
        return []
    proposals: list[StagedSkillProposal] = []
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
            proposals.append(StagedSkillProposal.from_dict(data))
        except (KeyError, TypeError, ValueError):
            continue
    proposals.sort(key=lambda p: (p.seq, p.id))
    return proposals


def get(repo_root: Path, proposal_id: str) -> StagedSkillProposal | None:
    """Return a single pending proposal by id, or ``None`` if not found."""
    return _load_proposal(repo_root, proposal_id)


def diff(repo_root: Path, proposal_id: str) -> str:
    """Return a unified-diff rendering of the proposed skill change.

    For ``create`` proposals, compares an empty baseline against the proposed
    content.  For ``edit`` proposals, compares the current skill body against
    the proposed content.  For ``delete`` proposals, shows the current content
    as fully removed.

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

    current_body = _current_skill_content(repo_root, proposal.name)

    if proposal.op == "create":
        before_lines: list[str] = []
        after_lines = proposal.content.splitlines()
    elif proposal.op == "edit":
        before_lines = current_body.splitlines()
        after_lines = proposal.content.splitlines()
    else:  # delete
        before_lines = current_body.splitlines()
        after_lines = []

    delta = list(
        difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"current/{proposal.name}",
            tofile=f"proposed/{proposal_id}" if proposal.op != "delete" else "(deleted)",
            lineterm="",
        )
    )
    header = f"op: {proposal.op}  skill: {proposal.name}  id: {proposal_id}"
    if proposal.reason:
        header += f"\nreason: {proposal.reason}"
    if not delta:
        return f"{header}\n(no content change)"
    return f"{header}\n" + "\n".join(delta)


def approve(
    repo_root: Path,
    proposal_id: str,
    *,
    service: object,
) -> SkillAuditRecord:
    """Approve a staged proposal and apply it to the skill store.

    For ``create`` proposals, inserts a new Skill via ``storage.add_skill``.
    For ``edit`` proposals, updates the existing skill body via ``storage.update_skill``.
    For ``delete`` proposals, removes the skill via the service (graceful if absent).
    The proposal is then removed from the pending queue and an audit record is written.

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
    SkillAuditRecord
        The audit record written for this approval.

    Raises
    ------
    LookupError
        If no pending proposal with *proposal_id* exists.
    TypeError
        If *service* is not an ``OnmcService`` instance.
    """
    proposal = _load_proposal(repo_root, proposal_id)
    if proposal is None:
        msg = f"no pending proposal with id {proposal_id!r}"
        raise LookupError(msg)

    from oh_no_my_claudecode.core.service import OnmcService  # noqa: PLC0415

    if not isinstance(service, OnmcService):
        msg = f"service must be an OnmcService instance, got {type(service).__name__}"
        raise TypeError(msg)

    skill_id = _apply_proposal(repo_root, proposal, service)

    _remove_proposal(repo_root, proposal_id)

    seq = _next_audit_seq(repo_root)
    record = SkillAuditRecord(
        seq=seq,
        proposal_id=proposal_id,
        decision="approved",
        skill_id=skill_id,
    )
    _save_audit(repo_root, record)
    return record


def _apply_proposal(
    repo_root: Path,
    proposal: StagedSkillProposal,
    service: object,
) -> str:
    """Apply the proposal to the skill store; return the skill id (or '' for delete)."""
    from oh_no_my_claudecode.models.skill import Skill  # noqa: PLC0415
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage  # noqa: PLC0415
    from oh_no_my_claudecode.utils.text import stable_id  # noqa: PLC0415
    from oh_no_my_claudecode.utils.time import utc_now  # noqa: PLC0415

    db_path = repo_root / ".onmc" / "memory.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SQLiteStorage(db_path)
    storage.initialize()

    if proposal.op == "create":
        now = utc_now()
        skill_id = stable_id("skillguard", "create", proposal.name, proposal.content, prefix="sk")
        skill = Skill(
            id=skill_id,
            name=proposal.name,
            body=proposal.content,
            trigger=f"When working on {proposal.name}.",
            tags=[],
            files=[],
            source_memory_ids=[],
            use_count=0,
            success_count=0,
            confidence=0.5,
            auto_inject=True,
            created_at=now,
            updated_at=now,
            last_used_at=None,
        )
        storage.add_skill(skill)
        return skill.id

    if proposal.op == "edit":
        skills = storage.list_skills()
        existing = next((sk for sk in skills if sk.name == proposal.name), None)
        if existing is None:
            # Skill doesn't exist yet — treat as create.
            now = utc_now()
            skill_id = stable_id(
                "skillguard", "edit-create", proposal.name, proposal.content, prefix="sk"
            )
            skill = Skill(
                id=skill_id,
                name=proposal.name,
                body=proposal.content,
                trigger=f"When working on {proposal.name}.",
                tags=[],
                files=[],
                source_memory_ids=[],
                use_count=0,
                success_count=0,
                confidence=0.5,
                auto_inject=True,
                created_at=now,
                updated_at=now,
                last_used_at=None,
            )
            storage.add_skill(skill)
            return skill.id
        # Update body and updated_at.
        from oh_no_my_claudecode.utils.time import utc_now as _utc_now  # noqa: PLC0415

        updated = existing.model_copy(update={"body": proposal.content, "updated_at": _utc_now()})
        storage.update_skill(updated)
        return existing.id

    # delete
    skills = storage.list_skills()
    target = next((sk for sk in skills if sk.name == proposal.name), None)
    if target is None:
        # Already absent — graceful no-op.
        return ""
    # SQLiteStorage may not expose delete_skill; fall back to direct SQL.
    _delete_skill_by_id(storage, target.id)
    return ""


def _delete_skill_by_id(storage: object, skill_id: str) -> None:
    """Delete a skill by id using the storage connection (internal helper)."""
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage  # noqa: PLC0415

    if not isinstance(storage, SQLiteStorage):
        return
    # Use the internal _connection context manager — same pattern as other
    # SQLiteStorage methods.  We avoid adding a delete_skill public API to
    # keep the change minimal; the real skill path stays unmodified.
    with storage._connection() as conn:  # noqa: SLF001
        conn.execute("DELETE FROM skills WHERE id = ?", (skill_id,))


def reject(
    repo_root: Path,
    proposal_id: str,
    *,
    reason: str = "",
) -> SkillAuditRecord:
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
    SkillAuditRecord
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
    record = SkillAuditRecord(
        seq=seq,
        proposal_id=proposal_id,
        decision="rejected",
        reason=reason.strip(),
    )
    _save_audit(repo_root, record)
    return record


def list_audit(repo_root: Path) -> list[SkillAuditRecord]:
    """Return all audit records in monotonic sequence order.

    Returns an empty list when the audit directory is absent.
    """
    audit_dir = _audit_dir(repo_root)
    if not audit_dir.is_dir():
        return []
    records: list[SkillAuditRecord] = []
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
            records.append(SkillAuditRecord.from_dict(data))
        except (KeyError, TypeError, ValueError):
            continue
    records.sort(key=lambda r: r.seq)
    return records
