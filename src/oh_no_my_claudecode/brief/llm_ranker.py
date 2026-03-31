from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, RootModel

from oh_no_my_claudecode.llm import generate_structured_logged
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import LLMGenerationRequest, MemoryEntry


class RankedMemory(BaseModel):
    memory_id: str
    relevance_reason: str
    priority: int = Field(ge=1, le=10)


class RankedMemoryList(RootModel[list[RankedMemory]]):
    pass


def rerank_memories_with_llm(
    *,
    task: str,
    candidates: list[MemoryEntry],
    provider: BaseLLMProvider,
    log_path: Path,
) -> tuple[list[MemoryEntry], dict[str, str]]:
    """Re-rank candidate memory entries with LLM reasoning and annotate relevance."""
    filtered_candidates = [memory for memory in candidates if memory.feedback_score > -0.5]
    if not filtered_candidates:
        return [], {}
    payload: list[dict[str, object]] = [
        {
            "memory_id": memory.id,
            "kind": memory.kind.value,
            "title": memory.title,
            "summary": memory.summary,
            "source_type": memory.source_type.value,
            "source_ref": memory.source_ref,
            "confidence": memory.confidence,
            "feedback_score": memory.feedback_score,
        }
        for memory in filtered_candidates
    ]
    try:
        ranked = generate_structured_logged(
            provider,
            LLMGenerationRequest(
                system_prompt=(
                    "Return only valid JSON that matches the provided schema. "
                    "Do not include markdown fences."
                ),
                prompt=_ranking_prompt(task, payload),
                temperature=0.0,
                max_tokens=1400,
            ),
            RankedMemoryList,
            log_path=log_path,
            operation="brief.rerank",
        )
    except LLMProviderError:
        return filtered_candidates, {}

    by_id = {memory.id: memory for memory in filtered_candidates}
    ordered: list[MemoryEntry] = []
    reasons: dict[str, str] = {}
    def _sort_key(item: RankedMemory) -> tuple[float, str]:
        memory = by_id.get(item.memory_id)
        feedback_score = memory.feedback_score if memory is not None else 0.0
        return (-float(item.priority) - (feedback_score * 0.2), item.memory_id)

    for item in sorted(ranked.root, key=_sort_key):
        memory = by_id.get(item.memory_id)
        if memory is None:
            continue
        ordered.append(memory)
        reasons[memory.id] = item.relevance_reason
    if not ordered:
        return filtered_candidates, {}
    return ordered, reasons


def _ranking_prompt(task: str, candidates: list[dict[str, object]]) -> str:
    return (
        "You are selecting the most relevant engineering context for an AI coding agent "
        "about to work on a task.\n\n"
        f'Task: "{task}"\n\n'
        "Here are candidate memory records from this repository:\n"
        f"{json.dumps(candidates, indent=2, sort_keys=True)}\n\n"
        "Select the 8-12 most relevant records. For each selected record, explain in one "
        "sentence why it is relevant to this specific task.\n\n"
        "Return ONLY a JSON array:\n"
        "[\n"
        "  {\n"
        '    "memory_id": "...",\n'
        '    "relevance_reason": "one sentence",\n'
        '    "priority": 1-10\n'
        "  }\n"
        "]\n\n"
        "Prioritize:\n"
        "- records directly about files the task will likely touch\n"
        "- invariants that constrain how the task must be solved\n"
        "- prior failed approaches to avoid re-discovering dead ends\n"
        "- decisions that explain why the relevant code looks the way it does\n"
    )
