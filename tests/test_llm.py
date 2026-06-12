from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from oh_no_my_claudecode.config import load_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import (
    AnthropicProvider,
    LLMConfigurationError,
    LLMProviderError,
    MockProvider,
    OpenAIProvider,
    generate_logged,
    provider_from_settings,
)
from oh_no_my_claudecode.llm import providers as llm_providers
from oh_no_my_claudecode.llm import runtime as llm_runtime
from oh_no_my_claudecode.llm.providers import _provider_http_error_message
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    LLMProviderType,
    LLMSettings,
)

ANTHROPIC_SUCCESS_BODY = json.dumps(
    {"content": [{"type": "text", "text": "recovered"}]}
).encode("utf-8")
OPENAI_SUCCESS_BODY = json.dumps(
    {"choices": [{"message": {"content": "fallback ok"}}]}
).encode("utf-8")
OPENAI_MAX_COMPLETION_TOKENS_400_BODY = (
    b'{"error":{"message":"Unsupported parameter: max_completion_tokens is not '
    b'supported with this model. Use max_tokens instead.",'
    b'"type":"invalid_request_error"}}'
)


class _FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def _http_error(
    code: int,
    body: bytes,
    headers: dict[str, str] | None = None,
) -> urllib.error.HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(
        "https://api.example.com/v1",
        code,
        "error",
        message,
        io.BytesIO(body),
    )


def _anthropic_provider() -> AnthropicProvider:
    return AnthropicProvider(
        LLMSettings(
            provider=LLMProviderType.ANTHROPIC,
            model="claude-sonnet-4-5",
            api_key_env_var="ANTHROPIC_API_KEY",
        ),
        api_key="test-key",
    )


def _openai_provider() -> OpenAIProvider:
    return OpenAIProvider(
        LLMSettings(
            provider=LLMProviderType.OPENAI,
            model="gpt-4o-mini",
            api_key_env_var="OPENAI_API_KEY",
            max_tokens=512,
        ),
        api_key="test-key",
    )


def test_llm_config_round_trip(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, settings = service.configure_llm(
        provider=LLMProviderType.ANTHROPIC,
        model="claude-sonnet-4-5",
        api_key_env_var="ANTHROPIC_API_KEY",
        temperature=0.1,
        max_tokens=900,
    )

    loaded = load_config(sample_repo)
    assert settings.provider == LLMProviderType.ANTHROPIC
    assert loaded.llm.provider == LLMProviderType.ANTHROPIC
    assert loaded.llm.model == "claude-sonnet-4-5"
    assert loaded.llm.api_key_env_var == "ANTHROPIC_API_KEY"
    assert loaded.llm.temperature == 0.1
    assert loaded.llm.max_tokens == 900


def test_provider_selection_uses_configured_provider() -> None:
    anthropic = provider_from_settings(
        LLMSettings(
            provider=LLMProviderType.ANTHROPIC,
            model="claude-sonnet-4-5",
            api_key_env_var="ANTHROPIC_API_KEY",
        ),
        environ={"ANTHROPIC_API_KEY": "test-key"},
    )
    openai = provider_from_settings(
        LLMSettings(
            provider=LLMProviderType.OPENAI,
            model="gpt-4o-mini",
            api_key_env_var="OPENAI_API_KEY",
        ),
        environ={"OPENAI_API_KEY": "test-key"},
    )
    mock = provider_from_settings(
        LLMSettings(
            provider=LLMProviderType.MOCK,
            model="mock-model",
        )
    )

    assert isinstance(anthropic, AnthropicProvider)
    assert isinstance(openai, OpenAIProvider)
    assert isinstance(mock, MockProvider)


def test_anthropic_model_not_found_error_is_actionable() -> None:
    message = _provider_http_error_message(
        status_code=404,
        details=(
            '{"type":"error","error":{"type":"not_found_error",'
            '"message":"model: claude-3-5-sonnet-latest"}}'
        ),
        provider=LLMProviderType.ANTHROPIC,
        model="claude-3-5-sonnet-latest",
    )

    assert "Anthropic model not found" in message
    assert "claude-sonnet-4-5" in message


def test_missing_credentials_raise_clear_error() -> None:
    with pytest.raises(LLMConfigurationError, match="Missing API key"):
        provider_from_settings(
            LLMSettings(
                provider=LLMProviderType.OPENAI,
                model="gpt-4o-mini",
                api_key_env_var="OPENAI_API_KEY",
            ),
            environ={},
        )


def test_mock_provider_supports_text_and_structured_generation() -> None:
    class MockPayload(BaseModel):
        summary: str

    provider = provider_from_settings(
        LLMSettings(
            provider=LLMProviderType.MOCK,
            model="mock-model",
        ),
        mock_response_text='{"summary":"mocked"}',
    )
    response = provider.generate(LLMGenerationRequest(prompt="Return JSON."))
    payload = provider.generate_structured(
        LLMGenerationRequest(prompt="Return JSON."),
        MockPayload,
    )

    assert response.text == '{"summary":"mocked"}'
    assert payload.summary == "mocked"


def test_rate_limited_requests_are_retried_with_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request: object, timeout: float | None = None) -> _FakeHTTPResponse:
        attempts["count"] += 1
        if attempts["count"] <= 2:
            raise _http_error(429, b'{"error":{"type":"rate_limit_error","message":"slow down"}}')
        return _FakeHTTPResponse(ANTHROPIC_SUCCESS_BODY)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(llm_providers, "_sleep", sleeps.append)

    response = _anthropic_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert response.text == "recovered"
    assert attempts["count"] == 3
    assert len(sleeps) == 2
    assert 1.0 <= sleeps[0] <= 1.25
    assert 2.0 <= sleeps[1] <= 2.5


def test_retry_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request: object, timeout: float | None = None) -> _FakeHTTPResponse:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _http_error(
                529,
                b'{"error":{"type":"overloaded_error","message":"Overloaded"}}',
                headers={"Retry-After": "7"},
            )
        return _FakeHTTPResponse(ANTHROPIC_SUCCESS_BODY)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(llm_providers, "_sleep", sleeps.append)

    response = _anthropic_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert response.text == "recovered"
    assert sleeps == [7.0]


def test_auth_errors_are_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = {"count": 0}
    sleeps: list[float] = []

    def fake_urlopen(request: object, timeout: float | None = None) -> _FakeHTTPResponse:
        attempts["count"] += 1
        raise _http_error(401, b'{"error":{"type":"authentication_error","message":"bad key"}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(llm_providers, "_sleep", sleeps.append)

    with pytest.raises(LLMProviderError, match="HTTP 401"):
        _anthropic_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert attempts["count"] == 1
    assert sleeps == []


def test_openai_sends_max_completion_tokens_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeHTTPResponse:
        captured.append(json.loads(request.data.decode("utf-8")))
        return _FakeHTTPResponse(OPENAI_SUCCESS_BODY)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    _openai_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert len(captured) == 1
    assert captured[0]["max_completion_tokens"] == 512
    assert "max_tokens" not in captured[0]


def test_openai_falls_back_to_max_tokens_when_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeHTTPResponse:
        captured.append(json.loads(request.data.decode("utf-8")))
        if len(captured) == 1:
            raise _http_error(400, OPENAI_MAX_COMPLETION_TOKENS_400_BODY)
        return _FakeHTTPResponse(OPENAI_SUCCESS_BODY)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(llm_providers, "_sleep", sleeps.append)

    response = _openai_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert response.text == "fallback ok"
    assert len(captured) == 2
    assert sleeps == []
    assert captured[0]["max_completion_tokens"] == 512
    assert "max_completion_tokens" not in captured[1]
    assert captured[1]["max_tokens"] == 512


def test_openai_unrelated_400_is_not_retried_with_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"count": 0}

    def fake_urlopen(request: object, timeout: float | None = None) -> _FakeHTTPResponse:
        attempts["count"] += 1
        raise _http_error(400, b'{"error":{"message":"messages is required"}}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LLMProviderError, match="HTTP 400"):
        _openai_provider().generate(LLMGenerationRequest(prompt="hello"))

    assert attempts["count"] == 1


def test_llm_call_log_redacts_prompts_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONMC_LOG_FULL_PROMPTS", raising=False)
    log_path = tmp_path / "logs" / "llm-calls.jsonl"
    provider = MockProvider(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        response_text="r" * 600,
    )

    text = generate_logged(
        provider,
        LLMGenerationRequest(prompt="p" * 600, system_prompt="s" * 600),
        log_path=log_path,
        operation="test-op",
    )
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])

    assert text == "r" * 600
    assert entry["operation"] == "test-op"
    assert entry["provider"] == "mock"
    assert entry["model"] == "mock-model"
    assert entry["error"] is None
    assert entry["latency_ms"] >= 0
    assert entry["prompt_token_count"] >= 1
    assert entry["prompt"] == "p" * 200 + " …[truncated 400 chars]"
    assert entry["system_prompt"] == "s" * 200 + " …[truncated 400 chars]"
    assert entry["response_text"] == "r" * 200 + " …[truncated 400 chars]"


def test_llm_call_log_keeps_full_prompts_when_env_flag_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONMC_LOG_FULL_PROMPTS", "1")
    log_path = tmp_path / "logs" / "llm-calls.jsonl"
    provider = MockProvider(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        response_text="r" * 600,
    )

    generate_logged(
        provider,
        LLMGenerationRequest(prompt="p" * 600, system_prompt="s" * 600),
        log_path=log_path,
        operation="test-op",
    )
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])

    assert entry["prompt"] == "p" * 600
    assert entry["system_prompt"] == "s" * 600
    assert entry["response_text"] == "r" * 600


def test_llm_call_log_rotates_when_over_size_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONMC_LOG_FULL_PROMPTS", raising=False)
    log_path = tmp_path / "llm-calls.jsonl"
    rotated_path = tmp_path / "llm-calls.jsonl.1"
    log_path.write_bytes(b"x" * (llm_runtime.LOG_ROTATE_BYTES + 1))
    rotated_path.write_text("stale rotation", encoding="utf-8")
    provider = MockProvider(
        LLMSettings(provider=LLMProviderType.MOCK, model="mock-model"),
        response_text="fresh",
    )

    generate_logged(
        provider,
        LLMGenerationRequest(prompt="hello"),
        log_path=log_path,
        operation="test-op",
    )

    assert rotated_path.read_bytes().startswith(b"x")
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["response_text"] == "fresh"
