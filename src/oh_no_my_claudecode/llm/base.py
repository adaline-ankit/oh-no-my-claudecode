from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from oh_no_my_claudecode.models.llm import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMSettings,
)

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class LLMError(RuntimeError):
    """Base error for optional LLM provider failures."""


class LLMConfigurationError(LLMError):
    """Raised when provider configuration or credentials are missing."""


class LLMProviderError(LLMError):
    """Raised when a provider request fails or returns an invalid response."""


class BaseLLMProvider(ABC):
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    @abstractmethod
    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        """Generate text from a prompt."""

    def generate_structured(
        self,
        request: LLMGenerationRequest,
        response_model: type[StructuredResultT],
    ) -> StructuredResultT:
        response = self.generate(request)
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "Provider response was not valid JSON for structured parsing."
            raise LLMProviderError(msg) from exc
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            msg = "Provider response did not match the expected structured schema."
            raise LLMProviderError(msg) from exc
