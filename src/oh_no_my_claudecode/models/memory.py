from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

StalenessLabel = Literal["fresh", "stale", "orphaned", "unanchored"]

#: Reserved ``source_ref`` prefix that used to be the *only* carrier of the
#: quarantine bit.  It is kept as a compatibility mirror of
#: :class:`PromotionState` (see :class:`MemoryEntry`) so that modules still
#: consulting the prefix keep working during the rollout.
#:
#: This literal MUST stay equal to
#: :data:`oh_no_my_claudecode.hooks.prompt_recall.UNPROMOTED_SOURCE_PREFIX`.
#: It is duplicated rather than imported because ``hooks.prompt_recall``
#: imports this module — importing back would be circular.  A test
#: (``tests/test_memory_promotion.py::test_prefix_constant_matches_hook_helpers``)
#: pins the two together.
UNPROMOTED_SOURCE_PREFIX = "unpromoted:"


class MemoryKind(StrEnum):
    DOC_FACT = "doc_fact"
    DECISION = "decision"
    INVARIANT = "invariant"
    HOTSPOT = "hotspot"
    GIT_PATTERN = "git_pattern"
    VALIDATION_RULE = "validation_rule"
    FAILED_APPROACH = "failed_approach"
    DESIGN_CONFLICT = "design_conflict"
    GOTCHA = "gotcha"


class SourceType(StrEnum):
    GIT = "git"
    DOC = "doc"
    CODE = "code"
    MANUAL = "manual"
    MANUAL_SEED = "manual_seed"
    LLM_EXTRACTED = "llm_extracted"
    TRANSCRIPT = "transcript"
    GITHUB_PR = "github_pr"
    SESSION = "session"


class PromotionState(StrEnum):
    """Whether a memory entry may be auto-injected into an agent's context.

    This is an *authorization* bit and is deliberately separate from
    :attr:`MemoryEntry.source_ref`, which is *provenance* (where the memory
    came from).  Overloading provenance with authorization — the historical
    ``unpromoted:`` prefix hack — corrupts the provenance value, is silently
    lost by any writer that rebuilds ``source_ref``, and cannot be queried in
    SQL.

    Two states, not a bool, because a bool has no honest name here: an entry
    ingested from a doc was never "promoted" by anyone, it simply never needed
    a promotion.  The enum also leaves room for further states (an explicit
    ``promoted``/``revoked`` audit distinction, say) without another schema
    migration — readers treat any non-``QUARANTINED`` value as injectable.
    """

    #: Default.  Human-authored, ingested, or human-promoted content: may be
    #: auto-injected.  This is the safe default for anything written before
    #: the quarantine concept existed.
    INJECTABLE = "injectable"

    #: Written autonomously by an agent about its own run with no promotion
    #: record behind it.  Fully readable through explicit surfaces
    #: (``onmc memory list``, ``onmc recall``) but never auto-injected.
    QUARANTINED = "quarantined"


def has_unpromoted_prefix(source_ref: str) -> bool:
    """Whether *source_ref* carries the legacy quarantine prefix.

    Mirrors :func:`oh_no_my_claudecode.hooks.prompt_recall.is_unpromoted_source`.
    """
    return source_ref.startswith(UNPROMOTED_SOURCE_PREFIX)


def strip_unpromoted_prefix(source_ref: str) -> str:
    """Return *source_ref* as pure provenance, with every quarantine prefix removed.

    Strips repeatedly (a doubled ``unpromoted:unpromoted:docs/x.md`` collapses
    to ``docs/x.md``) and never returns an empty pointer — mirroring the
    behaviour of ``OnmcService.promote_memory``.
    """
    cleaned = source_ref
    while cleaned.startswith(UNPROMOTED_SOURCE_PREFIX):
        cleaned = cleaned[len(UNPROMOTED_SOURCE_PREFIX) :]
    return cleaned.strip() or "unknown"


def add_unpromoted_prefix(source_ref: str) -> str:
    """Return the compat-prefixed form of *source_ref*.  Idempotent.

    Mirrors :func:`oh_no_my_claudecode.hooks.prompt_recall.unpromoted_source_ref`.
    """
    cleaned = source_ref.strip() or "unknown"
    if cleaned.startswith(UNPROMOTED_SOURCE_PREFIX):
        return cleaned
    return f"{UNPROMOTED_SOURCE_PREFIX}{cleaned}"


class MemoryEntry(BaseModel):
    """One memory entry.

    Quarantine (``promotion_state``) and provenance (``source_ref``) are two
    separate fields.  While the legacy ``unpromoted:`` prefix is still consulted
    by other modules, the model keeps the two representations in agreement:

    * constructing an entry whose ``source_ref`` carries the prefix forces
      ``promotion_state`` to :attr:`PromotionState.QUARANTINED`;
    * constructing an entry with ``promotion_state=QUARANTINED`` stamps the
      prefix onto ``source_ref``.

    So ``is_unpromoted_source(entry.source_ref)`` is always equivalent to
    ``entry.promotion_state is PromotionState.QUARANTINED`` for any validated
    entry, and callers may set either one.  ``model_copy(update=...)`` does not
    re-run validation, so an entry mutated that way can drift; the storage
    layer resolves the drift in favour of the ``source_ref`` prefix (see
    ``SQLiteStorage._memory_provenance_values``), which is what the existing
    promote/revoke path expresses its intent through.

    The prefix is *not* persisted: the ``source_ref`` column holds pure
    provenance and the ``promotion_state`` column holds the authorization bit,
    so quarantine is queryable in SQL and provenance is never corrupted on
    disk.
    """

    id: str
    kind: MemoryKind
    title: str
    summary: str
    details: str
    source_type: SourceType
    source_ref: str
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    feedback_score: float = 0.0
    created_at: datetime
    updated_at: datetime
    staleness: StalenessLabel | None = None
    last_verified_at: datetime | None = None
    promotion_state: PromotionState = PromotionState.INJECTABLE

    @model_validator(mode="after")
    def _sync_quarantine_marker(self) -> MemoryEntry:
        """Keep ``promotion_state`` and the legacy ``source_ref`` prefix in agreement.

        The prefix wins when both are supplied and disagree: it is what every
        pre-existing writer and reader uses, so it is the representation that
        must never be silently overridden while the compat window is open.
        """
        if has_unpromoted_prefix(self.source_ref):
            if self.promotion_state is not PromotionState.QUARANTINED:
                self.promotion_state = PromotionState.QUARANTINED
        elif self.promotion_state is PromotionState.QUARANTINED:
            self.source_ref = add_unpromoted_prefix(self.source_ref)
        return self
