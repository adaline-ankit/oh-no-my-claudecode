"""Router: resolves config, selects sink(s), and dispatches events.

Design
------
- ``NotifyRouter`` takes a ``NotifyConfig`` (or the repo root and loads it)
  and dispatches ``NotifyEvent`` to the correct sink(s).
- ``routine`` events go to the file sink immediately (no in-process buffering
  needed for CLI processes that are short-lived) and, if configured, also to
  the network sink — but network failures are always swallowed.
- ``failure`` / ``approval`` events are always emitted immediately to all
  active sinks.
- ``emit_event(repo_root, event)`` is the module-level convenience: it resolves
  config, builds a router, and dispatches.  Fully exception-safe (returns None,
  never raises) — this is what the hook agent will call.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from oh_no_my_claudecode.notify.events import NotifyEvent
from oh_no_my_claudecode.notify.sinks import DiscordSink, FileSink, Sink, SlackSink

# ---------------------------------------------------------------------------
# Config resolution
# ---------------------------------------------------------------------------

_SINK_ENV_VAR = "ONMC_NOTIFY_SINK"
_DISCORD_ENV_VAR = "ONMC_DISCORD_WEBHOOK"
_SLACK_ENV_VAR = "ONMC_SLACK_WEBHOOK"
_ENABLED_ENV_VAR = "ONMC_NOTIFY_ENABLED"


def _resolve_notify_config(repo_root: Path) -> dict[str, object]:
    """Return a resolved notify config dict with env-wins-over-yaml precedence.

    Returns a dict with keys:
    - ``enabled``: bool
    - ``sink``: str  ("file" | "discord" | "slack" | "none")
    - ``discord_webhook``: str | None
    - ``slack_webhook``: str | None
    """
    # Start with defaults.
    cfg: dict[str, object] = {
        "enabled": True,
        "sink": "file",
        "discord_webhook": None,
        "slack_webhook": None,
    }

    # Layer config.yaml values.
    try:
        from oh_no_my_claudecode.config import config_path

        yaml_path = config_path(repo_root)
        if yaml_path.exists():
            import yaml  # already a project dep

            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            notify_section = raw.get("notify", {})
            if isinstance(notify_section, dict):
                if "enabled" in notify_section:
                    cfg["enabled"] = bool(notify_section["enabled"])
                if "sink" in notify_section:
                    cfg["sink"] = str(notify_section["sink"])
                if "discord_webhook" in notify_section:
                    cfg["discord_webhook"] = notify_section["discord_webhook"] or None
                if "slack_webhook" in notify_section:
                    cfg["slack_webhook"] = notify_section["slack_webhook"] or None
    except Exception:  # noqa: BLE001, S110
        pass  # config load failure falls through to defaults

    # Env wins.
    env_enabled = os.environ.get(_ENABLED_ENV_VAR)
    if env_enabled is not None:
        cfg["enabled"] = env_enabled.strip() not in ("0", "false", "no")

    env_sink = os.environ.get(_SINK_ENV_VAR)
    if env_sink:
        cfg["sink"] = env_sink.strip().lower()

    env_discord = os.environ.get(_DISCORD_ENV_VAR)
    if env_discord:
        cfg["discord_webhook"] = env_discord.strip()

    env_slack = os.environ.get(_SLACK_ENV_VAR)
    if env_slack:
        cfg["slack_webhook"] = env_slack.strip()

    return cfg


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class NotifyRouter:
    """Resolves the active sink(s) from config and dispatches events.

    Parameters
    ----------
    repo_root:
        Root of the repository — used to locate ``.onmc/notify.log`` and
        ``config.yaml``.
    config:
        Pre-resolved notify config dict (from ``_resolve_notify_config``).
        If ``None``, resolved from ``repo_root`` at construction time.
    """

    def __init__(self, repo_root: Path, config: dict[str, object] | None = None) -> None:
        self._repo_root = repo_root
        self._cfg = config if config is not None else _resolve_notify_config(repo_root)
        self._file_sink = FileSink(repo_root)
        self._extra_sink: Sink | None = self._build_extra_sink()

    def _build_extra_sink(self) -> Sink | None:
        sink_type = str(self._cfg.get("sink", "file")).lower()
        if sink_type == "discord":
            url = self._cfg.get("discord_webhook")
            return DiscordSink(str(url) if url else None)
        if sink_type == "slack":
            url = self._cfg.get("slack_webhook")
            return SlackSink(str(url) if url else None)
        # "file" or "none" — no extra network sink.
        return None

    @property
    def enabled(self) -> bool:
        """Whether the firewall is active."""
        return bool(self._cfg.get("enabled", True))

    @property
    def sink_type(self) -> str:
        """The configured sink type string."""
        return str(self._cfg.get("sink", "file"))

    @property
    def file_sink(self) -> FileSink:
        """The always-present file sink (used by ``onmc notify tail``)."""
        return self._file_sink

    def emit(self, event: NotifyEvent) -> None:
        """Dispatch *event* to the active sink(s).

        ``routine`` events go to FileSink (and the extra sink if configured).
        ``failure`` / ``approval`` events emit immediately to all sinks.
        Exception-safe.
        """
        if not self.enabled:
            return

        sink_type = self.sink_type
        if sink_type == "none":
            return

        # Always write to FileSink (unless sink == "none" above).
        self._file_sink.emit(event)

        # Extra network sink when configured.
        if self._extra_sink is not None:
            self._extra_sink.emit(event)


# ---------------------------------------------------------------------------
# Module-level convenience (hook agent entry point)
# ---------------------------------------------------------------------------


def emit_event(repo_root: Path, event: NotifyEvent) -> None:
    """Emit *event* via the configured sink for *repo_root*.

    Fully exception-safe — never raises, never blocks.  This is the function
    the hook agent calls; it resolves the config and dispatches in one shot.

    Parameters
    ----------
    repo_root:
        Repository root (used for config + FileSink path resolution).
    event:
        The ``NotifyEvent`` to dispatch.
    """
    with contextlib.suppress(Exception):
        router = NotifyRouter(repo_root)
        router.emit(event)
