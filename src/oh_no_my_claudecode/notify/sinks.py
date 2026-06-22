"""Sink implementations for the context firewall notification subsystem.

All network sinks:
- require an explicit webhook URL to be configured (no-op without one).
- have a short timeout and swallow ALL errors (never raise).
- use stdlib ``urllib`` only — no third-party HTTP dependency.

``FileSink`` is the default: it appends JSONL to ``.onmc/notify.log`` and
never performs any network I/O.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from oh_no_my_claudecode.notify.events import NotifyEvent


class Sink(ABC):
    """Abstract base for notification sinks."""

    @abstractmethod
    def emit(self, event: NotifyEvent) -> None:
        """Emit *event* to the sink.

        Implementations MUST be exception-safe — they must never raise.
        """


class FileSink(Sink):
    """Append JSONL records to ``.onmc/notify.log`` under the repo root.

    This is the DEFAULT sink.  It is always safe to use — no network, no
    external configuration required.  The file is created on first write.
    """

    LOG_FILENAME: ClassVar[str] = "notify.log"

    def __init__(self, repo_root: Path) -> None:
        self._log_path = repo_root / ".onmc" / self.LOG_FILENAME

    @property
    def log_path(self) -> Path:
        """Absolute path to the JSONL log file."""
        return self._log_path

    def emit(self, event: NotifyEvent) -> None:
        """Append a JSONL line for *event*.  Exception-safe."""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": event.ts,
                "kind": str(event.kind),
                "severity": str(event.severity),
                "title": event.title,
                "detail": event.detail,
            }
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:  # noqa: BLE001, S110
            pass  # file sink must never raise


_WEBHOOK_TIMEOUT_S: int = 5  # seconds — short; never blocks the agent


class DiscordSink(Sink):
    """POST events to a Discord webhook URL.

    No-op when *webhook_url* is ``None`` or empty.  All network errors are
    swallowed.  Uses ``urllib`` (stdlib) — no third-party dependency.
    """

    def __init__(self, webhook_url: str | None) -> None:
        self._url = webhook_url or ""

    def emit(self, event: NotifyEvent) -> None:
        """Send *event* to Discord.  No-op without a URL.  Exception-safe."""
        if not self._url:
            return
        try:
            severity_label = str(event.severity).upper()
            content = f"**[onmc/{severity_label}]** {event.title}"
            if event.detail:
                content += f"\n{event.detail}"
            payload = json.dumps({"content": content[:2000]}).encode()
            req = urllib.request.Request(  # noqa: S310
                self._url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as _resp:  # noqa: S310
                pass
        except Exception:  # noqa: BLE001, S110
            pass  # network errors must never raise


class SlackSink(Sink):
    """POST events to a Slack incoming webhook URL.

    No-op when *webhook_url* is ``None`` or empty.  All network errors are
    swallowed.  Uses ``urllib`` (stdlib) — no third-party dependency.
    """

    def __init__(self, webhook_url: str | None) -> None:
        self._url = webhook_url or ""

    def emit(self, event: NotifyEvent) -> None:
        """Send *event* to Slack.  No-op without a URL.  Exception-safe."""
        if not self._url:
            return
        try:
            severity_label = str(event.severity).upper()
            text = f"*[onmc/{severity_label}]* {event.title}"
            if event.detail:
                text += f"\n{event.detail}"
            payload = json.dumps({"text": text[:3000]}).encode()
            req = urllib.request.Request(  # noqa: S310
                self._url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT_S) as _resp:  # noqa: S310
                pass
        except Exception:  # noqa: BLE001, S110
            pass  # network errors must never raise
