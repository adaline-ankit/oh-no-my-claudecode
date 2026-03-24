from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

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
    reasoning_map: list[str] = Field(default_factory=list)
    system_lesson: str
    false_lead_analysis: list[str] = Field(default_factory=list)
    mental_model_upgrade: str
