from __future__ import annotations

import os
from collections.abc import Mapping

from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMConfigurationError
from oh_no_my_claudecode.llm.providers import AnthropicProvider, MockProvider, OpenAIProvider
from oh_no_my_claudecode.models.llm import LLMProviderType, LLMSettings, LLMStatus

DEFAULT_PROVIDER_ENV_VARS = {
    LLMProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
    LLMProviderType.OPENAI: "OPENAI_API_KEY",
}


def default_api_key_env_var(provider: LLMProviderType) -> str | None:
    return DEFAULT_PROVIDER_ENV_VARS.get(provider)


def llm_status(
    settings: LLMSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> LLMStatus:
    env = environ or os.environ
    api_key_env_var = _resolved_api_key_env_var(settings)
    return LLMStatus(
        configured=settings.provider is not None and settings.model is not None,
        provider=settings.provider,
        model=settings.model,
        api_key_env_var=api_key_env_var,
        credentials_present=bool(api_key_env_var and env.get(api_key_env_var)),
    )


def provider_from_settings(
    settings: LLMSettings,
    *,
    environ: Mapping[str, str] | None = None,
    mock_response_text: str = "mock response",
) -> BaseLLMProvider:
    if settings.provider is None:
        msg = "LLM provider is not configured."
        raise LLMConfigurationError(msg)
    if settings.model is None:
        msg = "LLM model is not configured."
        raise LLMConfigurationError(msg)
    env = environ or os.environ
    if settings.provider == LLMProviderType.MOCK:
        return MockProvider(settings, response_text=mock_response_text)

    api_key_env_var = _resolved_api_key_env_var(settings)
    if api_key_env_var is None:
        msg = f"No API key environment variable is configured for {settings.provider.value}."
        raise LLMConfigurationError(msg)
    api_key = env.get(api_key_env_var)
    if not api_key:
        msg = (
            f"Missing API key for {settings.provider.value}. "
            f"Set {api_key_env_var} before using the provider."
        )
        raise LLMConfigurationError(msg)

    if settings.provider == LLMProviderType.ANTHROPIC:
        return AnthropicProvider(settings, api_key=api_key)
    if settings.provider == LLMProviderType.OPENAI:
        return OpenAIProvider(settings, api_key=api_key)

    msg = f"Unsupported LLM provider: {settings.provider.value}"
    raise LLMConfigurationError(msg)


def _resolved_api_key_env_var(settings: LLMSettings) -> str | None:
    if settings.api_key_env_var:
        return settings.api_key_env_var
    if settings.provider is None:
        return None
    return default_api_key_env_var(settings.provider)
