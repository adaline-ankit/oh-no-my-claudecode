"""Deterministic skill promoter — no LLM required.

Public API:
- ``promote_playbook_to_skill``  — lift a single Playbook into a Skill.
- ``auto_promote_recurring``     — detect recurring fail→fix patterns or
  high-signal repeated tag clusters and emit new Skill objects.
- ``rank_skills``                — order skills by relevance + success rate +
  confidence for injection candidates.

All functions are pure (no side-effects, no DB writes) so the injection agent
can import them safely.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from oh_no_my_claudecode.models.memory import MemoryKind
from oh_no_my_claudecode.models.skill import Skill
from oh_no_my_claudecode.utils.text import stable_id, tokenize
from oh_no_my_claudecode.utils.time import utc_now

if TYPE_CHECKING:
    from oh_no_my_claudecode.models.memory import MemoryEntry
    from oh_no_my_claudecode.models.playbook import Playbook
    from oh_no_my_claudecode.storage.sqlite import SQLiteStorage

# ── Constants ──────────────────────────────────────────────────────────────────

# Minimum cluster size to auto-promote a recurring pattern.
_MIN_AUTO_CLUSTER = 2

# Maximum skills returned by auto_promote_recurring.
_MAX_AUTO_SKILLS = 20

# Memory kinds that indicate a recurring problem–fix pair.
_FAIL_KINDS = {MemoryKind.FAILED_APPROACH, MemoryKind.DESIGN_CONFLICT, MemoryKind.GOTCHA}
_FIX_KINDS = {MemoryKind.DECISION, MemoryKind.INVARIANT, MemoryKind.VALIDATION_RULE}

# Minimum combined score (confidence + feedback*0.3) to be promoted.
_MIN_SIGNAL_SCORE = 0.5

# Staleness: if last_used_at is older than this many days, demote rank.
_STALENESS_DAYS = 30


# ── Public functions ───────────────────────────────────────────────────────────


def promote_playbook_to_skill(
    playbook: Playbook,
    *,
    name: str | None = None,
) -> Skill:
    """Lift a Playbook into a Skill, deriving all fields from the playbook.

    The resulting Skill carries:
    - ``name``   — caller-supplied or derived from playbook title.
    - ``body``   — numbered steps joined into prose.
    - ``trigger``— copied verbatim from the playbook.
    - ``tags``   — copied from the playbook.
    - ``files``  — empty (no file-glob inference at this layer).
    - ``source_memory_ids`` — derived from playbook.grounded_in.
    - ``confidence`` — copied from the playbook.
    """
    now = utc_now()
    skill_name = name or playbook.title
    body = _steps_to_body(playbook.steps)
    source_ids = [item.memory_id for item in playbook.grounded_in]
    skill_id = stable_id("skill", "pb", playbook.id, prefix="sk")
    return Skill(
        id=skill_id,
        name=skill_name,
        body=body,
        trigger=playbook.trigger,
        tags=list(playbook.tags),
        files=[],
        source_memory_ids=source_ids,
        use_count=0,
        success_count=0,
        confidence=playbook.confidence,
        auto_inject=True,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )


def auto_promote_recurring(
    storage: SQLiteStorage,
    *,
    min_cluster_size: int = _MIN_AUTO_CLUSTER,
    max_skills: int = _MAX_AUTO_SKILLS,
) -> list[Skill]:
    """Detect recurring fail→fix patterns and high-signal tag clusters.

    Strategy (deterministic, no LLM):
    1. Load all memories from storage.
    2. Filter to high-signal entries (score >= _MIN_SIGNAL_SCORE).
    3. Cluster by tags (same approach as the playbook compiler).
    4. Within each cluster, check for at least one FAIL_KIND + one FIX_KIND
       memory — these represent a learnable "avoid X, do Y" pattern.
    5. Also emit a skill for pure fix/invariant clusters (even without a FAIL).
    6. Deduplicate by stable id; return up to max_skills sorted by confidence.

    Excludes memories that are already source_memory_ids of existing skills.
    """
    memories = storage.list_memories()
    existing_skills = storage.list_skills()
    already_sourced: set[str] = {
        mid for sk in existing_skills for mid in sk.source_memory_ids
    }

    candidates = [
        m
        for m in memories
        if _signal_score(m) >= _MIN_SIGNAL_SCORE
        and m.id not in already_sourced
        and m.feedback_score >= -0.4
    ]

    clusters = _cluster_by_tags(candidates)
    skills: list[Skill] = []
    seen_ids: set[str] = set()
    now = utc_now()

    for cluster_key, members in sorted(clusters.items()):
        if len(members) < min_cluster_size:
            continue
        fail_members = [m for m in members if m.kind in _FAIL_KINDS]
        fix_members = [m for m in members if m.kind in _FIX_KINDS]
        # Require at least one fix-kind; fail+fix pairs are preferred.
        if not fix_members:
            continue

        label = _label_from_key(cluster_key)
        has_fail = bool(fail_members)

        if has_fail:
            trigger = (
                f"When encountering {label.lower()} problems — "
                "apply the known fix pattern."
            )
        else:
            trigger = f"When working on {label.lower()} concerns."

        body = _build_body(fail_members, fix_members)
        source_ids = [m.id for m in members]
        scores = [min(1.0, max(0.0, _signal_score(m))) for m in members]
        confidence = round(sum(scores) / len(scores), 4) if scores else 0.5
        tags = _union_tags(members)
        member_ids = sorted(m.id for m in members)
        skill_id = stable_id("skill", "auto", cluster_key, *member_ids, prefix="sk")

        if skill_id in seen_ids:
            continue
        seen_ids.add(skill_id)

        skills.append(
            Skill(
                id=skill_id,
                name=f"{label} Skill",
                body=body,
                trigger=trigger,
                tags=tags,
                files=_infer_files(members),
                source_memory_ids=source_ids,
                use_count=0,
                success_count=0,
                confidence=confidence,
                auto_inject=True,
                created_at=now,
                updated_at=now,
                last_used_at=None,
            )
        )

    skills.sort(key=lambda sk: (-sk.confidence, sk.name))
    return skills[:max_skills]


def rank_skills(
    skills: list[Skill],
    *,
    tags: list[str],
    files: list[str],
    now: datetime | None = None,
) -> list[Skill]:
    """Rank *skills* by relevance to the current context.

    Relevance factors (all multiplicative / additive, higher = better):
    1. Tag overlap with context tags.
    2. File prefix / glob overlap with context files.
    3. Success rate (success_count / max(1, use_count)).
    4. Confidence (0.0–1.0).
    5. Staleness demotion: if last_used_at is older than _STALENESS_DAYS,
       apply a small penalty.  Skills that have never been used are not penalised
       (they haven't had a chance to accumulate signal yet).

    Only skills with ``auto_inject=True`` are eligible for injection but this
    function ranks *all* supplied skills so callers can filter afterward.
    """
    effective_now = now or utc_now()
    tag_set = {t.lower().strip() for t in tags if t.strip()}
    file_set = set(files)

    def _score(skill: Skill) -> float:
        tag_overlap = len(tag_set & {t.lower().strip() for t in skill.tags})
        file_overlap = _file_overlap(skill.files, file_set)
        success_rate = skill.success_rate
        staleness_penalty = _staleness_penalty(skill, effective_now)
        return (
            tag_overlap * 2.0
            + file_overlap * 1.5
            + success_rate * 1.0
            + skill.confidence * 0.5
            - staleness_penalty
        )

    return sorted(skills, key=_score, reverse=True)


# ── Internal helpers ───────────────────────────────────────────────────────────


def _signal_score(memory: MemoryEntry) -> float:
    """Combined relevance score; mirrors the playbook compiler's formula."""
    return memory.confidence + memory.feedback_score * 0.3


def _steps_to_body(steps: list[str]) -> str:
    """Convert an ordered list of step strings into a numbered prose body."""
    if not steps:
        return ""
    return "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))


def _cluster_by_tags(memories: list[MemoryEntry]) -> dict[str, list[MemoryEntry]]:
    """Cluster memories by shared tags (same strategy as compile_playbooks)."""
    clusters: dict[str, list[MemoryEntry]] = defaultdict(list)
    for memory in memories:
        placed = False
        for tag in memory.tags:
            normalized = re.sub(r"\s+", "-", tag.strip().lower())
            if normalized:
                clusters[f"tag:{normalized}"].append(memory)
                placed = True
        if not placed:
            clusters["misc"].append(memory)
    return dict(clusters)


def _label_from_key(cluster_key: str) -> str:
    if cluster_key.startswith("tag:"):
        return cluster_key[4:].replace("-", " ").title()
    return cluster_key.replace("-", " ").replace("_", " ").title()


def _build_body(
    fail_members: list[MemoryEntry],
    fix_members: list[MemoryEntry],
) -> str:
    """Construct skill body from fail and fix memories."""
    lines: list[str] = []
    seen: set[str] = set()

    def _add(prefix: str, members: list[MemoryEntry]) -> None:
        for m in members:
            text = f"{prefix}: {m.summary.rstrip('.')}"
            norm = " ".join(tokenize(text))
            if norm and norm not in seen:
                seen.add(norm)
                lines.append(text)

    _add("Avoid", fail_members)
    _add("Apply", fix_members)
    return "\n".join(lines)


def _union_tags(members: list[MemoryEntry]) -> list[str]:
    seen: set[str] = set()
    tags: list[str] = []
    for m in members:
        for tag in m.tags:
            if tag and tag not in seen:
                seen.add(tag)
                tags.append(tag)
    return tags


def _infer_files(members: list[MemoryEntry]) -> list[str]:
    """Derive top-level path prefixes from source_refs as file hints."""
    prefixes: list[str] = []
    seen: set[str] = set()
    for m in members:
        ref = m.source_ref.split("|")[0].strip()
        parts = ref.replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[0] and parts[0] not in seen:
            seen.add(parts[0])
            prefixes.append(parts[0])
    return prefixes


def _file_overlap(skill_files: list[str], context_files: set[str]) -> float:
    """Count how many skill file prefixes/globs match any context file."""
    if not skill_files or not context_files:
        return 0.0
    count = 0
    for prefix in skill_files:
        if any(cf.startswith(prefix) or cf == prefix for cf in context_files):
            count += 1
    return float(count)


def _staleness_penalty(skill: Skill, now: datetime) -> float:
    """Small demotion if the skill has not been used recently.

    Returns 0.0 when the skill has never been used (fair chance) or was used
    within the staleness window.
    """
    if skill.last_used_at is None:
        return 0.0
    last = skill.last_used_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    eff_now = now
    if eff_now.tzinfo is None:
        eff_now = eff_now.replace(tzinfo=UTC)
    days_since = (eff_now - last).total_seconds() / 86_400
    if days_since > _STALENESS_DAYS:
        return min(1.0, (days_since - _STALENESS_DAYS) / _STALENESS_DAYS * 0.5)
    return 0.0
