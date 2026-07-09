"""Outbound sinks for the ``connect`` ecosystem adapter.

These compose the notification :class:`~oh_no_my_claudecode.notify.sinks.Sink`
ABC (imported, never edited) with two new destinations:

- :class:`TelegramSink` — POSTs a Telegram Bot API ``sendMessage`` payload.
- :class:`OpenClawSink` — POSTs an onmc reply to an OpenClaw outbound endpoint.

Both follow the same discipline as the built-in webhook sinks: stdlib ``urllib``
only, a short timeout, a no-op when unconfigured, and *never* raising into the
caller.  The network call goes through an injectable ``transport`` so tests
exercise payload formatting against a fake and never hit the network.  Payload
construction is split into a pure :meth:`format` (returns the JSON body) plus a
:attr:`endpoint` property, so the CLI can preview exactly what *would* be sent
without any I/O.
"""

from __future__ import annotations

import contextlib
import json
import urllib.request
from collections.abc import Callable
from typing import ClassVar

from oh_no_my_claudecode.notify.events import NotifyEvent
from oh_no_my_claudecode.notify.sinks import Sink

__all__ = ["OpenClawSink", "TelegramSink", "Transport"]

#: An injectable transport: ``(url, json_bytes) -> None``.  The default hits the
#: network via stdlib ``urllib``; tests pass a fake that records the call.
Transport = Callable[[str, bytes], None]

_WEBHOOK_TIMEOUT_S = 5  # seconds — short; never blocks the agent


def _urllib_transport(url: str, data: bytes) -> None:
    """Default transport: a stdlib ``urllib`` POST with a JSON content type."""
    req = urllib.request.Request(  # noqa: S310 - url is operator-supplied, http(s) only
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as _resp:  # noqa: S310
        pass


def _event_text(event: NotifyEvent, *, limit: int) -> str:
    """Render an event to a single ``[onmc/SEV] title`` (+ detail) string."""
    severity = str(event.severity).upper()
    text = f"[onmc/{severity}] {event.title}"
    if event.detail:
        text += f"\n{event.detail}"
    return text[:limit]


class TelegramSink(Sink):
    """POST events to the Telegram Bot API ``sendMessage`` endpoint.

    No-op when *bot_token* or *chat_id* is empty.  All transport errors are
    swallowed — the sink never raises into the caller.
    """

    API_BASE: ClassVar[str] = "https://api.telegram.org"
    _TEXT_LIMIT: ClassVar[int] = 4096  # Telegram's per-message character cap

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        *,
        api_base: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._token = bot_token or ""
        self._chat_id = chat_id or ""
        self._api_base = (api_base or self.API_BASE).rstrip("/")
        self._transport = transport or _urllib_transport

    @property
    def endpoint(self) -> str:
        """The Bot API ``sendMessage`` URL for the configured token."""
        return f"{self._api_base}/bot{self._token}/sendMessage"

    def format(self, event: NotifyEvent) -> dict[str, str]:
        """Return the ``sendMessage`` JSON body for *event* (pure, no I/O)."""
        return {"chat_id": self._chat_id, "text": _event_text(event, limit=self._TEXT_LIMIT)}

    def emit(self, event: NotifyEvent) -> None:
        """Send *event* to Telegram.  No-op when unconfigured.  Exception-safe."""
        if not self._token or not self._chat_id:
            return
        # Transport errors must never raise into the caller.
        with contextlib.suppress(Exception):
            self._transport(self.endpoint, json.dumps(self.format(event)).encode("utf-8"))


class OpenClawSink(Sink):
    """POST an onmc reply to an OpenClaw outbound endpoint.

    OpenClaw fans the reply back out to whatever chat platform the message came
    from.  No-op when *endpoint_url* is empty; all transport errors are swallowed.
    """

    _TEXT_LIMIT: ClassVar[int] = 4000

    def __init__(
        self,
        endpoint_url: str,
        *,
        channel: str | None = None,
        transport: Transport | None = None,
    ) -> None:
        self._url = endpoint_url or ""
        self._channel = channel
        self._transport = transport or _urllib_transport

    @property
    def endpoint(self) -> str:
        """The OpenClaw outbound endpoint URL."""
        return self._url

    def format(self, event: NotifyEvent) -> dict[str, str]:
        """Return the OpenClaw outbound JSON body for *event* (pure, no I/O)."""
        payload = {"text": _event_text(event, limit=self._TEXT_LIMIT)}
        if self._channel is not None:
            payload["channel"] = self._channel
        return payload

    def emit(self, event: NotifyEvent) -> None:
        """Send *event* to OpenClaw.  No-op without a URL.  Exception-safe."""
        if not self._url:
            return
        # Transport errors must never raise into the caller.
        with contextlib.suppress(Exception):
            self._transport(self._url, json.dumps(self.format(event)).encode("utf-8"))
