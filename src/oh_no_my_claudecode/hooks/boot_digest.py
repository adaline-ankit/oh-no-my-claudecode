from __future__ import annotations

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, TaskRecord, TaskStatus
from oh_no_my_claudecode.models.skill import Skill
from oh_no_my_claudecode.utils.text import shorten, tokenize

# Maximum token budget for the entire boot digest (full mode).
BOOT_DIGEST_MAX_TOKENS = 400

# How many entries to include per high-signal section (full mode).
_MAX_INVARIANTS = 3
_MAX_HOTSPOTS = 3
_MAX_ACTIVE_TASKS = 2
_MAX_USER_PREFS = 5

# Max skills to surface in the boot digest.
_MAX_BOOT_SKILLS = 2


def compile_boot_digest(
    *,
    memories: list[MemoryEntry],
    tasks: list[TaskRecord],
    repo_name: str,
    user_memories: list[MemoryEntry] | None = None,
    skills: list[Skill] | None = None,
    terse: bool | None = None,
) -> tuple[str, int]:
    """Compile a compact boot digest from repo memory for session startup injection.

    The digest is intentionally small (≤ ~400 tokens) so it is a helpful reminder
    rather than a full brief. It is emitted on every session start (startup / resume /
    clear) so agents always boot with the repo brain.

    *user_memories* is an optional list of user-scope preference memories (from
    ``~/.onmc/user.db``).  Up to ``_MAX_USER_PREFS`` are prepended as a small
    "Your preferences" section so they travel with the developer across all repos.

    *skills* is an optional list of Skill objects.  Up to ``_MAX_BOOT_SKILLS``
    auto_inject skills (ranked by confidence) are appended as a compact section so
    agents boot with the repo's top know-how without waiting for a prompt.

    *terse*: When None, respects ONMC_VERBOSE / ONMC_TERSE env vars with the hook
    default (terse=True). Pass True/False to override.

    Returns ``(markdown, token_count)``. When there is nothing to say (empty
    memories, no active tasks, no user prefs, and no skills) the function returns
    ``("", 0)`` so callers can skip injection entirely.
    """
    # Resolve terse flag — boot_digest runs as a hook, so default is terse.
    if terse is None:
        from oh_no_my_claudecode.serialize.terse import is_terse

        terse = is_terse(default=True)  # hook default: terse

    invariants = _select_kind(
        memories, {MemoryKind.INVARIANT, MemoryKind.DECISION, MemoryKind.VALIDATION_RULE}
    )
    hotspots = _select_kind(
        memories, {MemoryKind.HOTSPOT, MemoryKind.GOTCHA, MemoryKind.FAILED_APPROACH}
    )
    active_tasks = [t for t in tasks if t.status == TaskStatus.ACTIVE]
    prefs = [m for m in (user_memories or []) if m.feedback_score > -0.5]
    top_skills = _select_top_skills(skills or [], max_items=_MAX_BOOT_SKILLS)

    if not invariants and not hotspots and not active_tasks and not prefs and not top_skills:
        return "", 0

    if terse:
        from oh_no_my_claudecode.serialize.terse import render_boot_digest_terse

        text = render_boot_digest_terse(
            invariants=invariants,
            hotspots=hotspots,
            active_tasks=active_tasks,
            repo_name=repo_name,
            prefs=prefs,
        )
        # Append compact skills lines if any.
        if top_skills:
            from oh_no_my_claudecode.serialize.skill_renderer import render_skills_terse

            skills_text = render_skills_terse(top_skills, max_items=_MAX_BOOT_SKILLS)
            if skills_text:
                text = f"{text}\n{skills_text}" if text else skills_text
        if not text:
            return "", 0
        token_count = len(tokenize(text))
        return text, token_count

    # Full markdown mode.
    lines: list[str] = [f"## Repo brain: {repo_name}", ""]

    if prefs:
        lines.append("### Your preferences")
        for memory in prefs[:_MAX_USER_PREFS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=100)}")
        lines.append("")

    if invariants:
        lines.append("### Key invariants & decisions")
        for memory in invariants[:_MAX_INVARIANTS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=120)}")
        lines.append("")

    if hotspots:
        lines.append("### Hotspots & gotchas")
        for memory in hotspots[:_MAX_HOTSPOTS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=120)}")
        lines.append("")

    if active_tasks:
        lines.append("### Active tasks")
        for task in active_tasks[:_MAX_ACTIVE_TASKS]:
            lines.append(f"- `{task.task_id}` {shorten(task.title, max_length=80)}")
        lines.append("")

    if top_skills:
        lines.append("### Top skills")
        for skill in top_skills:
            lines.append(f"- **{skill.name}**: {shorten(skill.trigger, max_length=120)}")
        lines.append("")

    markdown = "\n".join(lines).rstrip() + "\n"
    token_count = len(tokenize(markdown))

    if token_count <= BOOT_DIGEST_MAX_TOKENS:
        return markdown, token_count

    # Trim to fit the token budget.
    markdown = _trim_boot_digest(
        invariants=invariants,
        hotspots=hotspots,
        active_tasks=active_tasks,
        repo_name=repo_name,
        prefs=prefs,
        top_skills=top_skills,
    )
    return markdown, len(tokenize(markdown))


def _select_kind(memories: list[MemoryEntry], kinds: set[MemoryKind]) -> list[MemoryEntry]:
    """Return memories of the given kinds, sorted by confidence descending."""
    selected = [m for m in memories if m.kind in kinds and m.feedback_score > -0.5]
    selected.sort(key=lambda m: (-m.confidence, m.title))
    return selected


def _select_top_skills(skills: list[Skill], *, max_items: int) -> list[Skill]:
    """Return top auto_inject skills sorted by confidence descending."""
    eligible = [sk for sk in skills if sk.auto_inject]
    eligible.sort(key=lambda sk: (-sk.confidence, sk.name))
    return eligible[:max_items]


def _trim_boot_digest(
    *,
    invariants: list[MemoryEntry],
    hotspots: list[MemoryEntry],
    active_tasks: list[TaskRecord],
    repo_name: str,
    prefs: list[MemoryEntry] | None = None,
    top_skills: list[Skill] | None = None,
) -> str:
    """Produce a hard-trimmed version that fits within the token budget."""
    lines: list[str] = [f"## Repo brain: {repo_name}", ""]

    if prefs:
        lines.append("### Your preferences")
        for memory in (prefs or [])[:3]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=80)}")
        lines.append("")

    if invariants:
        lines.append("### Key invariants & decisions")
        for memory in invariants[:2]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=80)}")
        lines.append("")

    if hotspots:
        lines.append("### Hotspots & gotchas")
        for memory in hotspots[:2]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=80)}")
        lines.append("")

    if active_tasks:
        lines.append("### Active tasks")
        task = active_tasks[0]
        lines.append(f"- `{task.task_id}` {shorten(task.title, max_length=60)}")
        lines.append("")

    if top_skills:
        lines.append("### Top skills")
        for skill in (top_skills or [])[:1]:
            lines.append(f"- **{skill.name}**: {shorten(skill.trigger, max_length=80)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
