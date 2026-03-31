from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from oh_no_my_claudecode.models.llm import LLMGenerationRequest


class AgentMode(StrEnum):
    SOLVE = "solve"
    REVIEW = "review"
    TEACH = "teach"


class CompiledPrompt(BaseModel):
    mode: AgentMode
    task_id: str
    task_title: str
    system_prompt: str
    prompt: str
    section_titles: list[str] = Field(default_factory=list)
    output_contract: str

    def to_generation_request(self) -> LLMGenerationRequest:
        return LLMGenerationRequest(
            prompt=self.prompt,
            system_prompt=self.system_prompt,
        )


class SolveModeOutput(BaseModel):
    approach_summary: str
    files_to_inspect: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    validations: list[str] = Field(default_factory=list)
    confidence: str


class ReviewModeOutput(BaseModel):
    concerns: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    likely_regressions: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)


class TeachModeOutput(BaseModel):
    problem_this_solves: str
    approach_chosen_and_why: str
    what_was_tried_first: list[str] = Field(default_factory=list)
    current_implementation: str
    what_would_break: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    reasoning_map: list[str] = Field(default_factory=list)
    system_lesson: str | None = None
    false_lead_analysis: list[str] = Field(default_factory=list)
    mental_model_upgrade: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_teach_shape(cls, data: object) -> object:
        """Accept both the original and God Mode teach output contracts."""
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        reasoning_map = payload.get("reasoning_map")
        system_lesson = payload.get("system_lesson")
        false_lead_analysis = payload.get("false_lead_analysis")
        mental_model_upgrade = payload.get("mental_model_upgrade")
        payload.setdefault(
            "problem_this_solves",
            (
                "Use the repo memory to understand the problem framing before changing code."
            ),
        )
        payload.setdefault(
            "approach_chosen_and_why",
            system_lesson
            or mental_model_upgrade
            or "The repo memory points to the core system boundary first.",
        )
        payload.setdefault(
            "what_was_tried_first",
            list(false_lead_analysis) if isinstance(false_lead_analysis, list) else [],
        )
        payload.setdefault(
            "current_implementation",
            "\n".join(reasoning_map)
            if isinstance(reasoning_map, list) and reasoning_map
            else "Use the highest-signal files and invariants from the brief.",
        )
        payload.setdefault(
            "what_would_break",
            list(false_lead_analysis) if isinstance(false_lead_analysis, list) else [],
        )
        payload.setdefault("open_questions", [])
        payload.setdefault("validation", [])
        return payload
