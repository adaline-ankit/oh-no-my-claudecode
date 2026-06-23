from __future__ import annotations

import contextlib
from pathlib import Path

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

# Max profile items per bucket to surface in boot digest.
_MAX_PROFILE_ITEMS = 2


def compile_boot_digest(
    *,
    memories: list[MemoryEntry],
    tasks: list[TaskRecord],
    repo_name: str,
    user_memories: list[MemoryEntry] | None = None,
    skills: list[Skill] | None = None,
    terse: bool | None = None,
    repo_root: Path | None = None,
) -> tuple[str, int]:
    """Compile a compact boot digest from repo memory for session startup injection.

    The digest is intentionally small (≤ ~400 tokens) so it is a helpful reminder
    rather than a full brief. It is emitted on every session start (startup / resume /
    clear) so agents always boot with the repo brain.

    *user_memories* is an optional list of user-scope preference memories (from
    ``~/.onmc/user.db``).  Up to ``_MAX_USER_PREFS`` are prepended as a small
    "Your preferences" section so they travel with the developer across all repos.
    A compact derived "Your profile" block (preferences + mistakes-to-avoid) is
    also injected when user memories are present.

    *skills* is an optional list of Skill objects.  Up to ``_MAX_BOOT_SKILLS``
    auto_inject skills (ranked by confidence) are appended as a compact section so
    agents boot with the repo's top know-how without waiting for a prompt.

    *terse*: When None, respects ONMC_VERBOSE / ONMC_TERSE env vars with the hook
    default (terse=True). Pass True/False to override.

    *repo_root*: Optional path used by the context firewall to locate the sink.
    Defaults to ``Path.cwd()`` when not supplied.

    Returns ``(markdown, token_count)``. When there is nothing to say (empty
    memories, no active tasks, no user prefs, and no skills) the function returns
    ``("", 0)`` so callers can skip injection entirely.

    Context firewall: when digest text is produced, a ``recall_surfaced`` event is
    emitted to the side sink for observability.  Set ``ONMC_FIREWALL=0`` to disable.
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

    # Derive a compact user profile from user memories (graceful-empty on missing db).
    profile = _compile_profile_safe(prefs)

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
        # Append compact profile lines (mistakes-to-avoid) in terse mode when verbose.
        profile_text = _render_profile_terse(profile)
        if profile_text:
            text = f"{text}\n{profile_text}" if text else profile_text
        # Append compact skills lines if any.
        if top_skills:
            from oh_no_my_claudecode.serialize.skill_renderer import render_skills_terse

            skills_text = render_skills_terse(top_skills, max_items=_MAX_BOOT_SKILLS)
            if skills_text:
                text = f"{text}\n{skills_text}" if text else skills_text
        if not text:
            return "", 0
        token_count = len(tokenize(text))
        _firewall_emit_boot_recall(repo_root, token_count)
        _firewall_emit_profile_injected(repo_root, profile)
        return text, token_count

    # Full markdown mode.
    lines: list[str] = [f"## Repo brain: {repo_name}", ""]

    if prefs:
        lines.append("### Your preferences")
        for memory in prefs[:_MAX_USER_PREFS]:
            lines.append(f"- **{memory.title}**: {shorten(memory.summary, max_length=100)}")
        lines.append("")

    # Derived profile block — compact mistakes + extra preferences not already listed.
    _append_profile_lines(lines, profile)

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
        _firewall_emit_boot_recall(repo_root, token_count)
        _firewall_emit_profile_injected(repo_root, profile)
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
    token_count = len(tokenize(markdown))
    _firewall_emit_boot_recall(repo_root, token_count)
    _firewall_emit_profile_injected(repo_root, profile)
    return markdown, token_count


def _firewall_emit_boot_recall(repo_root: Path | None, token_count: int) -> None:
    """Emit a recall_surfaced event to the side sink (exception-safe)."""
    with contextlib.suppress(Exception):
        from oh_no_my_claudecode.hooks.firewall import firewall_emit
        from oh_no_my_claudecode.notify import EventKind, EventSeverity, NotifyEvent

        _root = repo_root if repo_root is not None else Path.cwd()
        firewall_emit(
            _root,
            NotifyEvent(
                kind=EventKind.RECALL_SURFACED,
                severity=EventSeverity.ROUTINE,
                title="boot-digest injected into context",
                detail=f"tokens≈{token_count}",
            ),
        )


def _firewall_emit_profile_injected(repo_root: Path | None, profile: object) -> None:
    """Emit an observability event when a non-empty profile was injected (exception-safe)."""
    with contextlib.suppress(Exception):
        from oh_no_my_claudecode.hooks.firewall import firewall_emit
        from oh_no_my_claudecode.notify import EventKind, EventSeverity, NotifyEvent
        from oh_no_my_claudecode.profile.compiler import UserProfile

        if not isinstance(profile, UserProfile) or profile.is_empty:
            return
        _root = repo_root if repo_root is not None else Path.cwd()
        firewall_emit(
            _root,
            NotifyEvent(
                kind=EventKind.GENERIC,
                severity=EventSeverity.ROUTINE,
                title="user-profile injected into boot-digest",
                detail=f"derived_from={profile.derived_from}",
            ),
        )


def _compile_profile_safe(prefs: list[MemoryEntry]) -> object:
    """Compile a UserProfile from *prefs*, returning an empty profile on any error."""
    with contextlib.suppress(Exception):
        from oh_no_my_claudecode.profile.compiler import compile_user_profile

        return compile_user_profile(prefs)
    # Return a sentinel empty object that passes is_empty checks.
    from oh_no_my_claudecode.profile.compiler import UserProfile

    return UserProfile()


def _append_profile_lines(lines: list[str], profile: object) -> None:
    """Append a compact '### Your profile' block to *lines* when the profile has data.

    Only mistakes-to-avoid are added here (preferences already surfaced above).
    Under ONMC_VERBOSE, also adds tooling signals.
    """
    with contextlib.suppress(Exception):
        from oh_no_my_claudecode.profile.compiler import UserProfile
        from oh_no_my_claudecode.serialize.terse import is_terse

        if not isinstance(profile, UserProfile) or profile.is_empty:
            return

        verbose = not is_terse(default=True)
        profile_lines: list[str] = []

        if profile.frequent_mistakes:
            profile_lines.append("### Mistakes to avoid")
            for title, summary in profile.frequent_mistakes[:_MAX_PROFILE_ITEMS]:
                profile_lines.append(
                    f"- **{title}**: {shorten(summary, max_length=100)}"
                )
            profile_lines.append("")

        if verbose and profile.tooling:
            profile_lines.append("### Tooling preferences")
            for title, summary in profile.tooling[:_MAX_PROFILE_ITEMS]:
                profile_lines.append(
                    f"- **{title}**: {shorten(summary, max_length=100)}"
                )
            profile_lines.append("")

        lines.extend(profile_lines)


def _render_profile_terse(profile: object) -> str:
    """Render compact MISTAKE: lines for the terse boot digest.

    Returns an empty string when the profile is empty or on any error.
    Only mistakes-to-avoid are surfaced in terse mode to keep token budget tight.
    """
    with contextlib.suppress(Exception):
        from oh_no_my_claudecode.profile.compiler import UserProfile

        if not isinstance(profile, UserProfile) or profile.is_empty:
            return ""
        if not profile.frequent_mistakes:
            return ""
        parts = []
        for title, _summary in profile.frequent_mistakes[:_MAX_PROFILE_ITEMS]:
            # Keep it terse: just the title
            parts.append(f"MISTAKE: {title}")
        return "\n".join(parts)
    return ""


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
