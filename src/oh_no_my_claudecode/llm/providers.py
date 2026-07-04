from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from email.message import Message
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

MAX_REQUEST_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 1.0
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 529})
_sleep = time.sleep


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
        max_tokens_value = request.max_tokens or self.settings.max_tokens
        payload: dict[str, Any] = {
            "model": model,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.settings.temperature
            ),
            "max_completion_tokens": max_tokens_value,
            "messages": messages,
        }
        try:
            raw = _post_json(
                self.api_url,
                payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                provider=LLMProviderType.OPENAI,
                model=model,
            )
        except LLMProviderError as exc:
            if not _max_completion_tokens_unsupported(exc):
                raise
            fallback_payload = {
                key: value for key, value in payload.items() if key != "max_completion_tokens"
            }
            fallback_payload["max_tokens"] = max_tokens_value
            raw = _post_json(
                self.api_url,
                fallback_payload,
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


DEFAULT_OLLAMA_HOST = "http://localhost:11434"
OLLAMA_HOST_ENV_VAR = "ONMC_OLLAMA_HOST"


def ollama_host() -> str:
    """Return the configured Ollama base URL, defaulting to the local server."""
    return os.environ.get(OLLAMA_HOST_ENV_VAR, DEFAULT_OLLAMA_HOST).rstrip("/")


class OllamaProvider(BaseLLMProvider):
    """Optional local, free, offline LLM provider backed by an Ollama server.

    Talks to a local Ollama HTTP server (default ``http://localhost:11434``) over
    stdlib ``urllib`` — no extra dependency. When the server is not running or
    reachable, requests fail gracefully with a clear :class:`LLMProviderError`
    rather than crashing the process. Existing providers are unaffected.
    """

    def __init__(self, settings: LLMSettings, *, host: str | None = None) -> None:
        super().__init__(settings)
        self.host = (host or ollama_host()).rstrip("/")

    @property
    def api_url(self) -> str:
        return f"{self.host}/api/generate"

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        model = self._require_model()
        options: dict[str, Any] = {
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self.settings.temperature
            ),
            "num_predict": request.max_tokens or self.settings.max_tokens,
        }
        payload: dict[str, Any] = {
            "model": model,
            "prompt": request.prompt,
            "stream": False,
            "options": options,
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        raw = _post_json(
            self.api_url,
            payload,
            headers={},
            provider=LLMProviderType.OLLAMA,
            model=model,
        )
        text = raw.get("response")
        if not isinstance(text, str) or not text.strip():
            msg = "Ollama response did not contain text content."
            raise LLMProviderError(msg)
        return LLMGenerationResponse(
            provider=LLMProviderType.OLLAMA,
            model=model,
            text=text.strip(),
            raw=raw,
        )

    def _require_model(self) -> str:
        if self.settings.model:
            return self.settings.model
        msg = "Ollama provider requires a configured model."
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


LITELLM_UNAVAILABLE_MESSAGE = (
    "The litellm package is not installed. Install the optional extra with "
    "`pip install 'oh-no-my-claudecode[litellm]'` to use the unified LiteLLM provider."
)


def litellm_available() -> bool:
    """Return whether the optional ``litellm`` dependency can be imported.

    Guarded so the core package never hard-depends on litellm — when the extra
    is absent this reports ``False`` and existing providers stay untouched.
    """
    try:
        import litellm  # noqa: F401  - import probe only.
    except ImportError:
        return False
    return True


class LiteLLMProvider(BaseLLMProvider):
    """Optional unified provider that routes to ANY model via LiteLLM.

    One interface to OpenAI, Anthropic, Gemini, Groq, local servers, and every
    other backend LiteLLM supports. The model string is passed through verbatim
    (e.g. ``gpt-4o``, ``anthropic/claude-sonnet-4-5``, ``gemini/gemini-1.5-pro``,
    ``groq/llama-3.1-70b-versatile``, ``ollama/llama3``).

    ``litellm`` is an OPTIONAL extra. When it is not installed, construction and
    generation fail gracefully with a clear :class:`LLMProviderError` instead of
    crashing the process, and the built-in providers are unaffected. Credentials
    are read by litellm from the standard provider environment variables.
    """

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        model = self._require_model()
        completion = self._require_completion()
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        temperature = (
            request.temperature
            if request.temperature is not None
            else self.settings.temperature
        )
        max_tokens = request.max_tokens or self.settings.max_tokens
        try:
            raw_response = completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=llm_call_timeout_seconds(),
            )
        except Exception as exc:  # noqa: BLE001 - litellm raises a broad family of errors.
            msg = f"LiteLLM request failed: {exc}"
            raise LLMProviderError(msg) from exc
        text = _litellm_response_text(raw_response)
        if not text:
            msg = "LiteLLM response did not contain text content."
            raise LLMProviderError(msg)
        return LLMGenerationResponse(
            provider=LLMProviderType.LITELLM,
            model=model,
            text=text,
            raw=_litellm_response_raw(raw_response),
        )

    def _require_model(self) -> str:
        if self.settings.model:
            return self.settings.model
        msg = "LiteLLM provider requires a configured model."
        raise LLMProviderError(msg)

    @staticmethod
    def _require_completion() -> Any:
        try:
            import litellm
        except ImportError as exc:
            raise LLMProviderError(LITELLM_UNAVAILABLE_MESSAGE) from exc
        return litellm.completion


def _litellm_response_text(raw_response: Any) -> str:
    """Extract assistant text from a litellm ModelResponse (or dict-like)."""
    choices = _litellm_getattr(raw_response, "choices", [])
    if not choices:
        return ""
    message = _litellm_getattr(choices[0], "message", None)
    if message is None:
        return ""
    content = _litellm_getattr(message, "content", None)
    if not isinstance(content, str):
        return ""
    return content.strip()


def _litellm_response_raw(raw_response: Any) -> dict[str, Any]:
    """Best-effort conversion of a litellm response to a plain dict for logging."""
    for attr in ("model_dump", "dict"):
        converter = getattr(raw_response, attr, None)
        if callable(converter):
            converted = _safe_call_dict(converter)
            if converted is not None:
                return converted
    if isinstance(raw_response, dict):
        return raw_response
    return {}


def _safe_call_dict(converter: Any) -> dict[str, Any] | None:
    """Call a serializer and return its dict result, or None on any failure."""
    try:
        converted = converter()
    except Exception:  # noqa: BLE001 - logging metadata only, never fatal.
        return None
    return converted if isinstance(converted, dict) else None


def _litellm_getattr(obj: Any, name: str, default: Any) -> Any:
    """Read an attribute or mapping key — litellm objects support both."""
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


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
    for attempt in range(MAX_REQUEST_ATTEMPTS):
        retries_left = attempt + 1 < MAX_REQUEST_ATTEMPTS
        try:
            with urllib.request.urlopen(  # noqa: S310 - prevalidated provider URL.
                request,
                timeout=llm_call_timeout_seconds(),
            ) as response:
                body = response.read().decode("utf-8")
        except TimeoutError as exc:
            if retries_left:
                _sleep(_retry_delay_seconds(attempt))
                continue
            msg = "Provider request timed out."
            raise LLMProviderError(msg) from exc
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code in RETRYABLE_STATUS_CODES and retries_left:
                retry_after = _retry_after_seconds(exc.headers)
                _sleep(_retry_delay_seconds(attempt, retry_after=retry_after))
                continue
            msg = _provider_http_error_message(
                status_code=exc.code,
                details=details,
                provider=provider,
                model=model,
            )
            raise LLMProviderError(msg, status_code=exc.code, details=details) from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                if retries_left:
                    _sleep(_retry_delay_seconds(attempt))
                    continue
                msg = "Provider request timed out."
                raise LLMProviderError(msg) from exc
            msg = f"Provider request failed: {exc.reason}"
            raise LLMProviderError(msg) from exc
        return _parse_response_body(body)
    msg = "Provider request retries exhausted."
    raise LLMProviderError(msg)


def _parse_response_body(body: str) -> dict[str, Any]:
    try:
        payload_obj = json.loads(body)
    except json.JSONDecodeError as exc:
        msg = "Provider response was not valid JSON."
        raise LLMProviderError(msg) from exc
    if not isinstance(payload_obj, dict):
        msg = "Provider response root was not a JSON object."
        raise LLMProviderError(msg)
    return payload_obj


def _retry_delay_seconds(attempt: int, *, retry_after: float | None = None) -> float:
    if retry_after is not None and retry_after >= 0:
        return retry_after
    base: float = RETRY_BASE_DELAY_SECONDS * (2**attempt)
    jitter = random.uniform(0, base * 0.25)  # noqa: S311 - jitter, not cryptographic.
    return base + jitter


def _retry_after_seconds(headers: Message | None) -> float | None:
    if headers is None:
        return None
    raw_value = headers.get("Retry-After")
    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except ValueError:
        return None


def _max_completion_tokens_unsupported(error: LLMProviderError) -> bool:
    """Detect an HTTP 400 rejecting `max_completion_tokens` (older OpenAI models)."""
    if error.status_code != 400:
        return False
    details = error.details.lower()
    return "max_completion_tokens" in details and (
        "unsupported" in details or "not supported" in details
    )


def validate_provider_api_key(
    provider: LLMProviderType,
    api_key: str,
) -> tuple[bool, str]:
    """Validate provider credentials with a lightweight API request."""
    if provider == LLMProviderType.MOCK:
        return True, "Mock provider does not require validation."
    if provider == LLMProviderType.OLLAMA:
        return _validate_ollama_server()
    if provider == LLMProviderType.LITELLM:
        return _validate_litellm_available()
    url: str
    headers: dict[str, str]
    if provider == LLMProviderType.ANTHROPIC:
        url = "https://api.anthropic.com/v1/models"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    elif provider == LLMProviderType.OPENAI:
        url = "https://api.openai.com/v1/models"
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        return False, f"Unsupported LLM provider: {provider.value}"
    request = urllib.request.Request(  # noqa: S310 - provider URLs are fixed https endpoints.
        url,
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - provider request target is prevalidated above.
            request,
            timeout=llm_call_timeout_seconds(),
        ) as response:
            response.read()
    except TimeoutError:
        return False, "validation request timed out"
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return False, "invalid credentials"
        return False, f"provider returned HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = str(exc.reason)
        if "timed out" in reason.lower():
            return False, "validation request timed out"
        return False, reason
    return True, "valid"


def _validate_ollama_server() -> tuple[bool, str]:
    """Check that a local Ollama server is reachable — never raises, degrades gracefully."""
    url = f"{ollama_host()}/api/tags"
    request = urllib.request.Request(url, method="GET")  # noqa: S310 - local Ollama host.
    try:
        with urllib.request.urlopen(  # noqa: S310 - local Ollama host, keyless.
            request,
            timeout=llm_call_timeout_seconds(),
        ) as response:
            response.read()
    except TimeoutError:
        return False, "Ollama server request timed out"
    except urllib.error.HTTPError as exc:
        return False, f"Ollama server returned HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"Ollama server unavailable: {exc.reason}"
    except OSError as exc:
        return False, f"Ollama server unavailable: {exc}"
    return True, "Ollama server reachable"


def _validate_litellm_available() -> tuple[bool, str]:
    """Report whether the optional litellm extra is installed — never raises."""
    if litellm_available():
        return True, "litellm installed"
    return False, "litellm not installed"


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
