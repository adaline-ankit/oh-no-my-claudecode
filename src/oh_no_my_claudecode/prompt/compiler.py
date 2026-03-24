from __future__ import annotations

import json
from textwrap import dedent

from oh_no_my_claudecode.models import (
    AttemptRecord,
    AttemptStatus,
    BriefArtifact,
    MemoryArtifactRecord,
    MemoryArtifactType,
    TaskRecord,
)
from oh_no_my_claudecode.models.prompt import (
    AgentMode,
    CompiledPrompt,
    ReviewModeOutput,
    SolveModeOutput,
    TeachModeOutput,
)
from oh_no_my_claudecode.utils.text import shorten

MAX_REPO_MEMORY = 6
MAX_ATTEMPTS = 5
MAX_NEGATIVE_MEMORY = 5
MAX_VALIDATION_ITEMS = 6
MAX_FILES = 8


def compile_prompt(
    *,
    mode: AgentMode,
    task: TaskRecord,
    brief: BriefArtifact,
    attempts: list[AttemptRecord],
    memory_artifacts: list[MemoryArtifactRecord],
    supplemental_input: str | None = None,
) -> CompiledPrompt:
    section_map = _build_section_map(
        mode=mode,
        task=task,
        brief=brief,
        attempts=attempts,
        memory_artifacts=memory_artifacts,
        supplemental_input=supplemental_input,
    )
    output_contract = _output_contract(mode)
    sections = [f"## {title}\n{content}".rstrip() for title, content in section_map]
    prompt = "\n\n".join(
        [
            "# ONMC Compiled Prompt",
            "",
            "\n\n".join(sections),
            "",
            "## Output Contract",
            output_contract,
        ]
    ).strip()
    return CompiledPrompt(
        mode=mode,
        task_id=task.task_id,
        task_title=task.title,
        system_prompt=_system_prompt(mode),
        prompt=prompt,
        section_titles=[title for title, _ in section_map] + ["Output Contract"],
        output_contract=output_contract,
    )


def _build_section_map(
    *,
    mode: AgentMode,
    task: TaskRecord,
    brief: BriefArtifact,
    attempts: list[AttemptRecord],
    memory_artifacts: list[MemoryArtifactRecord],
    supplemental_input: str | None,
) -> list[tuple[str, str]]:
    sections = [
        ("Mode", _mode_goal(mode)),
        ("Instructions", _shared_instructions(mode)),
        ("Task", _task_block(task)),
        ("Repo Context", _repo_context_block(brief)),
        ("Relevant Repo Memory", _repo_memory_block(brief)),
        ("Prior Attempts", _attempts_block(attempts)),
        ("Negative Memory", _negative_memory_block(attempts, memory_artifacts)),
        ("Validation Guidance", _validation_block(brief, memory_artifacts)),
        ("Provenance", _provenance_block(brief, memory_artifacts)),
    ]
    if supplemental_input:
        sections.insert(6, ("External Input", _external_input_block(supplemental_input)))
    return sections


def _system_prompt(mode: AgentMode) -> str:
    base = (
        "You are operating inside ONMC, a memory-first coding-agent system. "
        "Reason from the provided repo brief and recorded task memory. "
        "Do not ignore prior failures, design conflicts, or validation guidance."
    )
    mode_specific = {
        AgentMode.SOLVE: (
            " Focus on the next best engineering approach. Be concrete, repo-aware, "
            "and avoid repeating known bad paths."
        ),
        AgentMode.REVIEW: (
            " Focus on critique. Surface brittle assumptions, review comments, "
            "architectural risks, and missing checks."
        ),
        AgentMode.TEACH: (
            " Focus on explanation. Teach how to reason through the problem like a "
            "staff engineer, using root-cause thinking and transferable lessons."
        ),
    }
    return base + mode_specific[mode]


def _mode_goal(mode: AgentMode) -> str:
    goals = {
        AgentMode.SOLVE: (
            "Use the memory spine below to propose the next best approach, likely files to "
            "inspect, major risks, and concrete validation steps."
        ),
        AgentMode.REVIEW: (
            "Use the memory spine below to critique a proposed or likely fix, focusing on "
            "assumptions, regressions, review comments, and missing tests."
        ),
        AgentMode.TEACH: (
            "Use the memory spine below to explain how to think about the task at a "
            "staff-engineer level, including false leads and system lessons."
        ),
    }
    return goals[mode]


def _shared_instructions(mode: AgentMode) -> str:
    lines = [
        "- Treat repo memory and design constraints as higher-signal than generic coding advice.",
        "- Use negative memory to avoid repeated failures or incompatible solutions.",
        "- Prefer concise, structured output over long prose.",
        "- Call out uncertainty rather than inventing repo facts.",
    ]
    mode_specific = {
        AgentMode.SOLVE: "- Recommend a practical next action sequence before broad exploration.",
        AgentMode.REVIEW: "- Assume the proposed fix may be incomplete; look for what it misses.",
        AgentMode.TEACH: "- Teach durable reasoning patterns, not just this task's final answer.",
    }
    lines.append(mode_specific[mode])
    return "\n".join(lines)


def _task_block(task: TaskRecord) -> str:
    return "\n".join(
        [
            f"- Task ID: {task.task_id}",
            f"- Title: {task.title}",
            f"- Description: {task.description}",
            f"- Status: {task.status.value}",
            f"- Branch: {task.branch}",
            f"- Labels: {', '.join(task.labels) if task.labels else '-'}",
            f"- Final summary: {task.final_summary or '-'}",
        ]
    )


def _repo_context_block(brief: BriefArtifact) -> str:
    lines = [
        f"- Repo summary: {brief.task_summary}",
        "- Repo overview:",
        *[f"  - {item}" for item in brief.repo_overview[:5]],
        "- Likely impacted areas:",
        *[f"  - {item}" for item in brief.impacted_areas[:5]],
        "- Files to inspect first:",
        *[f"  - {path}" for path in brief.files_to_inspect[:MAX_FILES]],
    ]
    return "\n".join(lines)


def _repo_memory_block(brief: BriefArtifact) -> str:
    if not brief.relevant_memories:
        return "- No high-confidence repo memory was selected for this task."
    lines = []
    for memory in brief.relevant_memories[:MAX_REPO_MEMORY]:
        lines.extend(
            [
                (
                    f"- [{memory.kind.value}] {memory.title}: "
                    f"{shorten(memory.summary, max_length=180)}"
                ),
                f"  - Source: {memory.source_type.value}:{memory.source_ref}",
                f"  - Confidence: {memory.confidence:.2f}",
            ]
        )
    return "\n".join(lines)


def _attempts_block(attempts: list[AttemptRecord]) -> str:
    if not attempts:
        return "- No prior attempts are stored for this task."
    lines = []
    for attempt in attempts[:MAX_ATTEMPTS]:
        evidence_bits = [
            bit
            for bit in [attempt.reasoning_summary, attempt.evidence_for, attempt.evidence_against]
            if bit
        ]
        evidence = shorten(" | ".join(evidence_bits), max_length=180) if evidence_bits else "-"
        lines.extend(
            [
                (
                    f"- [{attempt.status.value}] {attempt.kind.value}: "
                    f"{shorten(attempt.summary, max_length=140)}"
                ),
                f"  - Files: {', '.join(attempt.files_touched) if attempt.files_touched else '-'}",
                f"  - Evidence: {evidence}",
            ]
        )
    return "\n".join(lines)


def _negative_memory_block(
    attempts: list[AttemptRecord],
    memory_artifacts: list[MemoryArtifactRecord],
) -> str:
    entries: list[str] = []
    for attempt in attempts:
        if attempt.status in {AttemptStatus.REJECTED, AttemptStatus.PARTIAL}:
            evidence = attempt.evidence_against or attempt.reasoning_summary or "-"
            entries.append(
                f"- Attempt {attempt.attempt_id} [{attempt.status.value}]: "
                f"{shorten(attempt.summary, max_length=120)} | Why avoid: "
                f"{shorten(evidence, max_length=120)}"
            )
    for artifact in memory_artifacts:
        if artifact.type in {
            MemoryArtifactType.DID_NOT_WORK,
            MemoryArtifactType.DESIGN_CONFLICT,
        }:
            label = (
                "Design conflict"
                if artifact.type == MemoryArtifactType.DESIGN_CONFLICT
                else "Did not work"
            )
            guardrail = artifact.avoid_when or artifact.why_it_matters
            entries.append(
                f"- {label}: {artifact.title} | Summary: "
                f"{shorten(artifact.summary, max_length=110)} | Avoid because: "
                f"{shorten(guardrail, max_length=120)}"
            )
    if not entries:
        return "- No explicit failed approaches or design conflicts are stored yet."
    return "\n".join(entries[:MAX_NEGATIVE_MEMORY])


def _validation_block(
    brief: BriefArtifact,
    memory_artifacts: list[MemoryArtifactRecord],
) -> str:
    lines = [f"- {item}" for item in brief.validation_checklist[:MAX_VALIDATION_ITEMS]]
    for artifact in memory_artifacts:
        if artifact.type == MemoryArtifactType.VALIDATION:
            lines.append(f"- Task-derived validation: {shorten(artifact.summary, max_length=160)}")
    if not lines:
        return "- No explicit validation guidance was found."
    return "\n".join(lines[:MAX_VALIDATION_ITEMS])


def _provenance_block(
    brief: BriefArtifact,
    memory_artifacts: list[MemoryArtifactRecord],
) -> str:
    lines = [f"- {item}" for item in brief.provenance[:6]]
    for artifact in memory_artifacts[:3]:
        lines.append(f"- Task artifact: {artifact.type.value}:{artifact.memory_id}")
    return "\n".join(lines)


def _external_input_block(supplemental_input: str) -> str:
    return shorten(supplemental_input.strip(), max_length=2200)


def _output_contract(mode: AgentMode) -> str:
    if mode == AgentMode.SOLVE:
        schema = SolveModeOutput.model_json_schema()
    elif mode == AgentMode.REVIEW:
        schema = ReviewModeOutput.model_json_schema()
    else:
        schema = TeachModeOutput.model_json_schema()
    return dedent(
        f"""
        Return valid JSON only. Use this schema shape:
        {json.dumps(schema, indent=2, sort_keys=True)}
        """
    ).strip()
