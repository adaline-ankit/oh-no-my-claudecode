"""HTTP surface for the accountable agent gateway.

A tiny stdlib ``http.server`` app — structured like
:mod:`oh_no_my_claudecode.proxy.server`: all routing logic lives in the pure
:func:`route` function (no socket, no clock) so it can be tested directly, and
:func:`make_handler` wires that same function into a
``BaseHTTPRequestHandler`` subclass for real serving.

Endpoints
---------
- ``GET  /health``  → ``{"ok": true, "version": ...}``
- ``POST /webhook`` → JSON body ``{"channel", "user_id", "text", "mention"?}``;
  runs :func:`~oh_no_my_claudecode.gateway.pipeline.handle_inbound` and returns
  the decision.  When the decision is ``accepted``, an injectable *dispatcher*
  is invoked to (eventually) spawn the mission; the default is a **dry**
  dispatcher that spawns nothing — live swarm dispatch is a documented
  follow-up, never a side effect of importing or serving this module.
"""

from __future__ import annotations

import dataclasses
import http.server
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oh_no_my_claudecode import __version__
from oh_no_my_claudecode.gateway.pipeline import STATUS_ACCEPTED, InboundResult, handle_inbound
from oh_no_my_claudecode.missionbridge.models import IntakeTask

__all__ = ["Dispatcher", "dry_dispatcher", "route", "make_handler", "GatewayServer"]

#: A dispatcher turns an accepted :class:`IntakeTask` into a live mission run.
#: It returns a small JSON-safe dict describing what it did.
Dispatcher = Callable[[Path, IntakeTask], dict[str, Any]]


def dry_dispatcher(repo_root: Path, task: IntakeTask) -> dict[str, Any]:  # noqa: ARG001
    """The safe default dispatcher — spawns nothing.

    Live swarm dispatch (wiring an accepted goal into ``onmc swarm``) is an
    intentional follow-up so that merely serving the gateway can never spend
    money or launch agents.  Injecting a real dispatcher is the seam that turns
    this daemon live.
    """
    return {"dispatched": False, "note": "dry"}


def _result_to_dict(result: InboundResult) -> dict[str, Any]:
    """Serialize an :class:`InboundResult` to a JSON-safe dict."""
    payload: dict[str, Any] = {"status": result.status}
    if result.reason is not None:
        payload["reason"] = result.reason
    if result.task is not None:
        payload["task"] = dataclasses.asdict(result.task)
    if result.action is not None:
        payload["action"] = {
            "kind": str(result.action.kind),
            "unit_id": result.action.unit_id,
            "raw": result.action.raw,
        }
    return payload


def route(
    method: str,
    path: str,
    body: str | bytes | None,
    *,
    repo_root: Path | str,
    dispatcher: Dispatcher | None = None,
) -> tuple[int, dict[str, Any]]:
    """Resolve one request to ``(status_code, json_body)`` — pure, socket-free.

    Parameters
    ----------
    method:
        HTTP method (``"GET"`` / ``"POST"``).
    path:
        Request path (query string, if any, is ignored).
    body:
        Raw request body for ``POST`` (str/bytes), or ``None``.
    repo_root:
        Repository root whose allowlist gates ``/webhook``.
    dispatcher:
        Callable invoked for an ``accepted`` mission; defaults to
        :func:`dry_dispatcher` (spawns nothing).
    """
    dispatch = dispatcher or dry_dispatcher
    root = Path(repo_root)
    clean_path = path.split("?", 1)[0]

    if method == "GET" and clean_path == "/health":
        return 200, {"ok": True, "version": __version__}

    if method == "POST" and clean_path == "/webhook":
        return _handle_webhook(body, root, dispatch)

    return 404, {"error": f"unknown endpoint: {method} {clean_path}"}


def _handle_webhook(
    body: str | bytes | None,
    repo_root: Path,
    dispatch: Dispatcher,
) -> tuple[int, dict[str, Any]]:
    """Parse a ``/webhook`` body and route it through :func:`handle_inbound`."""
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8")
        except UnicodeDecodeError:
            return 400, {"error": "request body is not valid UTF-8"}

    try:
        parsed: Any = json.loads(body) if body else {}
    except (ValueError, TypeError):
        return 400, {"error": "request body is not valid JSON"}

    if not isinstance(parsed, dict):
        return 400, {"error": "request body must be a JSON object"}

    channel = parsed.get("channel")
    user_id = parsed.get("user_id")
    text = parsed.get("text")
    if not isinstance(channel, str) or not isinstance(user_id, str) or not isinstance(text, str):
        return 400, {"error": "channel, user_id and text are required strings"}

    mention = parsed.get("mention")
    mention = mention if isinstance(mention, str) and mention else "@onmc"

    result = handle_inbound(
        repo_root,
        channel=channel,
        user_id=user_id,
        text=text,
        mention=mention,
    )
    payload = _result_to_dict(result)
    if result.status == STATUS_ACCEPTED and result.task is not None:
        payload["dispatch"] = dispatch(repo_root, result.task)
    return 200, payload


def make_handler(
    repo_root: Path | str,
    dispatcher: Dispatcher | None = None,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Return a ``BaseHTTPRequestHandler`` subclass wired to :func:`route`.

    The handler is a thin transport shell: it reads the body and delegates every
    decision to :func:`route`, so the HTTP layer holds no business logic.  Build
    one class per server instance (it closes over *repo_root* / *dispatcher*).
    """
    root = Path(repo_root)
    dispatch = dispatcher or dry_dispatcher

    class _GatewayHandler(http.server.BaseHTTPRequestHandler):
        """Minimal gateway handler delegating to :func:`route`."""

        # Silence default request logging to keep tests/CI quiet.
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: ARG002
            pass

        def do_GET(self) -> None:  # noqa: N802
            status, payload = route("GET", self.path, None, repo_root=root, dispatcher=dispatch)
            self._send_json(status, payload)

        def do_POST(self) -> None:  # noqa: N802
            length_str = self.headers.get("Content-Length", "0")
            try:
                length = int(length_str)
            except ValueError:
                length = 0
            raw = self.rfile.read(length) if length > 0 else b""
            status, payload = route("POST", self.path, raw, repo_root=root, dispatcher=dispatch)
            self._send_json(status, payload)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return _GatewayHandler


class GatewayServer:
    """Thin lifecycle wrapper around ``http.server.HTTPServer``.

    Mirrors :class:`oh_no_my_claudecode.proxy.server.ProxyServer`: bind with
    :meth:`start`, block with :meth:`serve_forever`, release with :meth:`stop`.
    Pass ``port=0`` to let the OS pick an ephemeral port and read it back via
    :attr:`port`.
    """

    def __init__(
        self,
        repo_root: Path | str,
        *,
        host: str = "127.0.0.1",
        port: int = 8770,
        dispatcher: Dispatcher | None = None,
    ) -> None:
        self._repo_root = Path(repo_root)
        self.host = host
        self._requested_port = port
        self._dispatcher = dispatcher or dry_dispatcher
        self._server: http.server.HTTPServer | None = None
        self._serving = False

    @property
    def port(self) -> int:
        """The actual bound port (useful when ``port=0`` was requested)."""
        if self._server is not None:
            return self._server.server_address[1]
        return self._requested_port

    def start(self) -> None:
        """Bind the socket and prepare to serve (does not block)."""
        handler = make_handler(self._repo_root, self._dispatcher)
        self._server = http.server.HTTPServer((self.host, self._requested_port), handler)

    def serve_forever(self) -> None:
        """Block and serve until :meth:`stop` is called from another thread."""
        if self._server is None:
            self.start()
        assert self._server is not None  # noqa: S101 - start() always sets it
        self._serving = True
        try:
            self._server.serve_forever()
        finally:
            self._serving = False

    def stop(self) -> None:
        """Shut down the server and release the socket."""
        if self._server is not None:
            if self._serving:
                self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> GatewayServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()
