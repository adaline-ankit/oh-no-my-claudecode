"""Security scan rules for the onmc audit command.

Each rule is a callable with signature ``(repo_root: Path) -> list[AuditFinding]``.
Rules are deterministic, static, and make no network calls.

Rule catalogue
--------------
PERM-001  Wildcard Bash permission allow (settings.json)
PERM-002  Blanket tool allow with ``*`` glob (settings.json)
PERM-003  Dangerous auto-approve of all tools (settings.json)
HOOK-001  Hook command references an unresolvable / external binary
HOOK-002  Hook shell snippet uses eval or curl|bash (hook injection)
MCP-001   MCP server command fetches and pipes remote code (curl|sh, wget|sh)
MCP-002   MCP server uses npx/uvx with an unpinned package version
MCP-003   MCP server uses bash -c with a remote URL
SECRET-001  AWS access key ID embedded in a scanned file
SECRET-002  Private key PEM block embedded in a scanned file
SECRET-003  Generic api_key / secret / token / password assignment with a value
SECRET-004  GitHub / Slack / other OAuth token prefix patterns
PROMPT-001  Embedded instruction that looks like a prompt-injection attempt
             (e.g. "ignore previous instructions")
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from oh_no_my_claudecode.audit.scanner import AuditFinding, AuditSeverity

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

RuleFn = Callable[[Path], list[AuditFinding]]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rel(repo_root: Path, path: Path) -> str:
    """Return a repo-relative POSIX path string."""
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str | None:
    """Read a file as text; return None if it does not exist or is unreadable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _load_json(path: Path) -> object:
    """Load JSON from a file; return None on any error."""
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _finding(
    rule_id: str,
    severity: AuditSeverity,
    title: str,
    file: str,
    line: int | None,
    detail: str,
    fix: str,
) -> AuditFinding:
    return AuditFinding(
        rule_id=rule_id,
        severity=severity,
        title=title,
        file=file,
        line=line,
        detail=detail,
        fix=fix,
    )


def _line_number(text: str, pos: int) -> int:
    """Return 1-based line number of character position *pos* in *text*."""
    return text[:pos].count("\n") + 1


# ---------------------------------------------------------------------------
# Secret patterns
# ---------------------------------------------------------------------------

# Deliberately-fake format strings used only in unit-test fixtures should NOT
# match the anchored patterns below.  Real values have specific prefix/length.

_SECRET_PATTERNS: list[tuple[str, str, str, str]] = [
    # (rule_id, title, regex_pattern, fix)
    (
        "SECRET-001",
        "Possible AWS access key ID",
        r"AKIA[0-9A-Z]{16}",
        "Remove the key from this file. Rotate the AWS credentials immediately and "
        "store them in environment variables or a secrets manager.",
    ),
    (
        "SECRET-002",
        "Private key PEM block",
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |)?PRIVATE KEY-----",
        "Remove the private key from this file. Revoke and regenerate the key pair. "
        "Store private keys in a secrets manager, never in plaintext files.",
    ),
    (
        "SECRET-003",
        "Hardcoded credential assignment",
        r'(?i)(?:api[_\-]?key|secret|token|password)\s*[:=]\s*[\'"][^\'"]{12,}[\'"]',
        "Replace the hardcoded value with an environment-variable reference. "
        "Rotate the credential if it was ever committed.",
    ),
    (
        "SECRET-004",
        "Possible OAuth / service token",
        r"(?:ghp_|ghs_|github_pat_|xoxb-|xoxa-|xoxp-|sk-[A-Za-z0-9]{20,})[A-Za-z0-9_\-]{6,}",
        "Remove the token from this file. Revoke it immediately via the issuing "
        "platform and use an environment variable or secret vault instead.",
    ),
]


def _scan_secrets(repo_root: Path, rel_path: str) -> list[AuditFinding]:
    """Run all secret-detection patterns against a single file."""
    path = repo_root / rel_path
    text = _read_text(path)
    if text is None:
        return []

    findings: list[AuditFinding] = []
    for rule_id, title, pattern, fix in _SECRET_PATTERNS:
        for match in re.finditer(pattern, text):
            # Skip obvious test-fixture / placeholder strings to reduce noise.
            surrounding = text[max(0, match.start() - 30) : match.end() + 30].lower()
            if any(
                marker in surrounding
                for marker in ("fake", "example", "placeholder", "test", "dummy", "noqa")
            ):
                continue
            findings.append(
                _finding(
                    rule_id=rule_id,
                    severity="critical",
                    title=f"{title} in {rel_path}",
                    file=rel_path,
                    line=_line_number(text, match.start()),
                    detail=(
                        f"Pattern matched: `{match.group()[:40]!r}` — this looks like a "
                        "real credential embedded in a tracked file."
                    ),
                    fix=fix,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule: PERM-001 — wildcard Bash allow
# ---------------------------------------------------------------------------


def rule_perm_wildcard_bash(repo_root: Path) -> list[AuditFinding]:
    """Flag ``Bash(*)`` or ``Bash(**)`` in Claude Code settings allow-lists."""
    findings: list[AuditFinding] = []
    for settings_rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        settings_path = repo_root / settings_rel
        data = _load_json(settings_path)
        if not isinstance(data, dict):
            continue
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            continue
        allow_list: object = permissions.get("allow", [])
        if not isinstance(allow_list, list):
            continue
        for entry in allow_list:
            if not isinstance(entry, str):
                continue
            # Match Bash(*) or Bash(**) — wildcard glob for all shell commands.
            if re.fullmatch(r"Bash\(\s*\*+\s*\)", entry.strip()):
                findings.append(
                    _finding(
                        rule_id="PERM-001",
                        severity="high",
                        title=f"Wildcard Bash permission in {settings_rel}",
                        file=settings_rel,
                        line=None,
                        detail=(
                            f"The entry `{entry}` grants the agent unrestricted shell "
                            "execution.  Any tool call can run arbitrary commands without "
                            "further approval — a critical privilege-escalation surface."
                        ),
                        fix=(
                            "Replace `Bash(*)` with specific allow-listed commands, e.g. "
                            '`"Bash(npm run *)"` or `"Bash(git *)"`.  '
                            "Only allow-list the exact commands the agent legitimately needs."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Rule: PERM-002 — blanket tool allow with bare ``*``
# ---------------------------------------------------------------------------


def rule_perm_blanket_allow(repo_root: Path) -> list[AuditFinding]:
    """Flag a bare ``*`` entry in the permissions allow-list."""
    findings: list[AuditFinding] = []
    for settings_rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        settings_path = repo_root / settings_rel
        data = _load_json(settings_path)
        if not isinstance(data, dict):
            continue
        permissions = data.get("permissions", {})
        if not isinstance(permissions, dict):
            continue
        allow_list: object = permissions.get("allow", [])
        if not isinstance(allow_list, list):
            continue
        for entry in allow_list:
            if isinstance(entry, str) and entry.strip() == "*":
                findings.append(
                    _finding(
                        rule_id="PERM-002",
                        severity="high",
                        title=f"Blanket tool allow (`*`) in {settings_rel}",
                        file=settings_rel,
                        line=None,
                        detail=(
                            "A bare `*` in `permissions.allow` approves every tool call "
                            "the agent could ever make — file reads, shell execution, "
                            "network calls — without further prompting."
                        ),
                        fix=(
                            'Remove the `"*"` entry and enumerate specific allowed tools or '
                            "command patterns (e.g. `Bash(git *)`, `Read`, `Edit`)."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Rule: PERM-003 — dangerous auto-approve flag
# ---------------------------------------------------------------------------


def rule_perm_auto_approve_all(repo_root: Path) -> list[AuditFinding]:
    """Flag ``autoApproveTools: true`` or similar blanket auto-approval keys."""
    findings: list[AuditFinding] = []
    for settings_rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        settings_path = repo_root / settings_rel
        data = _load_json(settings_path)
        if not isinstance(data, dict):
            continue
        # Claude Code uses `autoApproveTools` (boolean) to skip all approval prompts.
        if data.get("autoApproveTools") is True:
            findings.append(
                _finding(
                    rule_id="PERM-003",
                    severity="high",
                    title=f"Auto-approve all tools enabled in {settings_rel}",
                    file=settings_rel,
                    line=None,
                    detail=(
                        "`autoApproveTools: true` instructs the agent to execute all tool "
                        "calls without human confirmation.  Combined with a capable agent, "
                        "this removes the human-in-the-loop safety net entirely."
                    ),
                    fix=(
                        "Set `autoApproveTools` to `false` or remove the key.  "
                        "Use fine-grained `permissions.allow` entries for the specific "
                        "commands the agent needs instead."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule: HOOK-001 — hook references unresolvable / obviously-external binary
# ---------------------------------------------------------------------------

_EXTERNAL_HOOK_PATTERN = re.compile(
    r"(https?://|curl\s+http|wget\s+http)",
    re.IGNORECASE,
)


def rule_hook_external_command(repo_root: Path) -> list[AuditFinding]:
    """Flag hooks whose command fetches from a remote URL."""
    findings: list[AuditFinding] = []
    for settings_rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        settings_path = repo_root / settings_rel
        data = _load_json(settings_path)
        if not isinstance(data, dict):
            continue
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            continue
        for event_name, hook_list in hooks.items():
            if not isinstance(hook_list, list):
                continue
            for hook in hook_list:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command", "")
                if not isinstance(cmd, str):
                    continue
                if _EXTERNAL_HOOK_PATTERN.search(cmd):
                    findings.append(
                        _finding(
                            rule_id="HOOK-001",
                            severity="high",
                            title=(
                                f"Hook for `{event_name}` fetches from a remote URL "
                                f"in {settings_rel}"
                            ),
                            file=settings_rel,
                            line=None,
                            detail=(
                                f"The hook command `{cmd[:80]}` makes an outbound "
                                "network request.  A compromised or redirected URL "
                                "could silently execute arbitrary code during every "
                                "agent session."
                            ),
                            fix=(
                                "Replace the remote URL with a local script checked into "
                                "the repository.  Pin the script by hash if sourced from "
                                "a third party."
                            ),
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# Rule: HOOK-002 — hook shell snippet uses eval or curl|bash
# ---------------------------------------------------------------------------

_HOOK_INJECTION_PATTERNS = [
    re.compile(r"\beval\b", re.IGNORECASE),
    re.compile(r"curl[^|]*\|[^|]*(?:bash|sh)\b", re.IGNORECASE),
    re.compile(r"wget[^|]*\|[^|]*(?:bash|sh)\b", re.IGNORECASE),
]

_HOOKS_JSON_WRITE_OUTSIDE_REPO = re.compile(
    r"(?:>>?|tee|cp|mv|install)\s+/(?!tmp/|var/folders/)[^\s]",
    re.IGNORECASE,
)


def rule_hook_shell_injection(repo_root: Path) -> list[AuditFinding]:
    """Flag risky shell patterns (eval, curl|bash) in hook commands and hooks.json."""
    findings: list[AuditFinding] = []

    # Check settings files for hook commands.
    for settings_rel in (
        ".claude/settings.json",
        ".claude/settings.local.json",
    ):
        settings_path = repo_root / settings_rel
        data = _load_json(settings_path)
        if not isinstance(data, dict):
            continue
        hooks = data.get("hooks", {})
        if not isinstance(hooks, dict):
            continue
        for event_name, hook_list in hooks.items():
            if not isinstance(hook_list, list):
                continue
            for hook in hook_list:
                if not isinstance(hook, dict):
                    continue
                cmd = hook.get("command", "")
                if not isinstance(cmd, str):
                    continue
                for pat in _HOOK_INJECTION_PATTERNS:
                    if pat.search(cmd):
                        findings.append(
                            _finding(
                                rule_id="HOOK-002",
                                severity="high",
                                title=(
                                    f"Shell-injection pattern in `{event_name}` hook "
                                    f"in {settings_rel}"
                                ),
                                file=settings_rel,
                                line=None,
                                detail=(
                                    f"The hook command `{cmd[:80]}` contains a pattern "
                                    "(`eval` or `curl|bash`) that allows arbitrary remote "
                                    "code execution.  An attacker who can influence the "
                                    "fetched content can take over the agent environment."
                                ),
                                fix=(
                                    "Replace `eval` / `curl|bash` with explicit, "
                                    "path-pinned scripts stored in the repository.  "
                                    "Never pipe downloaded content directly to a shell."
                                ),
                            )
                        )
                        break  # One finding per hook command is enough.

    # Check hooks/hooks.json.
    hooks_json_path = repo_root / "hooks" / "hooks.json"
    hooks_data = _load_json(hooks_json_path)
    hooks_rel = "hooks/hooks.json"
    if isinstance(hooks_data, dict):
        for event_name, hook_list in hooks_data.items():
            if not isinstance(hook_list, list):
                continue
            for hook in hook_list:
                hook_cmd: object = ""
                if isinstance(hook, dict):
                    hook_cmd = hook.get("command", "")
                elif isinstance(hook, str):
                    hook_cmd = hook
                if not isinstance(hook_cmd, str):
                    continue
                for pat in _HOOK_INJECTION_PATTERNS:
                    if pat.search(hook_cmd):
                        findings.append(
                            _finding(
                                rule_id="HOOK-002",
                                severity="high",
                                title=(
                                    f"Shell-injection pattern in `{event_name}` hook "
                                    f"in {hooks_rel}"
                                ),
                                file=hooks_rel,
                                line=None,
                                detail=(
                                    f"The hook command `{hook_cmd[:80]}` uses `eval` or "
                                    "`curl|bash`, enabling remote code execution."
                                ),
                                fix=(
                                    "Replace the risky pattern with a local pinned script."
                                ),
                            )
                        )
                        break
                # Write-outside-repo check.
                if isinstance(hook_cmd, str) and _HOOKS_JSON_WRITE_OUTSIDE_REPO.search(hook_cmd):
                    findings.append(
                        _finding(
                            rule_id="HOOK-002",
                            severity="medium",
                            title=(
                                f"Hook `{event_name}` writes outside repository "
                                f"in {hooks_rel}"
                            ),
                            file=hooks_rel,
                            line=None,
                            detail=(
                                f"The command `{hook_cmd[:80]}` writes to a path outside the "
                                "repository.  This could exfiltrate data or persist "
                                "malicious artefacts on the host system."
                            ),
                            fix=(
                                "Restrict all hook write operations to paths inside the "
                                "repository or explicitly approved temporary directories."
                            ),
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# Rule: MCP-001 — MCP server fetches and pipes remote code
# ---------------------------------------------------------------------------

_MCP_REMOTE_EXEC_PATTERN = re.compile(
    r"(?:curl|wget)[^|;&]*\|[^|;&]*(?:bash|sh|python|node)\b",
    re.IGNORECASE,
)


def rule_mcp_remote_code_exec(repo_root: Path) -> list[AuditFinding]:
    """Flag MCP server commands that fetch and execute remote code."""
    findings: list[AuditFinding] = []
    data = _load_json(repo_root / ".mcp.json")
    if not isinstance(data, dict):
        return findings
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return findings
    for server_name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        cmd: object = server_cfg.get("command", "")
        args: object = server_cfg.get("args", [])
        # Build a combined command string for pattern matching.
        full_cmd = str(cmd)
        if isinstance(args, list):
            full_cmd += " " + " ".join(str(a) for a in args)
        if _MCP_REMOTE_EXEC_PATTERN.search(full_cmd):
            findings.append(
                _finding(
                    rule_id="MCP-001",
                    severity="critical",
                    title=f"MCP server `{server_name}` executes remotely fetched code",
                    file=".mcp.json",
                    line=None,
                    detail=(
                        f"The server command `{full_cmd[:100]}` downloads and pipes "
                        "content to a shell interpreter.  A compromised CDN or DNS "
                        "hijack could silently run attacker-controlled code inside "
                        "the agent's execution environment."
                    ),
                    fix=(
                        "Replace the remote-fetch pattern with a versioned, vendored "
                        "script committed to the repository.  Pin the script by its "
                        "content hash and verify before execution."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule: MCP-002 — npx / uvx without pinned version
# ---------------------------------------------------------------------------

_UNPINNED_NPX_UVX = re.compile(
    # npx <pkg> or uvx <pkg> where <pkg> has no @version or ==version suffix
    r"^(npx|uvx)\s+(?!--)([a-zA-Z0-9@][a-zA-Z0-9._\-/]*)$",
)


def _is_version_pinned(pkg: str) -> bool:
    """Return True if the package string includes a version specifier."""
    # npm: @scope/name@version or name@version
    if re.search(r"@[0-9]", pkg):
        return True
    # pypi / uv: name==version or name>=version
    return bool(re.search(r"[=><!]{1,2}[0-9]", pkg))


def rule_mcp_unpinned_npx_uvx(repo_root: Path) -> list[AuditFinding]:
    """Flag MCP servers using npx/uvx to run unpinned packages."""
    findings: list[AuditFinding] = []
    data = _load_json(repo_root / ".mcp.json")
    if not isinstance(data, dict):
        return findings
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return findings
    for server_name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        cmd: object = server_cfg.get("command", "")
        args: object = server_cfg.get("args", [])
        if not isinstance(cmd, str):
            continue
        launcher = cmd.strip()
        if launcher not in ("npx", "uvx"):
            continue
        # First positional arg is the package name.
        pkg_arg = ""
        if isinstance(args, list) and args:
            # Skip flags like -y / --yes
            for a in args:
                a_str = str(a)
                if not a_str.startswith("-"):
                    pkg_arg = a_str
                    break
        if pkg_arg and not _is_version_pinned(pkg_arg):
            findings.append(
                _finding(
                    rule_id="MCP-002",
                    severity="high",
                    title=f"MCP server `{server_name}` uses unpinned {launcher} package",
                    file=".mcp.json",
                    line=None,
                    detail=(
                        f"`{launcher} {pkg_arg}` resolves to whatever the latest version "
                        "is at run-time.  A malicious publish or version bump can "
                        "silently introduce backdoors into the agent's MCP toolchain."
                    ),
                    fix=(
                        f"Pin the package version: `{launcher} {pkg_arg}@<exact-version>` "
                        "(npm) or `{launcher} {pkg_arg}==<exact-version>` (pypi).  "
                        "Add the pinned version to your dependency audit process."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule: MCP-003 — bash -c with a remote URL inside MCP server args
# ---------------------------------------------------------------------------

_BASH_C_REMOTE = re.compile(r"bash\s+-c.*https?://", re.IGNORECASE)


def rule_mcp_bash_c_remote(repo_root: Path) -> list[AuditFinding]:
    """Flag MCP server args that run ``bash -c`` with a remote URL."""
    findings: list[AuditFinding] = []
    data = _load_json(repo_root / ".mcp.json")
    if not isinstance(data, dict):
        return findings
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return findings
    for server_name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        args: object = server_cfg.get("args", [])
        if not isinstance(args, list):
            continue
        full_args = " ".join(str(a) for a in args)
        if _BASH_C_REMOTE.search(full_args):
            findings.append(
                _finding(
                    rule_id="MCP-003",
                    severity="critical",
                    title=(
                        f"MCP server `{server_name}` uses `bash -c` with a remote URL"
                    ),
                    file=".mcp.json",
                    line=None,
                    detail=(
                        f"Server args contain `{full_args[:100]}` — running `bash -c` "
                        "with a remote URL allows arbitrary code injection via the "
                        "fetched content, DNS hijacking, or CDN compromise."
                    ),
                    fix=(
                        "Replace the inline `bash -c <url>` pattern with a local, "
                        "version-pinned script committed to the repository."
                    ),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Rule: SECRET-* — scan config / instruction files for secrets
# ---------------------------------------------------------------------------

_INSTRUCTION_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".mcp.json",
]


def rule_secrets_in_config_files(repo_root: Path) -> list[AuditFinding]:
    """Scan agent-config and instruction files for embedded secrets."""
    findings: list[AuditFinding] = []
    for rel in _INSTRUCTION_FILES:
        findings.extend(_scan_secrets(repo_root, rel))
    return findings


# ---------------------------------------------------------------------------
# Rule: PROMPT-001 — prompt injection surface in CLAUDE.md / AGENTS.md
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS = [
    re.compile(
        r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?",
        re.IGNORECASE,
    ),
    re.compile(
        r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|context)",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+now\s+(?:a\s+)?(?:an?\s+)?(?:unrestricted|jailbroken|DAN|evil)",
        re.IGNORECASE,
    ),
    re.compile(
        r"forget\s+(?:all\s+)?(?:your\s+)?(?:previous\s+)?instructions?",
        re.IGNORECASE,
    ),
    re.compile(
        # Instruction hidden inside an HTML comment or zero-width space trick.
        r"<!--.*?-->",
        re.DOTALL,
    ),
]


def rule_prompt_injection_surface(repo_root: Path) -> list[AuditFinding]:
    """Flag instruction files containing prompt-injection-style text."""
    findings: list[AuditFinding] = []
    for rel in ("CLAUDE.md", "AGENTS.md"):
        path = repo_root / rel
        text = _read_text(path)
        if text is None:
            continue
        for pat in _INJECTION_PATTERNS:
            for match in pat.finditer(text):
                # HTML comments are lower severity — they may be legitimate.
                sev: AuditSeverity = (
                    "medium" if "<!--" in match.group() else "high"
                )
                findings.append(
                    _finding(
                        rule_id="PROMPT-001",
                        severity=sev,
                        title=f"Possible prompt-injection text in {rel}",
                        file=rel,
                        line=_line_number(text, match.start()),
                        detail=(
                            f"The text `{match.group()[:80]!r}` matches a known "
                            "prompt-injection pattern.  If an adversary can modify "
                            "this file (e.g. via a supply-chain PR), they can hijack "
                            "the agent's behaviour."
                        ),
                        fix=(
                            "Review and remove the injection-style phrase.  Protect "
                            "CLAUDE.md / AGENTS.md with CODEOWNERS rules and required "
                            "reviews so they cannot be modified without approval."
                        ),
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# Rule: MCP-004 — broad env var exposure in MCP server config
# ---------------------------------------------------------------------------


def rule_mcp_broad_env_exposure(repo_root: Path) -> list[AuditFinding]:
    """Flag MCP servers that pass wildcard or obviously sensitive env vars."""
    findings: list[AuditFinding] = []
    data = _load_json(repo_root / ".mcp.json")
    if not isinstance(data, dict):
        return findings
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        return findings
    sensitive_env_re = re.compile(
        r"(?i)(aws_secret|database_url|db_password|private_key|api_secret|"
        r"oauth_secret|client_secret|auth_token)",
    )
    for server_name, server_cfg in servers.items():
        if not isinstance(server_cfg, dict):
            continue
        env: object = server_cfg.get("env", {})
        if not isinstance(env, dict):
            continue
        for key, val in env.items():
            if sensitive_env_re.search(key):
                # Only flag if the value looks hardcoded (not an env-var ref).
                val_str = str(val) if val is not None else ""
                if val_str and not val_str.startswith("${") and not val_str.startswith("$"):
                    findings.append(
                        _finding(
                            rule_id="MCP-004",
                            severity="high",
                            title=(
                                f"MCP server `{server_name}` has hardcoded sensitive "
                                f"env var `{key}`"
                            ),
                            file=".mcp.json",
                            line=None,
                            detail=(
                                f"The env key `{key}` looks like a credential and its "
                                "value appears to be a literal string rather than a "
                                "shell-variable reference.  Credentials in .mcp.json "
                                "are committed to the repository in plaintext."
                            ),
                            fix=(
                                f"Replace the hardcoded value with a shell-variable "
                                f"reference: `\"{key}\": \"${{{key}}}\"` and set the "
                                "variable in your shell profile or CI secrets."
                            ),
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# Rule catalogue — ALL_RULES drives the scanner
# ---------------------------------------------------------------------------

ALL_RULES: list[RuleFn] = [
    rule_perm_wildcard_bash,
    rule_perm_blanket_allow,
    rule_perm_auto_approve_all,
    rule_hook_external_command,
    rule_hook_shell_injection,
    rule_mcp_remote_code_exec,
    rule_mcp_unpinned_npx_uvx,
    rule_mcp_bash_c_remote,
    rule_mcp_broad_env_exposure,
    rule_secrets_in_config_files,
    rule_prompt_injection_surface,
]
