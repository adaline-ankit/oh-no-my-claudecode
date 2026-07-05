"""Claude Code integration status — is onmc the default layer right now?

Answers, for a repo, whether onmc is wired into Claude Code: the MCP server is
registered (``.mcp.json``), the session hooks are installed, and the strict
``wrap`` Task-intercept is active (so *all* agent work routes through onmc).

Read-only + deterministic; reuses the existing hook/wrap detectors so it never
drifts from what ``onmc plug`` / ``onmc wrap`` actually install.
"""

from __future__ import annotations

from oh_no_my_claudecode.integration.status import (
    IntegrationStatus,
    integration_status,
    mcp_registered,
)

__all__ = ["IntegrationStatus", "integration_status", "mcp_registered"]
