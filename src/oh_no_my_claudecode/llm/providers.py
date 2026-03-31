from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from oh_no_my_claudecode.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    llm_call_timeout_seconds,
)
from oh_no_my_claudecode.models.llm import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMProviderType,
    LLMSettings,
)


class AnthropicProvider(BaseLLMProvider):
    api_url = "https://api.anthropic.com/v1/messages"

    def __init__(self, settings: LLMSettings, api_key: str) -> None:
        super().__init__(settings)
        self.api_key = api_key

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        model = self._require_model()
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens or self.settings.max_tokens,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.settings.temperature
            ),
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        raw = _post_json(
            self.api_url,
            payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            provider=LLMProviderType.ANTHROPIC,
            model=model,
        )
        content = raw.get("content", [])
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            msg = "Anthropic response did not contain text content."
            raise LLMProviderError(msg)
        return LLMGenerationResponse(
            provider=LLMProviderType.ANTHROPIC,
            model=model,
            text=text,
            raw=raw,
        )

    def _require_model(self) -> str:
        if self.settings.model:
            return self.settings.model
        msg = "Anthropic provider requires a configured model."
        raise LLMProviderError(msg)


class OpenAIProvider(BaseLLMProvider):
    api_url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, settings: LLMSettings, api_key: str) -> None:
        super().__init__(settings)
        self.api_key = api_key

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        model = self._require_model()
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        raw = _post_json(
            self.api_url,
            {
                "model": model,
                "temperature": (
                    request.temperature
                    if request.temperature is not None
                    else self.settings.temperature
                ),
                "max_tokens": request.max_tokens or self.settings.max_tokens,
                "messages": messages,
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            provider=LLMProviderType.OPENAI,
            model=model,
        )
        choices = raw.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            msg = "OpenAI response did not contain text content."
            raise LLMProviderError(msg)
        return LLMGenerationResponse(
            provider=LLMProviderType.OPENAI,
            model=model,
            text=content.strip(),
            raw=raw,
        )

    def _require_model(self) -> str:
        if self.settings.model:
            return self.settings.model
        msg = "OpenAI provider requires a configured model."
        raise LLMProviderError(msg)


class MockProvider(BaseLLMProvider):
    def __init__(self, settings: LLMSettings, *, response_text: str = "mock response") -> None:
        super().__init__(settings)
        self.response_text = response_text

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        text = self.response_text
        if text == "mock response":
            text = _default_mock_response(request.prompt)
        return LLMGenerationResponse(
            provider=LLMProviderType.MOCK,
            model=self.settings.model or "mock-model",
            text=text,
            raw={
                "prompt": request.prompt,
                "system_prompt": request.system_prompt,
            },
        )


def _post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: Mapping[str, str],
    provider: LLMProviderType | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(  # noqa: S310 - provider URLs are fixed https endpoints.
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            **dict(headers),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - provider request target is prevalidated above.
            request,
            timeout=llm_call_timeout_seconds(),
        ) as response:
            body = response.read().decode("utf-8")
    except TimeoutError as exc:
        msg = "Provider request timed out."
        raise LLMProviderError(msg) from exc
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        msg = _provider_http_error_message(
            status_code=exc.code,
            details=details,
            provider=provider,
            model=model,
        )
        raise LLMProviderError(msg) from exc
    except urllib.error.URLError as exc:
        if "timed out" in str(exc.reason).lower():
            msg = "Provider request timed out."
            raise LLMProviderError(msg) from exc
        msg = f"Provider request failed: {exc.reason}"
        raise LLMProviderError(msg) from exc

    try:
        payload_obj = json.loads(body)
    except json.JSONDecodeError as exc:
        msg = "Provider response was not valid JSON."
        raise LLMProviderError(msg) from exc
    if not isinstance(payload_obj, dict):
        msg = "Provider response root was not a JSON object."
        raise LLMProviderError(msg)
    return payload_obj


def _provider_http_error_message(
    *,
    status_code: int,
    details: str,
    provider: LLMProviderType | None,
    model: str | None,
) -> str:
    parsed_details = _parse_error_payload(details)
    if (
        provider == LLMProviderType.ANTHROPIC
        and status_code == 404
        and parsed_details.get("error_type") == "not_found_error"
        and parsed_details.get("error_message", "").startswith("model:")
    ):
        requested_model = model or parsed_details["error_message"].split("model:", 1)[1].strip()
        return (
            "Anthropic model not found: "
            f"{requested_model}. Configure a current model such as "
            "`claude-sonnet-4-5`, "
            "or list models available to your key with "
            "`curl https://api.anthropic.com/v1/models --header \"x-api-key: $ANTHROPIC_API_KEY\" "
            "--header \"anthropic-version: 2023-06-01\"`."
        )
    return f"Provider request failed with HTTP {status_code}: {details}"


def _parse_error_payload(details: str) -> dict[str, str]:
    try:
        payload = json.loads(details)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {}
    error_type = error.get("type")
    error_message = error.get("message")
    return {
        "error_type": error_type if isinstance(error_type, str) else "",
        "error_message": error_message if isinstance(error_message, str) else "",
    }


def _default_mock_response(prompt: str) -> str:
    if '"approach_summary"' in prompt:
        return json.dumps(
            {
                "approach_summary": (
                    "Inspect the highest-signal repo files first and preserve "
                    "recorded constraints."
                ),
                "files_to_inspect": ["src/cache.py", "tests/test_cache.py"],
                "risks": ["Repeated churn in the cache path may hide coupling."],
                "validations": ["pytest", "ruff check ."],
                "confidence": "medium",
            }
        )
    if '"required_tests"' in prompt:
        return json.dumps(
            {
                "concerns": ["The proposed change may miss the caller path."],
                "assumptions": ["Existing tests cover the failing path."],
                "likely_regressions": ["Worker refresh behavior."],
                "required_tests": ["tests/test_cache.py"],
            }
        )
    if '"current_implementation"' in prompt:
        return json.dumps(
            {
                "problem_this_solves": "The task needs repo-specific context and guardrails.",
                "approach_chosen_and_why": (
                    "Start from the execution boundary and the recorded invariants."
                ),
                "what_was_tried_first": ["A narrower fix missed the adjacent caller path."],
                "current_implementation": (
                    "The current implementation routes work through a shared boundary."
                ),
                "what_would_break": ["Bypassing the shared boundary would violate the invariant."],
                "open_questions": ["Double-check the adjacent test coverage."],
                "validation": ["pytest", "ruff check ."],
                "reasoning_map": ["Trace the shared boundary first."],
                "system_lesson": "System boundaries are more reliable than local symptoms.",
                "false_lead_analysis": ["A narrower fix missed the adjacent caller path."],
                "mental_model_upgrade": "Start from the boundary that coordinates the workflow.",
            }
        )
    if '"markdown"' in prompt or "Follow-up question:" in prompt:
        return json.dumps(
            {
                "markdown": (
                    "The config-only approach failed because the problem lived at the shared "
                    "execution boundary rather than in a tunable leaf setting."
                ),
            }
        )
    return json.dumps({"summary": "mocked"})
