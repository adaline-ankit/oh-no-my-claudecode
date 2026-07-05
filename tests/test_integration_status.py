from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.integration import integration_status, mcp_registered


def test_mcp_registered_detects_onmc_entry(tmp_path: Path) -> None:
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"onmc": {"command": "onmc", "args": ["serve", "--mcp"]}}}),
        encoding="utf-8",
    )
    assert mcp_registered(tmp_path) is True


def test_mcp_registered_false_when_absent(tmp_path: Path) -> None:
    assert mcp_registered(tmp_path) is False
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")
    assert mcp_registered(tmp_path) is False


def test_integration_status_levels(tmp_path: Path) -> None:
    # Fresh repo: nothing wired.
    status = integration_status(tmp_path)
    assert status.level == "none"
    assert status.to_dict()["mcp_registered"] is False
    assert "onmc plug claude-code" in status.next_steps

    # Register only the MCP server -> partial; wrap is still a remaining step.
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"onmc": {"command": "onmc"}}}), encoding="utf-8"
    )
    status = integration_status(tmp_path)
    assert status.level == "partial"
    assert status.mcp_registered is True
    assert "onmc wrap --strict" in status.next_steps


def test_integration_status_is_json_safe(tmp_path: Path) -> None:
    payload = integration_status(tmp_path).to_dict()
    json.dumps(payload)  # must not raise
    assert set(payload) >= {
        "mcp_registered",
        "hooks_installed",
        "wrap_installed",
        "level",
        "next_steps",
    }
