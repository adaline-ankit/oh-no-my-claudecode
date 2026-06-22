from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SkillProvenanceItem(BaseModel):
    """A single memory or playbook that grounds a skill."""

    memory_id: str
    title: str
    kind: str


class Skill(BaseModel):
    """A named, reusable, self-improving unit of know-how.

    Skills are synthesized from playbooks or detected recurring patterns and
    improve over time via feedback signals (``use_count``, ``success_count``,
    ``confidence``).  They live in the git-portable brain so they can later be
    exported to ``.agent-memory/`` and injected across Claude Code / Codex /
    Cursor sessions.
    """

    id: str
    name: str
    # Actionable know-how: the body of the skill (prose or numbered steps).
    body: str
    # Short relevance sentence — "when this applies".
    trigger: str
    tags: list[str] = Field(default_factory=list)
    # File glob / path prefixes that signal relevance.
    files: list[str] = Field(default_factory=list)
    # Provenance: source memory ids that contributed to this skill.
    source_memory_ids: list[str] = Field(default_factory=list)
    # Usage metrics for self-improvement signals.
    use_count: int = 0
    success_count: int = 0
    # Derived relevance score (0.0–1.0); starts at 0.5 and adjusts via feedback.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # When True the injection layer may surface this skill automatically.
    auto_inject: bool = True
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        """Success fraction — 0.0 when never used."""
        return self.success_count / max(1, self.use_count)
