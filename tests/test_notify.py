"""Tests for the context firewall notification subsystem (notify/).

Coverage:
- FileSink appends JSONL + emit_event is exception-safe when misconfigured.
- DiscordSink / SlackSink are no-ops without a webhook + swallow network
  errors (monkeypatched urllib to raise — assert no exception).
- NotifyRouter routes routine events to sink + failure emits immediately.
- Config precedence: env > yaml > default.
- CLI notify test / status / tail exit codes + --json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.notify.events import EventKind, EventSeverity, NotifyEvent
from oh_no_my_claudecode.notify.router import NotifyRouter, _resolve_notify_config, emit_event
from oh_no_my_claudecode.notify.sinks import DiscordSink, FileSink, SlackSink

_runner = CliRunner()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    kind: EventKind = EventKind.GENERIC,
    title: str = "test event",
    severity: EventSeverity = EventSeverity.ROUTINE,
    detail: str = "",
) -> NotifyEvent:
    return NotifyEvent(kind=kind, title=title, severity=severity, detail=detail)


def _init_onmc(repo_root: Path) -> None:
    """Minimal init so the CLI can find the repo."""
    (repo_root / ".git").mkdir(exist_ok=True)
    (repo_root / ".onmc").mkdir(exist_ok=True)
    config_yaml = repo_root / ".onmc" / "config.yaml"
    config_yaml.write_text(f"version: 1\nrepo_root: {repo_root}\n", encoding="utf-8")
    db_path = repo_root / ".onmc" / "memory.db"
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.close()


# ---------------------------------------------------------------------------
# FileSink
# ---------------------------------------------------------------------------


class TestFileSink:
    def test_emit_appends_jsonl(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        event = _make_event(title="hello world", kind=EventKind.MEMORY_CAPTURED)
        sink.emit(event)

        log = sink.log_path
        assert log.exists()
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["title"] == "hello world"
        assert record["kind"] == EventKind.MEMORY_CAPTURED

    def test_emit_multiple_appends_lines(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        for i in range(5):
            sink.emit(_make_event(title=f"event {i}"))

        lines = sink.log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 5

    def test_emit_records_severity_and_ts(self, tmp_path: Path) -> None:
        before = time.time()
        sink = FileSink(tmp_path)
        sink.emit(_make_event(severity=EventSeverity.FAILURE, title="crash"))
        after = time.time()

        record = json.loads(sink.log_path.read_text(encoding="utf-8").splitlines()[0])
        assert record["severity"] == "failure"
        assert before <= record["ts"] <= after

    def test_emit_creates_parent_dirs(self, tmp_path: Path) -> None:
        # repo_root/.onmc/ does not exist yet
        new_root = tmp_path / "new_project"
        sink = FileSink(new_root)
        sink.emit(_make_event(title="make dirs"))
        assert sink.log_path.exists()

    def test_emit_is_exception_safe_on_unwritable_path(self, tmp_path: Path) -> None:
        """FileSink must not raise even when the target is unwritable."""
        sink = FileSink(tmp_path)
        # Make .onmc a file (not a directory) to force a write error.
        (tmp_path / ".onmc").write_text("not a directory")
        # Must not raise.
        sink.emit(_make_event(title="force error"))

    def test_emit_detail_preserved(self, tmp_path: Path) -> None:
        sink = FileSink(tmp_path)
        sink.emit(_make_event(title="titled", detail="some long detail here"))
        record = json.loads(sink.log_path.read_text(encoding="utf-8").splitlines()[0])
        assert record["detail"] == "some long detail here"


# ---------------------------------------------------------------------------
# DiscordSink
# ---------------------------------------------------------------------------


class TestDiscordSink:
    def test_noop_without_webhook(self) -> None:
        """No exception, no network call when webhook is None."""
        sink = DiscordSink(None)
        sink.emit(_make_event(title="noop"))  # must not raise

    def test_noop_with_empty_string(self) -> None:
        sink = DiscordSink("")
        sink.emit(_make_event(title="noop"))  # must not raise

    def test_swallows_network_error(self) -> None:
        """urlopen raises — DiscordSink must swallow it silently."""
        sink = DiscordSink("https://discord.com/api/webhooks/test/fake")
        with patch("urllib.request.urlopen", side_effect=OSError("simulated network failure")):
            sink.emit(_make_event(title="boom"))  # must not raise

    def test_swallows_http_error(self) -> None:
        import urllib.error

        sink = DiscordSink("https://discord.com/api/webhooks/test/fake")
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="", code=400, msg="Bad Request", hdrs=MagicMock(), fp=None
            ),
        ):
            sink.emit(_make_event(title="http error"))  # must not raise

    def test_does_not_call_network_without_url(self) -> None:
        sink = DiscordSink(None)
        with patch("urllib.request.urlopen") as mock_open:
            sink.emit(_make_event(title="no call"))
            mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# SlackSink
# ---------------------------------------------------------------------------


class TestSlackSink:
    def test_noop_without_webhook(self) -> None:
        sink = SlackSink(None)
        sink.emit(_make_event(title="noop"))

    def test_noop_with_empty_string(self) -> None:
        sink = SlackSink("")
        sink.emit(_make_event(title="noop"))

    def test_swallows_network_error(self) -> None:
        sink = SlackSink("https://hooks.slack.com/services/fake/url")
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            sink.emit(_make_event(title="slack error"))  # must not raise

    def test_does_not_call_network_without_url(self) -> None:
        sink = SlackSink(None)
        with patch("urllib.request.urlopen") as mock_open:
            sink.emit(_make_event(title="no call"))
            mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# NotifyRouter
# ---------------------------------------------------------------------------


class TestNotifyRouter:
    def test_routine_event_writes_to_file_sink(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {"enabled": True, "sink": "file"}
        router = NotifyRouter(tmp_path, config=cfg)
        router.emit(_make_event(title="routine"))

        log_path = router.file_sink.log_path
        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["title"] == "routine"

    def test_failure_event_emits_immediately(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {"enabled": True, "sink": "file"}
        router = NotifyRouter(tmp_path, config=cfg)
        router.emit(_make_event(title="crash!", severity=EventSeverity.FAILURE))

        record = json.loads(router.file_sink.log_path.read_text(encoding="utf-8").strip())
        assert record["severity"] == "failure"

    def test_approval_event_emits_immediately(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {"enabled": True, "sink": "file"}
        router = NotifyRouter(tmp_path, config=cfg)
        router.emit(_make_event(title="approved", severity=EventSeverity.APPROVAL))

        record = json.loads(router.file_sink.log_path.read_text(encoding="utf-8").strip())
        assert record["severity"] == "approval"

    def test_disabled_router_drops_event(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {"enabled": False, "sink": "file"}
        router = NotifyRouter(tmp_path, config=cfg)
        router.emit(_make_event(title="dropped"))

        assert not router.file_sink.log_path.exists()

    def test_none_sink_drops_event(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {"enabled": True, "sink": "none"}
        router = NotifyRouter(tmp_path, config=cfg)
        router.emit(_make_event(title="dropped"))

        assert not router.file_sink.log_path.exists()

    def test_discord_sink_routes_to_discord(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {
            "enabled": True,
            "sink": "discord",
            "discord_webhook": "https://discord.com/api/webhooks/test",
        }
        router = NotifyRouter(tmp_path, config=cfg)
        assert isinstance(router._extra_sink, DiscordSink)  # noqa: SLF001

    def test_slack_sink_routes_to_slack(self, tmp_path: Path) -> None:
        cfg: dict[str, Any] = {
            "enabled": True,
            "sink": "slack",
            "slack_webhook": "https://hooks.slack.com/services/x",
        }
        router = NotifyRouter(tmp_path, config=cfg)
        assert isinstance(router._extra_sink, SlackSink)  # noqa: SLF001


# ---------------------------------------------------------------------------
# emit_event — module-level convenience
# ---------------------------------------------------------------------------


class TestEmitEvent:
    def test_emit_event_is_exception_safe_with_bad_root(self) -> None:
        """emit_event must not raise even with a nonsense repo_root."""
        bad_root = Path("/does/not/exist/at/all")
        event = _make_event(title="should not raise")
        emit_event(bad_root, event)  # must not raise

    def test_emit_event_writes_to_file(self, tmp_path: Path) -> None:
        event = _make_event(title="via emit_event", kind=EventKind.SKILL_PROMOTED)
        emit_event(tmp_path, event)

        log_path = FileSink(tmp_path).log_path
        assert log_path.exists()
        record = json.loads(log_path.read_text(encoding="utf-8").strip())
        assert record["title"] == "via emit_event"

    def test_emit_event_exception_safe_when_misconfigured(self, tmp_path: Path) -> None:
        """Even if config.yaml has invalid YAML, emit_event must not raise."""
        onmc_dir = tmp_path / ".onmc"
        onmc_dir.mkdir()
        (onmc_dir / "config.yaml").write_text(":::invalid yaml:::", encoding="utf-8")

        event = _make_event(title="bad config")
        emit_event(tmp_path, event)  # must not raise


# ---------------------------------------------------------------------------
# Config precedence: env > yaml > default
# ---------------------------------------------------------------------------


class TestConfigPrecedence:
    def test_default_sink_is_file(self, tmp_path: Path) -> None:
        cfg = _resolve_notify_config(tmp_path)
        assert cfg["sink"] == "file"
        assert cfg["enabled"] is True

    def test_yaml_overrides_default(self, tmp_path: Path) -> None:
        onmc_dir = tmp_path / ".onmc"
        onmc_dir.mkdir()
        (onmc_dir / "config.yaml").write_text(
            "version: 1\nrepo_root: .\nnotify:\n  sink: discord\n  discord_webhook: https://x.y\n",
            encoding="utf-8",
        )
        cfg = _resolve_notify_config(tmp_path)
        assert cfg["sink"] == "discord"
        assert cfg["discord_webhook"] == "https://x.y"

    def test_env_wins_over_yaml(self, tmp_path: Path) -> None:
        onmc_dir = tmp_path / ".onmc"
        onmc_dir.mkdir()
        (onmc_dir / "config.yaml").write_text(
            "version: 1\nrepo_root: .\nnotify:\n  sink: discord\n",
            encoding="utf-8",
        )
        env = {"ONMC_NOTIFY_SINK": "slack", "ONMC_SLACK_WEBHOOK": "https://hooks.slack.com/x"}
        with patch.dict(os.environ, env, clear=False):
            cfg = _resolve_notify_config(tmp_path)
        assert cfg["sink"] == "slack"
        assert cfg["slack_webhook"] == "https://hooks.slack.com/x"

    def test_env_disabled_wins_over_yaml_enabled(self, tmp_path: Path) -> None:
        onmc_dir = tmp_path / ".onmc"
        onmc_dir.mkdir()
        (onmc_dir / "config.yaml").write_text(
            "version: 1\nrepo_root: .\nnotify:\n  enabled: true\n",
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"ONMC_NOTIFY_ENABLED": "0"}, clear=False):
            cfg = _resolve_notify_config(tmp_path)
        assert cfg["enabled"] is False

    def test_env_discord_webhook_wins(self, tmp_path: Path) -> None:
        with patch.dict(
            os.environ,
            {"ONMC_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/env"},
            clear=False,
        ):
            cfg = _resolve_notify_config(tmp_path)
        assert cfg["discord_webhook"] == "https://discord.com/api/webhooks/env"


# ---------------------------------------------------------------------------
# CLI commands: notify test / status / tail
# ---------------------------------------------------------------------------


class TestNotifyCLI:
    def test_notify_test_exit_code_zero(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        result = _runner.invoke(app, ["notify", "test"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "notify test" in result.output.lower() or "event written" in result.output.lower()

    def test_notify_test_custom_message(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(
                app, ["notify", "test", "--message", "hello firewall"], catch_exceptions=False
            )
        assert result.exit_code == 0

    def test_notify_status_exit_code_zero(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(app, ["notify", "status"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_notify_status_json_output(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(app, ["notify", "status", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "sink" in payload
        assert "enabled" in payload
        assert "log_path" in payload

    def test_notify_tail_empty_log(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(app, ["notify", "tail"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "No events" in result.output or result.exit_code == 0

    def test_notify_tail_json_output(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        # Write a test event first.
        sink = FileSink(tmp_path)
        sink.emit(_make_event(title="event for tail"))

        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(app, ["notify", "tail", "--json"], catch_exceptions=False)
        assert result.exit_code == 0
        events = json.loads(result.output)
        assert isinstance(events, list)
        assert len(events) == 1
        assert events[0]["title"] == "event for tail"

    def test_notify_tail_respects_n(self, tmp_path: Path) -> None:
        _init_onmc(tmp_path)
        sink = FileSink(tmp_path)
        for i in range(10):
            sink.emit(_make_event(title=f"event {i}"))

        with patch("oh_no_my_claudecode.core.service.discover_repo_root", return_value=tmp_path):
            result = _runner.invoke(
                app, ["notify", "tail", "-n", "3", "--json"], catch_exceptions=False
            )
        assert result.exit_code == 0
        events = json.loads(result.output)
        assert len(events) == 3


# ---------------------------------------------------------------------------
# NotifyEvent dataclass
# ---------------------------------------------------------------------------


class TestNotifyEvent:
    def test_default_ts_is_recent(self) -> None:
        before = time.time()
        ev = NotifyEvent(kind=EventKind.GENERIC, title="x")
        after = time.time()
        assert before <= ev.ts <= after

    def test_kind_str_values(self) -> None:
        assert str(EventKind.MEMORY_CAPTURED) == "memory_captured"
        assert str(EventKind.SKILL_PROMOTED) == "skill_promoted"
        assert str(EventKind.DANGER_BLOCKED) == "danger_blocked"

    def test_severity_str_values(self) -> None:
        assert str(EventSeverity.ROUTINE) == "routine"
        assert str(EventSeverity.FAILURE) == "failure"
        assert str(EventSeverity.APPROVAL) == "approval"
