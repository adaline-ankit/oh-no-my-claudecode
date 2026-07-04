"""Core proxy server: pure mappers + HTTP handler factory.

Design
------
All transformation logic lives in pure functions (``to_provider_request``,
``to_openai_response``, ``to_openai_error``, ``to_openai_models_response``) so
they can be tested without binding any socket.  The ``make_handler`` factory
wires a :class:`~oh_no_my_claudecode.llm.base.BaseLLMProvider` into a
``BaseHTTPRequestHandler`` class suitable for ``http.server.HTTPServer``.
``ProxyServer`` bundles the server lifecycle (start / stop).

Supported endpoints
-------------------
- ``POST /v1/chat/completions`` — OpenAI ChatCompletions format
- ``GET  /v1/models``           — Returns the configured model as a list entry

Non-streaming only (v1).  Streaming is out of scope.
"""

from __future__ import annotations

import http.server
import json
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oh_no_my_claudecode.llm.base import BaseLLMProvider

from oh_no_my_claudecode.models.llm import LLMGenerationRequest, LLMGenerationResponse

# ---------------------------------------------------------------------------
# Pure mappers — no I/O, fully testable without a socket
# ---------------------------------------------------------------------------

_OPENAI_OBJECT_CHAT_COMPLETION = "chat.completion"
_OPENAI_OBJECT_MODEL = "model"
_OPENAI_OBJECT_LIST = "list"
_FINISH_REASON_STOP = "stop"
_DEFAULT_MODEL_ID = "onmc-proxy"


def to_provider_request(openai_body: dict[str, Any]) -> LLMGenerationRequest:
    """Map an OpenAI ChatCompletions request body to an :class:`LLMGenerationRequest`.

    The OpenAI messages array is collapsed into a single ``prompt`` string.
    System messages are concatenated and passed as ``system_prompt``.  All other
    message roles (``user``, ``assistant``, ``tool``, etc.) are concatenated in
    order as the user turn.

    Parameters
    ----------
    openai_body:
        Parsed JSON dict from a ``POST /v1/chat/completions`` request.

    Returns
    -------
    LLMGenerationRequest
        Ready for ``provider.generate()``.
    """
    messages: list[dict[str, Any]] = openai_body.get("messages", [])
    system_parts: list[str] = []
    user_parts: list[str] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""
        if isinstance(content, list):
            # Content blocks (vision / tool-use payloads) — extract text only.
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        content = str(content)
        if role == "system":
            system_parts.append(content)
        else:
            prefix = f"{role}: " if role and role != "user" else ""
            user_parts.append(f"{prefix}{content}")

    system_prompt = "\n\n".join(system_parts) if system_parts else None
    prompt = "\n\n".join(user_parts) if user_parts else ""

    temperature: float | None = None
    raw_temp = openai_body.get("temperature")
    if raw_temp is not None:
        try:
            temperature = float(raw_temp)
        except (ValueError, TypeError):
            temperature = None

    max_tokens: int | None = None
    for key in ("max_tokens", "max_completion_tokens"):
        raw_mt = openai_body.get(key)
        if raw_mt is not None:
            try:
                max_tokens = int(raw_mt)
                break
            except (ValueError, TypeError):
                pass

    return LLMGenerationRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def to_openai_response(
    provider_result: LLMGenerationResponse,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Map an :class:`LLMGenerationResponse` to an OpenAI ChatCompletions response dict.

    The ``id`` field is stable within a call (``request_id`` or a fresh UUID4).
    Usage counts are estimated conservatively (1 token ≈ 4 chars) since the
    provider layer does not expose precise token counts.

    Parameters
    ----------
    provider_result:
        The response object from ``provider.generate()``.
    request_id:
        Optional stable request identifier; defaults to a fresh ``chatcmpl-*`` id.

    Returns
    -------
    dict
        OpenAI-shaped ``chat.completion`` object.
    """
    rid = request_id or f"chatcmpl-{uuid.uuid4().hex}"
    text = provider_result.text
    model_id = provider_result.model or _DEFAULT_MODEL_ID

    # Rough token estimation: 1 token ≈ 4 characters (good enough for headers).
    completion_tokens = max(1, len(text) // 4)

    return {
        "id": rid,
        "object": _OPENAI_OBJECT_CHAT_COMPLETION,
        "created": int(time.time()),
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": text,
                },
                "finish_reason": _FINISH_REASON_STOP,
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens,
        },
    }


def to_openai_error(
    message: str,
    *,
    status_code: int = 500,
    error_type: str = "proxy_error",
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build an OpenAI-shaped error response body.

    Parameters
    ----------
    message:
        Human-readable error description.
    status_code:
        HTTP status to accompany this body (informational — the dict itself
        does not carry the status).
    error_type:
        OpenAI ``error.type`` string (e.g. ``"invalid_request_error"``).
    request_id:
        Optional stable request identifier included in the body.
    """
    rid = request_id or f"chatcmpl-{uuid.uuid4().hex}"
    return {
        "id": rid,
        "object": "error",
        "error": {
            "message": message,
            "type": error_type,
            "code": status_code,
        },
    }


def to_openai_models_response(model_id: str) -> dict[str, Any]:
    """Build a ``GET /v1/models`` response listing *model_id* as a single entry.

    Parameters
    ----------
    model_id:
        The model string to advertise (e.g. ``"claude-sonnet-4-5"``).

    Returns
    -------
    dict
        OpenAI-shaped model list response.
    """
    return {
        "object": _OPENAI_OBJECT_LIST,
        "data": [
            {
                "id": model_id,
                "object": _OPENAI_OBJECT_MODEL,
                "created": 0,
                "owned_by": "onmc-proxy",
            }
        ],
    }


# ---------------------------------------------------------------------------
# HTTP handler factory
# ---------------------------------------------------------------------------

def make_handler(provider: BaseLLMProvider) -> type[http.server.BaseHTTPRequestHandler]:
    """Return a ``BaseHTTPRequestHandler`` subclass wired to *provider*.

    The handler is a closure over the provider instance.  Create a new class
    per server instance (or per test) — do not share across server lifetimes.

    Parameters
    ----------
    provider:
        Any :class:`~oh_no_my_claudecode.llm.base.BaseLLMProvider` instance.

    Returns
    -------
    type[BaseHTTPRequestHandler]
        Ready for ``http.server.HTTPServer(addr, handler_class)``.
    """
    from oh_no_my_claudecode.llm.base import LLMError

    class _ProxyHandler(http.server.BaseHTTPRequestHandler):
        """Minimal OpenAI-compatible proxy handler."""

        # Silence the default request logging to avoid noise in tests/CI.
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
            pass

        # ------------------------------------------------------------------
        # Routing
        # ------------------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/models":
                self._handle_models()
            else:
                self._send_json(
                    404,
                    to_openai_error(
                        f"Unknown endpoint: {self.path}",
                        status_code=404,
                        error_type="not_found",
                    ),
                )

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/v1/chat/completions":
                self._handle_chat_completions()
            else:
                self._send_json(
                    404,
                    to_openai_error(
                        f"Unknown endpoint: {self.path}",
                        status_code=404,
                        error_type="not_found",
                    ),
                )

        # ------------------------------------------------------------------
        # Endpoint handlers
        # ------------------------------------------------------------------

        def _handle_models(self) -> None:
            model_id = provider.settings.model or _DEFAULT_MODEL_ID
            self._send_json(200, to_openai_models_response(model_id))

        def _handle_chat_completions(self) -> None:
            # Read body.
            length_str = self.headers.get("Content-Length", "0")
            try:
                length = int(length_str)
            except ValueError:
                length = 0
            raw_body = self.rfile.read(length) if length > 0 else b""

            # Parse JSON body.
            try:
                body: dict[str, Any] = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_json(
                    400,
                    to_openai_error(
                        f"Request body is not valid JSON: {exc}",
                        status_code=400,
                        error_type="invalid_request_error",
                    ),
                )
                return

            if not isinstance(body, dict):
                self._send_json(
                    400,
                    to_openai_error(
                        "Request body must be a JSON object.",
                        status_code=400,
                        error_type="invalid_request_error",
                    ),
                )
                return

            # Map → provider → map back.
            try:
                gen_request = to_provider_request(body)
                gen_response = provider.generate(gen_request)
            except LLMError as exc:
                self._send_json(
                    502,
                    to_openai_error(
                        str(exc),
                        status_code=502,
                        error_type="provider_error",
                    ),
                )
                return
            except Exception as exc:  # noqa: BLE001 - unexpected errors must not crash server
                self._send_json(
                    500,
                    to_openai_error(
                        f"Internal proxy error: {exc}",
                        status_code=500,
                    ),
                )
                return

            self._send_json(200, to_openai_response(gen_response))

        # ------------------------------------------------------------------
        # Helper
        # ------------------------------------------------------------------

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _ProxyHandler


# ---------------------------------------------------------------------------
# ProxyServer — lifecycle wrapper
# ---------------------------------------------------------------------------

class ProxyServer:
    """Thin lifecycle wrapper around ``http.server.HTTPServer``.

    Intended for use as a context manager::

        with ProxyServer(provider, host="127.0.0.1", port=8760) as srv:
            print(f"Listening on {srv.host}:{srv.port}")
            srv.serve_forever()

    Or manually::

        srv = ProxyServer(provider)
        srv.start()
        try:
            srv.serve_forever()
        finally:
            srv.stop()

    Parameters
    ----------
    provider:
        Any :class:`~oh_no_my_claudecode.llm.base.BaseLLMProvider` instance.
    host:
        Bind address (default ``127.0.0.1``).
    port:
        Bind port.  Pass ``0`` to let the OS pick an ephemeral port; read back
        the actual port via :attr:`port` after :meth:`start`.
    """

    def __init__(
        self,
        provider: BaseLLMProvider,
        *,
        host: str = "127.0.0.1",
        port: int = 8760,
    ) -> None:
        self._provider = provider
        self.host = host
        self._requested_port = port
        self._server: http.server.HTTPServer | None = None

    @property
    def port(self) -> int:
        """The actual bound port (useful when ``port=0`` was requested)."""
        if self._server is not None:
            return self._server.server_address[1]
        return self._requested_port

    def start(self) -> None:
        """Bind the socket and prepare to serve (does not block)."""
        handler = make_handler(self._provider)
        self._server = http.server.HTTPServer((self.host, self._requested_port), handler)

    def serve_forever(self) -> None:
        """Block and serve until :meth:`stop` is called from another thread."""
        if self._server is None:
            self.start()
        if self._server is None:  # pragma: no cover — start() always sets it
            msg = "Server failed to start."
            raise RuntimeError(msg)
        self._server.serve_forever()

    def stop(self) -> None:
        """Shut down the server and release the socket."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def handle_one_request(self) -> None:
        """Process exactly one request (useful for ephemeral-port tests)."""
        if self._server is None:
            self.start()
        if self._server is None:  # pragma: no cover — start() always sets it
            msg = "Server failed to start."
            raise RuntimeError(msg)
        self._server.handle_request()

    def __enter__(self) -> ProxyServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
