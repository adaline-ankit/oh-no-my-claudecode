"""Offline tests for the onmc MCP prompts surface."""

from __future__ import annotations

import pytest

from oh_no_my_claudecode.mcp_server.prompts import (
    get_onmc_prompt,
    list_onmc_prompts,
    render_prompt_text,
)
from oh_no_my_claudecode.slash.generator import SlashCommand


def test_lists_prompts_for_shipped_commands() -> None:
    names = {p.name for p in list_onmc_prompts()}
    # Known shipped features should each be an MCP prompt (→ /mcp__onmc__<name>).
    assert {"why", "swarm", "guard", "pulse", "budget"} <= names
    # Plumbing is filtered by the shared discovery.
    assert "serve" not in names and "slash" not in names


def test_prompt_descriptor_shape() -> None:
    by_name = {p.name: p for p in list_onmc_prompts()}
    why = by_name["why"]
    assert why.description  # non-empty help
    # `why` takes a path → exposes an args argument, not required.
    arg_names = {a.name for a in (why.arguments or [])}
    assert "args" in arg_names
    assert all(a.required is False for a in (why.arguments or []))


def test_get_prompt_builds_invocation_with_args() -> None:
    res = get_onmc_prompt("why", {"args": "src/foo.py"})
    assert res.messages
    text = res.messages[0].content.text  # type: ignore[union-attr]
    assert "onmc why src/foo.py" in text


def test_get_prompt_without_args() -> None:
    res = get_onmc_prompt("pulse", None)
    text = res.messages[0].content.text  # type: ignore[union-attr]
    assert "onmc pulse" in text


def test_unknown_prompt_raises() -> None:
    with pytest.raises(ValueError, match="unknown onmc prompt"):
        get_onmc_prompt("definitely-not-a-command", None)


def test_render_prompt_text_deterministic() -> None:
    cmd = SlashCommand(name="why", help="Explain a file", takes_args=True)
    a = render_prompt_text(cmd, "x.py")
    b = render_prompt_text(cmd, "x.py")
    assert a == b
    assert "onmc why x.py" in a


def test_render_prompt_text_no_args_no_trailing_space() -> None:
    cmd = SlashCommand(name="pulse", help="heartbeat", takes_args=False)
    text = render_prompt_text(cmd, "")
    assert "`onmc pulse`" in text  # no dangling space before backtick


def test_prompts_are_deterministic() -> None:
    assert [p.name for p in list_onmc_prompts()] == [p.name for p in list_onmc_prompts()]
