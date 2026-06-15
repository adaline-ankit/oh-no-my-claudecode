from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from oh_no_my_claudecode.models.memory import MemoryEntry
from oh_no_my_claudecode.utils.text import shorten


class BriefStyle(StrEnum):
    FULL = "full"
    COMPACT = "compact"
    CAVEMAN = "caveman"


class BriefArtifact(BaseModel):
    task: str
    generated_at: datetime
    repo_root: str
    task_summary: str
    repo_overview: list[str] = Field(default_factory=list)
    relevant_memories: list[MemoryEntry] = Field(default_factory=list)
    relevance_reasons: dict[str, str] = Field(default_factory=dict)
    impacted_areas: list[str] = Field(default_factory=list)
    files_to_inspect: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    validation_checklist: list[str] = Field(default_factory=list)
    reading_list: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    output_path: str | None = None

    def to_markdown(self, *, style: BriefStyle | str = BriefStyle.FULL) -> str:
        resolved_style = style if isinstance(style, BriefStyle) else BriefStyle(style)
        if resolved_style == BriefStyle.COMPACT:
            return self._to_compact_markdown()
        if resolved_style == BriefStyle.CAVEMAN:
            return self._to_caveman_markdown()
        lines: list[str] = [
            "# ONMC Task Brief",
            "",
            f"- Task: {self.task}",
            f"- Generated: {self.generated_at.isoformat()}",
            f"- Repo: `{self.repo_root}`",
            "",
            "## Task",
            "",
            self.task_summary,
            "",
            "## Repo Overview",
            "",
        ]
        lines.extend(f"- {item}" for item in self.repo_overview)
        lines.extend(["", "## Most Relevant Memory", ""])
        if self.relevant_memories:
            for memory in self.relevant_memories:
                lines.append(f"### [{memory.kind.value}] {memory.title}")
                lines.append("")
                lines.append(f"- Summary: {memory.summary}")
                if reason := self.relevance_reasons.get(memory.id):
                    lines.append(f"- Relevant because: {reason}")
                lines.append(f"- Source: `{memory.source_type.value}:{memory.source_ref}`")
                lines.append(f"- Confidence: {memory.confidence:.2f}")
                lines.append("")
        else:
            lines.extend(
                [
                    "- No stored memory matched strongly; rely on repo structure and hotspots.",
                    "",
                ]
            )
        lines.extend(["## Likely Impacted Areas", ""])
        lines.extend(f"- {item}" for item in self.impacted_areas)
        lines.extend(["", "## Files To Inspect First", ""])
        lines.extend(f"1. `{item}`" for item in self.files_to_inspect)
        lines.extend(["", "## Risk Notes", ""])
        lines.extend(f"- {item}" for item in self.risk_notes)
        lines.extend(["", "## Validation Checklist", ""])
        lines.extend(f"- {item}" for item in self.validation_checklist)
        lines.extend(["", "## Next Reading List", ""])
        lines.extend(f"1. `{item}`" for item in self.reading_list)
        lines.extend(["", "## Provenance", ""])
        lines.extend(f"- {item}" for item in self.provenance)
        lines.append("")
        return "\n".join(lines)

    def _to_compact_markdown(self) -> str:
        lines = [
            "# ONMC Compact Brief",
            f"Task: {shorten(self.task, max_length=120)}",
            f"Repo: `{self.repo_root}`",
            "",
            "## Inspect First",
            *[f"- `{item}`" for item in self.files_to_inspect[:6]],
            "",
            "## Memory",
        ]
        if self.relevant_memories:
            for memory in self.relevant_memories[:4]:
                reason = self.relevance_reasons.get(memory.id)
                suffix = f" Reason: {shorten(reason, max_length=100)}" if reason else ""
                lines.append(
                    f"- {memory.kind.value}: {memory.title}. "
                    f"{shorten(memory.summary, max_length=140)}{suffix}"
                )
        else:
            lines.append("- No strong memory match.")
        lines.extend(
            [
                "",
                "## Risks",
                *[f"- {shorten(item, max_length=130)}" for item in self.risk_notes[:4]],
                "",
                "## Validate",
                *[
                    f"- {shorten(item, max_length=130)}"
                    for item in self.validation_checklist[:4]
                ],
                "",
                "## Provenance",
                *[f"- {shorten(item, max_length=120)}" for item in self.provenance[:4]],
                "",
            ]
        )
        return "\n".join(lines)

    def _to_caveman_markdown(self) -> str:
        lines = [
            "# ONMC Brief Caveman",
            f"Task: {shorten(self.task, max_length=100)}",
            f"Repo: `{self.repo_root}`",
            "",
            "## Files",
            *[f"- `{item}`" for item in self.files_to_inspect[:5]],
            "",
            "## Memory",
        ]
        if self.relevant_memories:
            for memory in self.relevant_memories[:3]:
                lines.append(
                    f"- {memory.kind.value}: {memory.title} -> "
                    f"{shorten(memory.summary, max_length=110)}"
                )
        else:
            lines.append("- No strong memory. Use files + tests.")
        lines.extend(
            [
                "",
                "## Risk",
                *[f"- {shorten(item, max_length=100)}" for item in self.risk_notes[:3]],
                "",
                "## Test",
                *[
                    f"- {shorten(item, max_length=100)}"
                    for item in self.validation_checklist[:3]
                ],
                "",
                "## Rule",
                "- Read listed files first. No broad grep dump. No repeat failed path.",
                "- Output terse. Bullets. File refs exact.",
                "",
            ]
        )
        return "\n".join(lines)
