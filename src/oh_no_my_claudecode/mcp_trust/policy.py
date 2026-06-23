"""MCP policy file loader and data model.

Policy file location: ``<repo_root>/.onmc/mcp-policy.yaml``

Schema
------
The policy file uses a simple YAML format::

    # .onmc/mcp-policy.yaml
    default_decision: approval_required  # allow | block | approval_required

    allowed_servers:
      - filesystem
      - github

    tool_scopes:
      # scope: read | write | network
      filesystem__read_file: read
      filesystem__write_file: write
      github__search_repositories: network

    approval_required:
      - filesystem__write_file
      - github__create_issue

Safe defaults (when no policy file is present)
----------------------------------------------
- Unknown servers → ``approval_required``
- Network-scope tools → ``approval_required``
- ``default_decision`` → ``approval_required``
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Verdict = Literal["allow", "block", "approval_required"]
Scope = Literal["read", "write", "network"]

POLICY_FILE_NAME = "mcp-policy.yaml"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class McpPolicy:
    """Parsed representation of ``.onmc/mcp-policy.yaml``.

    Attributes
    ----------
    allowed_servers:
        Set of server names that are permitted at all.  Any server NOT in
        this set falls back to ``default_decision`` (safe default:
        ``approval_required``).
    tool_scopes:
        Mapping from ``{server}__{tool}`` key (double-underscore separator)
        to one of ``"read"``, ``"write"``, or ``"network"``.
    approval_required:
        List of ``{server}__{tool}`` keys that ALWAYS require approval,
        regardless of scope.
    default_decision:
        Verdict returned when no more-specific rule matches.
        Defaults to ``"approval_required"`` (safe).
    """

    allowed_servers: set[str] = field(default_factory=set)
    tool_scopes: dict[str, Scope] = field(default_factory=dict)
    approval_required: list[str] = field(default_factory=list)
    default_decision: Verdict = "approval_required"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_VALID_SCOPES: frozenset[str] = frozenset({"read", "write", "network"})
_VALID_VERDICTS: frozenset[str] = frozenset({"allow", "block", "approval_required"})


def load_policy(repo_root: Path) -> McpPolicy:
    """Load the MCP trust policy from ``<repo_root>/.onmc/mcp-policy.yaml``.

    Returns a safe-default policy (all unknown → approval_required) when the
    file does not exist or cannot be parsed.  Never raises.
    """
    policy_path = repo_root / ".onmc" / POLICY_FILE_NAME
    if not policy_path.exists():
        return McpPolicy()

    try:
        raw = policy_path.read_text(encoding="utf-8")
        data: object = yaml.safe_load(raw)
    except Exception:  # noqa: BLE001
        return McpPolicy()

    if not isinstance(data, dict):
        return McpPolicy()

    # allowed_servers
    allowed_servers: set[str] = set()
    raw_servers = data.get("allowed_servers") or []
    if isinstance(raw_servers, list):
        for item in raw_servers:
            if isinstance(item, str) and item.strip():
                allowed_servers.add(item.strip())

    # tool_scopes
    tool_scopes: dict[str, Scope] = {}
    raw_scopes = data.get("tool_scopes") or {}
    if isinstance(raw_scopes, dict):
        for key, val in raw_scopes.items():
            if isinstance(key, str) and isinstance(val, str) and val in _VALID_SCOPES:
                tool_scopes[key] = val  # type: ignore[assignment]

    # approval_required
    approval_required: list[str] = []
    raw_approval = data.get("approval_required") or []
    if isinstance(raw_approval, list):
        for item in raw_approval:
            if isinstance(item, str) and item.strip():
                approval_required.append(item.strip())

    # default_decision
    raw_default = data.get("default_decision", "approval_required")
    default_decision: Verdict = (
        raw_default  # type: ignore[assignment]
        if isinstance(raw_default, str) and raw_default in _VALID_VERDICTS
        else "approval_required"
    )

    return McpPolicy(
        allowed_servers=allowed_servers,
        tool_scopes=tool_scopes,
        approval_required=approval_required,
        default_decision=default_decision,
    )


# ---------------------------------------------------------------------------
# Policy file initializer
# ---------------------------------------------------------------------------

_STARTER_POLICY = textwrap.dedent(
    """\
    # .onmc/mcp-policy.yaml — MCP Trust Gateway policy
    #
    # This file declares which MCP servers and tools are allowed, their
    # permission scope, and which require human approval before execution.
    #
    # Verdicts: allow | block | approval_required
    # Scopes:   read  | write | network
    #
    # Run `onmc mcp check <calls.jsonl>` to classify recorded tool calls.
    # Run `onmc mcp policy init` to regenerate this file.

    # Default verdict for calls not matched by any rule below.
    # "approval_required" is the safe default — change to "allow" only after
    # explicitly listing every server in allowed_servers.
    default_decision: approval_required

    # List of MCP server names permitted to make calls at all.
    # Calls from servers NOT listed here fall back to default_decision.
    allowed_servers:
      - filesystem
      - github
      # - my-internal-server

    # Per-tool scope declarations.  Key format: {server}__{tool}
    # (double-underscore separator).  Scope drives approval logic:
    #   read    — safe for auto-allow on trusted servers
    #   write   — always requires approval unless explicitly listed as "allow"
    #   network — always requires approval
    tool_scopes:
      filesystem__read_file: read
      filesystem__read_multiple_files: read
      filesystem__list_directory: read
      filesystem__write_file: write
      filesystem__edit_file: write
      filesystem__create_directory: write
      github__search_repositories: network
      github__get_file_contents: read
      github__create_issue: network
      github__push_files: network

    # Tools that ALWAYS require human approval, regardless of scope.
    # Add any tool you want to force-gate here.
    approval_required:
      - filesystem__write_file
      - filesystem__edit_file
      - filesystem__create_directory
      - github__create_issue
      - github__push_files
    """
)


def init_policy(repo_root: Path, *, force: bool = False) -> Path:
    """Write a documented starter policy file to ``<repo_root>/.onmc/mcp-policy.yaml``.

    Parameters
    ----------
    repo_root:
        Root of the repository.
    force:
        Overwrite an existing policy file.  Without ``--force`` the function
        is a no-op when the file already exists.

    Returns
    -------
    Path
        Absolute path to the (written or existing) policy file.
    """
    policy_dir = repo_root / ".onmc"
    policy_dir.mkdir(parents=True, exist_ok=True)
    policy_path = policy_dir / POLICY_FILE_NAME

    if policy_path.exists() and not force:
        return policy_path

    policy_path.write_text(_STARTER_POLICY, encoding="utf-8")
    return policy_path
