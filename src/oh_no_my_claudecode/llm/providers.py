from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
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
        return LLMGenerationResponse(
            provider=LLMProviderType.MOCK,
            model=self.settings.model or "mock-model",
            text=self.response_text,
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
            timeout=30,
        ) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        msg = f"Provider request failed with HTTP {exc.code}: {details}"
        raise LLMProviderError(msg) from exc
    except urllib.error.URLError as exc:
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
