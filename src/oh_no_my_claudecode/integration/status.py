"""Detect whether onmc is wired into Claude Code for a repo."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.hooks.installer import (
    hooks_installed,
    mcp_config_path,
    project_settings_path,
    wrap_hooks_installed,
)
from oh_no_my_claudecode.wrap.state import CLAUDE_MD_BEGIN, claude_md_path


@dataclass(frozen=True)
class IntegrationStatus:
    """Which Claude Code integration pieces are active for a repo.

    Attributes
    ----------
    mcp_registered:
        The onmc MCP server is present in ``.mcp.json`` (``onmc serve --mcp``).
    hooks_installed:
        The session hooks (PreCompact/SessionStart/UserPromptSubmit/SessionEnd)
        are in ``.claude/settings.json``.
    wrap_installed:
        The strict ``wrap`` Task-intercept is active — native agent spawns are
        redirected to ``onmc swarm`` (onmc is *the* default layer).
    claude_md_stanza:
        The onmc policy stanza is present in ``CLAUDE.md``.
    """

    mcp_registered: bool
    hooks_installed: bool
    wrap_installed: bool
    claude_md_stanza: bool

    @property
    def level(self) -> str:
        """``full`` (default layer), ``partial`` (some pieces), or ``none``."""
        if self.mcp_registered and self.hooks_installed and self.wrap_installed:
            return "full"
        if self.mcp_registered or self.hooks_installed or self.wrap_installed:
            return "partial"
        return "none"

    @property
    def next_steps(self) -> list[str]:
        """The commands that would complete the integration, in order."""
        steps: list[str] = []
        if not (self.mcp_registered and self.hooks_installed):
            steps.append("onmc plug claude-code")
        if not self.wrap_installed:
            steps.append("onmc wrap --strict")
        return steps

    def to_dict(self) -> dict[str, Any]:
        return {
            "mcp_registered": self.mcp_registered,
            "hooks_installed": self.hooks_installed,
            "wrap_installed": self.wrap_installed,
            "claude_md_stanza": self.claude_md_stanza,
            "level": self.level,
            "next_steps": self.next_steps,
        }


def mcp_registered(repo_root: Path) -> bool:
    """True when ``.mcp.json`` registers an ``onmc`` MCP server."""
    try:
        payload = json.loads(mcp_config_path(repo_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    servers = payload.get("mcpServers")
    return isinstance(servers, dict) and "onmc" in servers


def _stanza_present(repo_root: Path) -> bool:
    try:
        return CLAUDE_MD_BEGIN in claude_md_path(repo_root).read_text(encoding="utf-8")
    except OSError:
        return False


def integration_status(repo_root: Path) -> IntegrationStatus:
    """Build the read-only Claude Code integration status for *repo_root*."""
    settings = project_settings_path(repo_root)
    return IntegrationStatus(
        mcp_registered=mcp_registered(repo_root),
        hooks_installed=hooks_installed(settings_path=settings),
        wrap_installed=wrap_hooks_installed(settings_path=settings),
        claude_md_stanza=_stanza_present(repo_root),
    )
