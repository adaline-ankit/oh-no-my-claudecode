"""Tests for the ``proxy`` module — OpenAI-compatible local proxy.

Coverage
--------
1.  ``to_provider_request`` — OpenAI body → LLMGenerationRequest mapping.
2.  ``to_openai_response`` — LLMGenerationResponse → OpenAI response shape.
3.  ``to_openai_response`` id/usage/choices fields present and correct types.
4.  ``to_openai_error`` — OpenAI-shaped error JSON structure.
5.  ``to_openai_models_response`` — ``GET /v1/models`` shape.
6.  Handler with injected fake provider — POST /v1/chat/completions (no socket).
7.  Handler with injected fake provider — GET /v1/models (no socket).
8.  No-provider-configured → graceful CLI exit code 1 and error message.
9.  Malformed body → 400 OpenAI-error JSON from handler.
10. Determinism of pure mappers (same input → identical output, modulo timestamps).
11. Ephemeral-port round-trip: full HTTP request via ProxyServer(port=0).
12. System messages extracted as system_prompt; non-system messages as prompt.
"""

from __future__ import annotations

import io
import json
import time
import urllib.request
from threading import Thread
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models.llm import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMProviderType,
    LLMSettings,
)
from oh_no_my_claudecode.proxy.server import (
    ProxyServer,
    make_handler,
    to_openai_error,
    to_openai_models_response,
    to_openai_response,
    to_provider_request,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_SETTINGS = LLMSettings(provider=LLMProviderType.MOCK, model="mock-model")


class _FakeProvider(BaseLLMProvider):
    """Deterministic fake provider for unit tests — never makes network calls."""

    def __init__(self, response_text: str = "Hello from fake provider") -> None:
        super().__init__(_MOCK_SETTINGS)
        self.response_text = response_text
        self.last_request: LLMGenerationRequest | None = None

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        self.last_request = request
        return LLMGenerationResponse(
            provider=LLMProviderType.MOCK,
            model="mock-model",
            text=self.response_text,
            raw={"prompt": request.prompt},
        )


class _ErrorProvider(BaseLLMProvider):
    """Provider that always raises LLMProviderError."""

    def __init__(self) -> None:
        super().__init__(_MOCK_SETTINGS)

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        raise LLMProviderError("backend unavailable", status_code=503)


def _make_raw_request(
    method: str,
    path: str,
    body: bytes | None = None,
    *,
    port: int,
) -> tuple[int, dict[str, Any]]:
    """Fire a raw HTTP request to the proxy on localhost:port.  Returns (status, json)."""
    url = f"http://127.0.0.1:{port}{path}"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def _handler_response(
    handler_cls: type,
    method: str,
    path: str,
    body: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    """Call a handler instance directly (no socket) and return (status, json)."""
    wfile = io.BytesIO()
    rfile = io.BytesIO(body or b"")

    handler = handler_cls.__new__(handler_cls)
    handler.rfile = rfile
    handler.wfile = wfile
    handler.path = path
    handler.headers = {"Content-Length": str(len(body)) if body else "0"}
    handler.command = method

    status_holder: list[int] = []
    headers_sent: list[tuple[str, str]] = []
    headers_ended = False

    def _send_response(code: int, message: str | None = None) -> None:  # noqa: ARG001
        status_holder.append(code)

    def _send_header(key: str, value: str) -> None:
        headers_sent.append((key, value))

    def _end_headers() -> None:
        nonlocal headers_ended
        headers_ended = True

    handler.send_response = _send_response  # type: ignore[method-assign]
    handler.send_header = _send_header  # type: ignore[method-assign]
    handler.end_headers = _end_headers  # type: ignore[method-assign]

    if method == "POST":
        handler.do_POST()
    else:
        handler.do_GET()

    status = status_holder[0] if status_holder else 200
    wfile.seek(0)
    payload = json.loads(wfile.read().decode("utf-8"))
    return status, payload


# ---------------------------------------------------------------------------
# 1. to_provider_request — OpenAI body → LLMGenerationRequest
# ---------------------------------------------------------------------------

class TestToProviderRequest:
    def test_single_user_message(self) -> None:
        body = {"messages": [{"role": "user", "content": "Hello, world!"}]}
        req = to_provider_request(body)
        assert req.prompt == "Hello, world!"
        assert req.system_prompt is None

    def test_system_plus_user_messages(self) -> None:
        body = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What is 2+2?"},
            ]
        }
        req = to_provider_request(body)
        assert req.system_prompt == "You are a helpful assistant."
        assert "What is 2+2?" in req.prompt

    def test_temperature_mapped(self) -> None:
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7,
        }
        req = to_provider_request(body)
        assert req.temperature == pytest.approx(0.7)

    def test_max_tokens_mapped(self) -> None:
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 256,
        }
        req = to_provider_request(body)
        assert req.max_tokens == 256

    def test_max_completion_tokens_fallback(self) -> None:
        body = {
            "messages": [{"role": "user", "content": "hi"}],
            "max_completion_tokens": 512,
        }
        req = to_provider_request(body)
        assert req.max_tokens == 512

    def test_multiple_system_messages_concatenated(self) -> None:
        body = {
            "messages": [
                {"role": "system", "content": "Part one."},
                {"role": "system", "content": "Part two."},
                {"role": "user", "content": "Go."},
            ]
        }
        req = to_provider_request(body)
        assert req.system_prompt == "Part one.\n\nPart two."

    def test_assistant_turn_included_in_prompt(self) -> None:
        body = {
            "messages": [
                {"role": "user", "content": "Q?"},
                {"role": "assistant", "content": "A."},
                {"role": "user", "content": "Follow-up?"},
            ]
        }
        req = to_provider_request(body)
        assert "assistant:" in req.prompt
        assert "A." in req.prompt
        assert "Follow-up?" in req.prompt

    def test_empty_messages_gives_empty_prompt(self) -> None:
        req = to_provider_request({"messages": []})
        assert req.prompt == ""
        assert req.system_prompt is None

    def test_missing_messages_key(self) -> None:
        req = to_provider_request({})
        assert req.prompt == ""

    def test_content_block_list_extracted(self) -> None:
        """Vision-style content blocks — only text blocks are used."""
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image."},
                        {"type": "image_url", "image_url": {"url": "data:..."}},
                    ],
                }
            ]
        }
        req = to_provider_request(body)
        assert "Describe this image." in req.prompt


# ---------------------------------------------------------------------------
# 2 & 3. to_openai_response — shape, id, usage, choices
# ---------------------------------------------------------------------------

class TestToOpenaiResponse:
    def _make_response(self, text: str = "42") -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider=LLMProviderType.MOCK,
            model="mock-model",
            text=text,
            raw={},
        )

    def test_top_level_fields_present(self) -> None:
        resp = to_openai_response(self._make_response())
        assert resp["object"] == "chat.completion"
        assert "id" in resp
        assert "created" in resp
        assert "model" in resp
        assert "choices" in resp
        assert "usage" in resp

    def test_id_starts_with_chatcmpl(self) -> None:
        resp = to_openai_response(self._make_response())
        assert resp["id"].startswith("chatcmpl-")

    def test_custom_request_id_used(self) -> None:
        resp = to_openai_response(self._make_response(), request_id="chatcmpl-abc123")
        assert resp["id"] == "chatcmpl-abc123"

    def test_choices_shape(self) -> None:
        resp = to_openai_response(self._make_response("Hello!"))
        choices = resp["choices"]
        assert len(choices) == 1
        choice = choices[0]
        assert choice["index"] == 0
        assert choice["finish_reason"] == "stop"
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == "Hello!"

    def test_usage_field_types(self) -> None:
        resp = to_openai_response(self._make_response("word " * 100))
        usage = resp["usage"]
        assert isinstance(usage["prompt_tokens"], int)
        assert isinstance(usage["completion_tokens"], int)
        assert isinstance(usage["total_tokens"], int)
        assert usage["completion_tokens"] >= 1

    def test_model_id_from_provider_result(self) -> None:
        resp = to_openai_response(self._make_response())
        assert resp["model"] == "mock-model"

    def test_created_is_recent_unix_timestamp(self) -> None:
        before = int(time.time()) - 1
        resp = to_openai_response(self._make_response())
        after = int(time.time()) + 1
        assert before <= resp["created"] <= after


# ---------------------------------------------------------------------------
# 4. to_openai_error — error shape
# ---------------------------------------------------------------------------

class TestToOpenaiError:
    def test_error_shape(self) -> None:
        err = to_openai_error("Something went wrong", status_code=502)
        assert err["object"] == "error"
        assert err["error"]["message"] == "Something went wrong"
        assert err["error"]["code"] == 502
        assert "type" in err["error"]

    def test_custom_error_type(self) -> None:
        err = to_openai_error("bad input", error_type="invalid_request_error")
        assert err["error"]["type"] == "invalid_request_error"

    def test_id_field_present(self) -> None:
        err = to_openai_error("x")
        assert "id" in err


# ---------------------------------------------------------------------------
# 5. to_openai_models_response — /v1/models shape
# ---------------------------------------------------------------------------

class TestToOpenaiModelsResponse:
    def test_models_shape(self) -> None:
        resp = to_openai_models_response("gpt-4o")
        assert resp["object"] == "list"
        assert len(resp["data"]) == 1
        entry = resp["data"][0]
        assert entry["id"] == "gpt-4o"
        assert entry["object"] == "model"
        assert "owned_by" in entry

    def test_model_id_propagated(self) -> None:
        resp = to_openai_models_response("claude-sonnet-4-5")
        assert resp["data"][0]["id"] == "claude-sonnet-4-5"


# ---------------------------------------------------------------------------
# 6 & 7. Handler tests with injected fake provider (no real socket)
# ---------------------------------------------------------------------------

class TestHandlerNoSocket:
    def test_post_chat_completions_success(self) -> None:
        provider = _FakeProvider("The answer is 42.")
        handler_cls = make_handler(provider)
        body = json.dumps({
            "messages": [{"role": "user", "content": "What is the answer?"}]
        }).encode()

        status, payload = _handler_response(handler_cls, "POST", "/v1/chat/completions", body)

        assert status == 200
        assert payload["object"] == "chat.completion"
        assert payload["choices"][0]["message"]["content"] == "The answer is 42."

    def test_get_models_success(self) -> None:
        provider = _FakeProvider()
        handler_cls = make_handler(provider)

        status, payload = _handler_response(handler_cls, "GET", "/v1/models")

        assert status == 200
        assert payload["object"] == "list"
        assert any(e["id"] == "mock-model" for e in payload["data"])

    def test_provider_error_returns_502(self) -> None:
        provider = _ErrorProvider()
        handler_cls = make_handler(provider)
        body = json.dumps({
            "messages": [{"role": "user", "content": "hi"}]
        }).encode()

        status, payload = _handler_response(handler_cls, "POST", "/v1/chat/completions", body)

        assert status == 502
        assert payload["object"] == "error"
        assert "backend unavailable" in payload["error"]["message"]

    def test_unknown_get_path_returns_404(self) -> None:
        handler_cls = make_handler(_FakeProvider())
        status, payload = _handler_response(handler_cls, "GET", "/v1/unknown")
        assert status == 404
        assert payload["object"] == "error"

    def test_unknown_post_path_returns_404(self) -> None:
        handler_cls = make_handler(_FakeProvider())
        body = json.dumps({}).encode()
        status, payload = _handler_response(handler_cls, "POST", "/not/a/real/path", body)
        assert status == 404


# ---------------------------------------------------------------------------
# 8. No-provider-configured → graceful CLI exit
# ---------------------------------------------------------------------------

class TestNoProviderGracefulExit:
    def test_proxy_serve_no_provider_exits_nonzero(self) -> None:
        """proxy serve must exit 1 and print a clear error when no LLM is configured."""
        runner = CliRunner()

        from oh_no_my_claudecode.core import repo as _repo_mod
        from oh_no_my_claudecode.core import service as _svc_mod
        from oh_no_my_claudecode.llm import factory as _factory
        from oh_no_my_claudecode.llm.base import LLMConfigurationError as _LLMConfigErr

        # Patch at the actual module level (lazy imports inside the command function).
        with (
            patch.object(_repo_mod, "discover_repo_root", return_value=MagicMock()),
            patch.object(
                _svc_mod.OnmcService,
                "_load_context",
                side_effect=Exception("no config"),
            ),
            patch.object(
                _factory,
                "provider_from_settings",
                side_effect=_LLMConfigErr("LLM provider is not configured."),
            ),
        ):
            result = runner.invoke(app, ["proxy", "serve", "--port", "19999"])

        assert result.exit_code == 1
        # Error message goes to stderr (typer err=True), which CliRunner mixes into output.
        assert "error:" in result.output


# ---------------------------------------------------------------------------
# 9. Malformed body → 400
# ---------------------------------------------------------------------------

class TestMalformedBody:
    def test_non_json_body_returns_400(self) -> None:
        handler_cls = make_handler(_FakeProvider())
        bad_body = b"this is not json {"

        status, payload = _handler_response(
            handler_cls, "POST", "/v1/chat/completions", bad_body
        )

        assert status == 400
        assert payload["error"]["type"] == "invalid_request_error"

    def test_json_array_body_returns_400(self) -> None:
        handler_cls = make_handler(_FakeProvider())
        body = json.dumps([1, 2, 3]).encode()

        status, payload = _handler_response(
            handler_cls, "POST", "/v1/chat/completions", body
        )

        assert status == 400
        assert payload["error"]["type"] == "invalid_request_error"


# ---------------------------------------------------------------------------
# 10. Determinism of pure mappers
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_to_provider_request_deterministic(self) -> None:
        body = {
            "messages": [
                {"role": "system", "content": "System."},
                {"role": "user", "content": "Question?"},
            ],
            "temperature": 0.5,
            "max_tokens": 128,
        }
        req1 = to_provider_request(body)
        req2 = to_provider_request(body)
        assert req1.prompt == req2.prompt
        assert req1.system_prompt == req2.system_prompt
        assert req1.temperature == req2.temperature
        assert req1.max_tokens == req2.max_tokens

    def test_to_openai_models_response_deterministic(self) -> None:
        resp1 = to_openai_models_response("test-model")
        resp2 = to_openai_models_response("test-model")
        assert resp1["data"][0]["id"] == resp2["data"][0]["id"]
        assert resp1["object"] == resp2["object"]


# ---------------------------------------------------------------------------
# 11. Ephemeral-port round-trip (real socket, ephemeral port)
# ---------------------------------------------------------------------------

class TestEphemeralPortRoundTrip:
    def test_post_chat_completions_full_roundtrip(self) -> None:
        """Bind to port 0 (OS picks), make one request, shut down."""
        provider = _FakeProvider("Pong!")
        with ProxyServer(provider, host="127.0.0.1", port=0) as srv:
            port = srv.port
            assert port > 0

            # Serve in a background thread.
            t = Thread(target=srv.handle_one_request, daemon=True)
            t.start()

            body = json.dumps({
                "messages": [{"role": "user", "content": "Ping?"}]
            }).encode()
            status, payload = _make_raw_request(
                "POST", "/v1/chat/completions", body, port=port
            )
            t.join(timeout=3)

        assert status == 200
        assert payload["choices"][0]["message"]["content"] == "Pong!"

    def test_get_models_full_roundtrip(self) -> None:
        """GET /v1/models round-trip on an ephemeral port."""
        provider = _FakeProvider()
        with ProxyServer(provider, host="127.0.0.1", port=0) as srv:
            port = srv.port

            t = Thread(target=srv.handle_one_request, daemon=True)
            t.start()

            status, payload = _make_raw_request("GET", "/v1/models", port=port)
            t.join(timeout=3)

        assert status == 200
        assert payload["object"] == "list"
        assert payload["data"][0]["id"] == "mock-model"
