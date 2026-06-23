"""MCP Trust Gateway — runtime classifier for MCP tool calls.

Complements ``onmc audit`` (static config scan) with a runtime gate:
classify individual tool calls against a policy file, scanning arguments
for prompt-injection phrases and embedded secrets.

Usage
-----
>>> from oh_no_my_claudecode.mcp_trust import McpPolicy, ToolCall, Decision
>>> from oh_no_my_claudecode.mcp_trust import classify_call, load_policy
"""

from __future__ import annotations

from oh_no_my_claudecode.mcp_trust.gateway import Decision, ToolCall, classify_call, classify_calls
from oh_no_my_claudecode.mcp_trust.policy import McpPolicy, load_policy

__all__ = [
    "Decision",
    "McpPolicy",
    "ToolCall",
    "classify_call",
    "classify_calls",
    "load_policy",
]
