from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from oh_no_my_claudecode.llm.base import (
    BaseLLMProvider,
    LLMProviderError,
    json_only_request,
    parse_llm_json,
)
from oh_no_my_claudecode.models import LLMGenerationRequest
from oh_no_my_claudecode.utils.text import tokenize
from oh_no_my_claudecode.utils.time import isoformat_utc, utc_now

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)
logger = logging.getLogger(__name__)
FULL_PROMPT_LOG_ENV_VAR = "ONMC_LOG_FULL_PROMPTS"
LOG_TEXT_PREVIEW_CHARS = 200
LOG_ROTATE_BYTES = 10 * 1024 * 1024


class MarkdownEnvelope(BaseModel):
    """Hold markdown returned through the structured LLM path."""

    markdown: str


def generate_logged(
    provider: BaseLLMProvider,
    request: LLMGenerationRequest,
    *,
    log_path: Path,
    operation: str,
) -> str:
    """Generate text through the provider and append a structured log entry."""
    started = time.monotonic()
    response_text = ""
    error: str | None = None
    try:
        response = provider.generate(request)
        response_text = response.text
        return response.text
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        _append_log(
            log_path=log_path,
            operation=operation,
            provider=provider.settings.provider.value if provider.settings.provider else "unknown",
            model=provider.settings.model or "unknown",
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            response_text=response_text,
            latency_ms=(time.monotonic() - started) * 1000,
            error=error,
        )


def generate_structured_logged(
    provider: BaseLLMProvider,
    request: LLMGenerationRequest,
    response_model: type[StructuredResultT],
    *,
    log_path: Path,
    operation: str,
) -> StructuredResultT:
    """Generate structured output, validate it, and append a structured log entry."""
    raw_text = generate_logged(
        provider,
        json_only_request(request),
        log_path=log_path,
        operation=operation,
    )
    parsed: object | None = None
    try:
        parsed = parse_llm_json(raw_text)
    except json.JSONDecodeError as exc:
        logger.error("LLM returned unparseable response. Raw: %s", raw_text[:500])
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


def _append_log(
    *,
    log_path: Path,
    operation: str,
    provider: str,
    model: str,
    prompt: str,
    system_prompt: str | None,
    response_text: str,
    latency_ms: float,
    error: str | None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _rotate_log_if_needed(log_path)
    prompt_token_count = len(tokenize(prompt))
    response_token_count = len(tokenize(response_text))
    log_full_prompts = os.environ.get(FULL_PROMPT_LOG_ENV_VAR) == "1"
    if not log_full_prompts:
        prompt = _truncate_for_log(prompt)
        system_prompt = _truncate_for_log(system_prompt) if system_prompt is not None else None
        response_text = _truncate_for_log(response_text)
    payload = {
        "timestamp": isoformat_utc(utc_now()),
        "operation": operation,
        "provider": provider,
        "model": model,
        "prompt_token_count": prompt_token_count,
        "response_token_count": response_token_count,
        "latency_ms": round(latency_ms, 2),
        "prompt": prompt,
        "system_prompt": system_prompt,
        "response_text": response_text,
        "error": error,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _truncate_for_log(text: str) -> str:
    if len(text) <= LOG_TEXT_PREVIEW_CHARS:
        return text
    truncated_chars = len(text) - LOG_TEXT_PREVIEW_CHARS
    return f"{text[:LOG_TEXT_PREVIEW_CHARS]} …[truncated {truncated_chars} chars]"


def _rotate_log_if_needed(log_path: Path) -> None:
    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        return
    if size > LOG_ROTATE_BYTES:
        log_path.replace(log_path.with_name(f"{log_path.name}.1"))
