"""Tests for the ``connect`` bidirectional ecosystem adapter.

Fully offline and deterministic (no socket, no network, no Rich ``--help``
scraping):

- :mod:`oh_no_my_claudecode.connect.openclaw` — envelope parsing, reply shaping
  (action-id mirroring), and the ``handle_openclaw`` glue with the dry + an
  injected dispatcher.
- :mod:`oh_no_my_claudecode.connect.hermes` — the continuous mirror: dry vs
  apply, idempotent re-run, and a missing source.
- :mod:`oh_no_my_claudecode.connect.sinks` — Telegram / OpenClaw payload shaping
  through an injected fake transport, plus transport-error swallowing.
- the ``onmc connect`` CLI via ``CliRunner`` (exit codes + JSON only).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.connect.hermes import HermesSyncResult, sync_hermes
from oh_no_my_claudecode.connect.openclaw import (
    OpenClawInbound,
    handle_openclaw,
    parse_openclaw_event,
    to_openclaw_reply,
)
from oh_no_my_claudecode.connect.sinks import OpenClawSink, TelegramSink
from oh_no_my_claudecode.gateway.pipeline import (
    STATUS_ACCEPTED,
    STATUS_DENIED,
    STATUS_IGNORED,
    InboundResult,
)
from oh_no_my_claudecode.missionbridge.auth import add_identity
from oh_no_my_claudecode.missionbridge.card import ACTION_ABORT, ACTION_APPROVE_ALL
from oh_no_my_claudecode.missionbridge.models import IntakeTask
from oh_no_my_claudecode.models import MemoryEntry
from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:  # older click without mix_stderr
        return CliRunner()


def _git_repo(tmp_path: Path) -> Path:
    """Init a git repo so ``discover_repo_root`` resolves the CLI's cwd."""
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path.resolve()


class _FakeStore:
    """A tiny in-memory :class:`~oh_no_my_claudecode.connect.hermes.MemoryStore`."""

    def __init__(self) -> None:
        self.upserted: list[MemoryEntry] = []

    def upsert_memories(self, entries: list[MemoryEntry]) -> tuple[int, int]:
        self.upserted.extend(entries)
        return len(entries), 0


class _RecordingTransport:
    """A fake sink transport that records ``(url, decoded-json)`` calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, data: bytes) -> None:
        self.calls.append((url, json.loads(data.decode("utf-8"))))


def _memory_md(tmp_path: Path, body: str) -> Path:
    src = tmp_path / "MEMORY.md"
    src.write_text(body, encoding="utf-8")
    return src


_SAMPLE_MEMORY = """## Decision: use Hono
We picked Hono for the backend.

## Gotcha: emulator data
Never commit emulator-data/.
"""


# ---------------------------------------------------------------------------
# openclaw.parse_openclaw_event
# ---------------------------------------------------------------------------


def test_parse_openclaw_happy_path() -> None:
    inbound = parse_openclaw_event(
        {"channel": "slack", "user": "U1", "text": "@onmc ship it", "mention": "@bot"}
    )
    assert inbound == OpenClawInbound(
        channel="slack", user_id="U1", text="@onmc ship it", mention="@bot"
    )


def test_parse_openclaw_normalizes_platform_aliases() -> None:
    inbound = parse_openclaw_event(
        {"platform": "telegram", "sender_id": "42", "message": "@onmc build the dashboard"}
    )
    assert inbound is not None
    assert inbound.channel == "telegram"
    assert inbound.user_id == "42"
    assert inbound.text == "@onmc build the dashboard"
    assert inbound.mention == "@onmc"  # default


def test_parse_openclaw_non_message_type_is_none() -> None:
    assert parse_openclaw_event({"type": "typing", "channel": "slack", "user": "U1"}) is None


def test_parse_openclaw_missing_fields_is_none() -> None:
    assert parse_openclaw_event({"channel": "slack"}) is None  # no user / text
    assert parse_openclaw_event({"channel": "slack", "user": "U1", "text": "   "}) is None


def test_parse_openclaw_non_dict_is_none() -> None:
    assert parse_openclaw_event([]) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# openclaw.to_openclaw_reply
# ---------------------------------------------------------------------------


def test_reply_accepted_mirrors_mission_action_ids() -> None:
    result = InboundResult(status=STATUS_ACCEPTED, task=IntakeTask(goal="add OAuth", concurrency=3))
    reply = to_openclaw_reply(result, channel="slack")
    assert reply["channel"] == "slack"
    assert reply["status"] == STATUS_ACCEPTED
    action_ids = [b["action_id"] for b in reply["buttons"]]
    assert action_ids == [ACTION_APPROVE_ALL, ACTION_ABORT]
    assert "add OAuth" in reply["text"]


def test_reply_denied_has_no_buttons() -> None:
    result = InboundResult(status=STATUS_DENIED, reason="not on the mission allowlist")
    reply = to_openclaw_reply(result)
    assert "buttons" not in reply
    assert "channel" not in reply  # not provided
    assert "Denied" in reply["text"]


def test_reply_appends_card_text() -> None:
    result = InboundResult(status=STATUS_ACCEPTED, task=IntakeTask(goal="x"))
    reply = to_openclaw_reply(result, card_text="Mission sw_1 — 2/2 verified")
    assert "Mission sw_1" in reply["text"]


# ---------------------------------------------------------------------------
# openclaw.handle_openclaw
# ---------------------------------------------------------------------------


def test_handle_openclaw_dry_accepts_without_spawning(tmp_path: Path) -> None:
    add_identity(tmp_path, "slack:U1")
    reply = handle_openclaw(
        tmp_path, {"channel": "slack", "user": "U1", "text": "@onmc ship the docs"}
    )
    assert reply["status"] == STATUS_ACCEPTED
    assert reply["dispatch"] == {"dispatched": False, "note": "dry"}


def test_handle_openclaw_injected_dispatcher(tmp_path: Path) -> None:
    add_identity(tmp_path, "slack:U1")
    seen: list[str] = []

    def spy(repo_root: Path, task: IntakeTask) -> dict[str, object]:  # noqa: ARG001
        seen.append(task.goal)
        return {"dispatched": True, "swarm_id": "sw_test"}

    reply = handle_openclaw(
        tmp_path,
        {"channel": "slack", "user": "U1", "text": "@onmc fix flaky test"},
        dispatcher=spy,
    )
    assert seen == ["fix flaky test"]
    assert reply["dispatch"] == {"dispatched": True, "swarm_id": "sw_test"}


def test_handle_openclaw_denied_has_no_dispatch(tmp_path: Path) -> None:
    reply = handle_openclaw(tmp_path, {"channel": "slack", "user": "nope", "text": "@onmc go"})
    assert reply["status"] == STATUS_DENIED
    assert "dispatch" not in reply


def test_handle_openclaw_non_actionable_is_ignored(tmp_path: Path) -> None:
    reply = handle_openclaw(tmp_path, {"type": "presence", "channel": "slack"})
    assert reply["status"] == STATUS_IGNORED
    assert reply["reason"] == "not-a-message"


# ---------------------------------------------------------------------------
# hermes.sync_hermes
# ---------------------------------------------------------------------------


def test_sync_hermes_dry_reports_delta_without_writing(tmp_path: Path) -> None:
    src = _memory_md(tmp_path, _SAMPLE_MEMORY)
    store = _FakeStore()
    result = sync_hermes(tmp_path, src, dry_run=True, storage=store)
    assert isinstance(result, HermesSyncResult)
    assert result.total == 2
    assert result.imported == 2
    assert result.skipped == 0
    assert result.dry_run is True
    assert store.upserted == []  # nothing written on a dry run
    assert not (tmp_path / ".onmc" / "connect" / "hermes-state.json").exists()


def test_sync_hermes_apply_writes_and_is_idempotent(tmp_path: Path) -> None:
    src = _memory_md(tmp_path, _SAMPLE_MEMORY)
    store = _FakeStore()

    first = sync_hermes(tmp_path, src, dry_run=False, storage=store, now_ms=1000)
    assert first.imported == 2
    assert first.skipped == 0
    assert len(store.upserted) == 2
    state_file = tmp_path / ".onmc" / "connect" / "hermes-state.json"
    assert state_file.exists()

    # Re-run with no source change → nothing new imported (idempotent).
    second = sync_hermes(tmp_path, src, dry_run=False, storage=store, now_ms=2000)
    assert second.imported == 0
    assert second.skipped == 2
    assert second.total == 2
    assert len(store.upserted) == 2  # unchanged — no second write


def test_sync_hermes_detects_changed_entry(tmp_path: Path) -> None:
    src = _memory_md(tmp_path, _SAMPLE_MEMORY)
    store = _FakeStore()
    sync_hermes(tmp_path, src, dry_run=False, storage=store, now_ms=1000)

    # Change one section's body; its id stays the same but its hash changes.
    changed = _SAMPLE_MEMORY.replace("We picked Hono", "We picked Hono v4")
    src.write_text(changed, encoding="utf-8")
    result = sync_hermes(tmp_path, src, dry_run=False, storage=store, now_ms=2000)
    assert result.imported == 1
    assert result.skipped == 1


def test_sync_hermes_missing_source_is_empty(tmp_path: Path) -> None:
    result = sync_hermes(tmp_path, tmp_path / "nope", dry_run=False, storage=_FakeStore())
    assert result == HermesSyncResult(imported=0, skipped=0, total=0, dry_run=False)


# ---------------------------------------------------------------------------
# sinks
# ---------------------------------------------------------------------------


# A dummy bot token as a variable (avoids ruff S106 literal-secret detection).
_BOT = "TOK"


def _event() -> NotifyEvent:
    return NotifyEvent(
        kind=EventKind.GENERIC,
        title="hello",
        severity=EventSeverity.ROUTINE,
        detail="world",
    )


def test_telegram_sink_formats_send_message_payload() -> None:
    transport = _RecordingTransport()
    sink = TelegramSink(bot_token=_BOT, chat_id="C1", transport=transport)
    sink.emit(_event())
    assert len(transport.calls) == 1
    url, payload = transport.calls[0]
    assert url == "https://api.telegram.org/botTOK/sendMessage"
    assert payload == {"chat_id": "C1", "text": "[onmc/ROUTINE] hello\nworld"}


def test_telegram_sink_noop_without_config() -> None:
    transport = _RecordingTransport()
    TelegramSink(bot_token="", chat_id="C1", transport=transport).emit(_event())
    TelegramSink(bot_token=_BOT, chat_id="", transport=transport).emit(_event())
    assert transport.calls == []


def test_openclaw_sink_formats_payload_with_channel() -> None:
    transport = _RecordingTransport()
    sink = OpenClawSink("https://openclaw.example/reply", channel="slack", transport=transport)
    sink.emit(_event())
    url, payload = transport.calls[0]
    assert url == "https://openclaw.example/reply"
    assert payload == {"text": "[onmc/ROUTINE] hello\nworld", "channel": "slack"}


def test_openclaw_sink_noop_without_url() -> None:
    transport = _RecordingTransport()
    OpenClawSink("", transport=transport).emit(_event())
    assert transport.calls == []


def test_sinks_swallow_transport_errors() -> None:
    def boom(url: str, data: bytes) -> None:  # noqa: ARG001
        raise RuntimeError("network down")

    # Neither call may raise.
    TelegramSink(bot_token=_BOT, chat_id="C1", transport=boom).emit(_event())
    OpenClawSink("https://x", transport=boom).emit(_event())


# ---------------------------------------------------------------------------
# CLI — CliRunner (JSON + exit codes only)
# ---------------------------------------------------------------------------


def test_cli_openclaw_routes_event(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    add_identity(root, "slack:U1")
    event_file = root / "event.json"
    event_file.write_text(
        json.dumps({"channel": "slack", "user": "U1", "text": "@onmc build the dashboard"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(root)
    result = _cli_runner().invoke(app, ["connect", "openclaw", "--file", str(event_file)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == STATUS_ACCEPTED
    assert payload["dispatch"] == {"dispatched": False, "note": "dry"}


def test_cli_hermes_dry(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    src = _memory_md(root, _SAMPLE_MEMORY)
    monkeypatch.chdir(root)
    result = _cli_runner().invoke(app, ["connect", "hermes", "--from", str(src)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"imported": 2, "skipped": 0, "total": 2, "dry_run": True}


def test_cli_test_sink_dry_preview(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    monkeypatch.chdir(root)
    runner = _cli_runner()

    tg = runner.invoke(app, ["connect", "test-sink", "telegram", "--message", "ping"])
    assert tg.exit_code == 0
    tg_payload = json.loads(tg.stdout)
    assert tg_payload["sent"] is False
    assert tg_payload["endpoint"].endswith("/sendMessage")
    assert tg_payload["payload"]["text"] == "[onmc/ROUTINE] ping"

    oc = runner.invoke(app, ["connect", "test-sink", "openclaw"])
    assert oc.exit_code == 0
    assert json.loads(oc.stdout)["sent"] is False


def test_cli_test_sink_rejects_unknown_kind(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    root = _git_repo(tmp_path)
    monkeypatch.chdir(root)
    result = _cli_runner().invoke(app, ["connect", "test-sink", "carrier-pigeon"])
    assert result.exit_code == 1
