from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from oh_no_my_claudecode.models.llm import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMSettings,
)

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)
JSON_ONLY_INSTRUCTION = (
    "You must respond with ONLY valid JSON. "
    "No markdown fences, no preamble, no explanation. Raw JSON only."
)
logger = logging.getLogger(__name__)


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
        response = self.generate(json_only_request(request))
        parsed: Any | None = None
        try:
            parsed = parse_llm_json(response.text)
        except json.JSONDecodeError as exc:
            logger.error(
                "LLM returned unparseable response. Raw: %s",
                response.text[:500],
            )
            msg = "Provider response was not valid JSON for structured parsing."
            raise LLMProviderError(msg) from exc
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            logger.error(
                "LLM returned parseable but invalid JSON. Parsed: %s. Error: %s",
                parsed,
                exc,
            )
            msg = "Provider response did not match the expected structured schema."
            raise LLMProviderError(msg) from exc


def json_only_request(request: LLMGenerationRequest) -> LLMGenerationRequest:
    """Return a request with a strict JSON-only system instruction appended."""
    existing = request.system_prompt.strip() if request.system_prompt else ""
    system_prompt = (
        f"{existing}\n\n{JSON_ONLY_INSTRUCTION}" if existing else JSON_ONLY_INSTRUCTION
    )
    return request.model_copy(update={"system_prompt": system_prompt})


def parse_llm_json(text: str) -> Any:
    """Parse JSON from LLM response text, including fenced and prefixed outputs."""
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    object_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if object_match:
        return json.loads(object_match.group(1))
    raise json.JSONDecodeError("No valid JSON found in response", stripped, 0)
