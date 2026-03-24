from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from oh_no_my_claudecode.config import load_config
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.llm import (
    AnthropicProvider,
    LLMConfigurationError,
    MockProvider,
    OpenAIProvider,
    provider_from_settings,
)
from oh_no_my_claudecode.llm.providers import _provider_http_error_message
from oh_no_my_claudecode.models import (
    LLMGenerationRequest,
    LLMProviderType,
    LLMSettings,
)


def test_llm_config_round_trip(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, settings = service.configure_llm(
        provider=LLMProviderType.ANTHROPIC,
        model="claude-3-7-sonnet-20250219",
        api_key_env_var="ANTHROPIC_API_KEY",
        temperature=0.1,
        max_tokens=900,
    )

    loaded = load_config(sample_repo)
    assert settings.provider == LLMProviderType.ANTHROPIC
    assert loaded.llm.provider == LLMProviderType.ANTHROPIC
    assert loaded.llm.model == "claude-3-7-sonnet-20250219"
    assert loaded.llm.api_key_env_var == "ANTHROPIC_API_KEY"
    assert loaded.llm.temperature == 0.1
    assert loaded.llm.max_tokens == 900


def test_provider_selection_uses_configured_provider() -> None:
    anthropic = provider_from_settings(
        LLMSettings(
            provider=LLMProviderType.ANTHROPIC,
            model="claude-3-7-sonnet-20250219",
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
    assert "claude-sonnet-4-20250514" in message
    assert "claude-3-7-sonnet-20250219" in message


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
