from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LLMProviderType(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOCK = "mock"


class LLMSettings(BaseModel):
    provider: LLMProviderType | None = None
    model: str | None = None
    api_key_env_var: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)


class LLMGenerationRequest(BaseModel):
    prompt: str
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class LLMGenerationResponse(BaseModel):
    provider: LLMProviderType
    model: str
    text: str
    raw: dict[str, Any] | None = None


class LLMStatus(BaseModel):
    configured: bool
    provider: LLMProviderType | None = None
    model: str | None = None
    api_key_env_var: str | None = None
    credentials_present: bool = False
