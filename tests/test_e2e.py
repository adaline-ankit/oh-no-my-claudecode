"""End-to-end tests that drive the real ``onmc`` entry point as a subprocess.

Unlike the unit suite (which calls services and handlers in-process, often with
the MockProvider), these tests exercise the actual CLI binary, the real stdin
hook payload parsing, and a real MCP stdio client/server handshake. They are the
layer that catches integration gaps the mocked unit tests cannot — e.g. a CLI
signature that fails to import, a hook that prints non-JSON to stdout, or an MCP
tool that is registered but unreachable over the wire.

Every test runs fully offline: no LLM provider is configured and provider env
vars are blanked, so each command takes its deterministic heuristic path.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Invoke via ``python -m`` rather than the ``onmc`` console script so the tests
# do not depend on the script being on PATH (true in editable installs and CI).
CLI = [sys.executable, "-m", "oh_no_my_claudecode"]

TASK_ID_RE = re.compile(r"task-[0-9a-f]+")


def _run(
    *args: str,
    cwd: Path,
    home: Path,
    stdin: str | None = None,
    check: bool = True,
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    """Run ``onmc <args>`` in an isolated HOME with no LLM provider configured."""
    env = dict(os.environ)
    env["HOME"] = str(home)
    # Force the offline heuristic path and never touch a real provider.
    env["ANTHROPIC_API_KEY"] = ""
    env["OPENAI_API_KEY"] = ""
    # Subprocesses have no TTY, so Rich falls back to 80 cols and truncates
    # table cells; widen it so assertions can match full titles/summaries.
    env["COLUMNS"] = "220"
    result = subprocess.run(
        [*CLI, *args],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        msg = (
            f"`onmc {' '.join(args)}` exited {result.returncode}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        raise AssertionError(msg)
    return result


@pytest.fixture
def e2e_env(tmp_path: Path) -> tuple[Path, Path]:
    """A git repo with a little history plus an isolated fake HOME."""
    repo = tmp_path / "repo"
    repo.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(home)},
        )

    git("init")
    git("config", "user.name", "Test User")
    git("config", "user.email", "test@example.com")
    (repo / "README.md").write_text(
        "# Cache service\n\nHandles cache invalidation for worker jobs.\n",
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src" / "cache.py").write_text(
        "def invalidate_cache(key: str) -> str:\n    return f'invalidate:{key}'\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-m", "feat: initial cache module")
    (repo / "src" / "cache.py").write_text(
        "def invalidate_cache(key: str) -> str:\n"
        "    # route through the shared boundary\n"
        "    return f'invalidate:{key}'\n",
        encoding="utf-8",
    )
    git("add", "-A")
    git("commit", "-m", "refactor: centralize invalidation at the cache boundary")
    return repo, home


def _transcript_dir(home: Path, repo: Path) -> Path:
    """Mirror onmc's project-dir sanitization for the *resolved* repo path."""
    sanitized = re.sub(r"[^A-Za-z0-9]", "-", repo.resolve().as_posix())
    return home / ".claude" / "projects" / sanitized


def _assistant_line(repo: Path, *, text: str, edited: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "isSidechain": False,
            "sessionId": "sess-e2e",
            "timestamp": "2026-06-12T10:00:00Z",
            "uuid": "u-1",
            "cwd": repo.resolve().as_posix(),
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "internal", "signature": "x"},
                    {"type": "text", "text": text},
                    {
                        "type": "tool_use",
                        "name": "Edit",
                        "input": {"file_path": (repo / edited).resolve().as_posix()},
                    },
                ],
            },
        }
    )


# --------------------------------------------------------------------------- #
# Full memory lifecycle through the real CLI                                    #
# --------------------------------------------------------------------------- #


def test_full_memory_lifecycle(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env

    _run("init", cwd=repo, home=home)
    assert (repo / ".onmc").is_dir()

    ingest = _run("ingest", cwd=repo, home=home)
    assert "Commits analyzed" in ingest.stdout or "memor" in ingest.stdout.lower()

    status = _run("status", cwd=repo, home=home)
    assert repo.name in status.stdout

    _run("brief", "--task", "fix cache invalidation", cwd=repo, home=home)
    compiled = list((repo / ".onmc" / "compiled").glob("*-brief.md"))
    assert compiled, "brief should write a compiled markdown artifact"
    assert compiled[0].read_text(encoding="utf-8").strip()

    _run("claude-md", "generate", cwd=repo, home=home)
    claude_md = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "##" in claude_md, "generated CLAUDE.md should contain sections"

    _run("sync", "--commit", cwd=repo, home=home)
    assert (repo / ".agent-memory" / "manifest.json").is_file()

    # doctor must exit 0 on a healthy, fully-set-up repo.
    _run("doctor", cwd=repo, home=home)


def test_sync_survives_a_fresh_clone(e2e_env: tuple[Path, Path], tmp_path: Path) -> None:
    """The headline promise: committed memory restores on a fresh clone.

    Exercises ``sync --commit`` → ``git clone`` → ``sync --restore`` and proves
    that durable memory (repo memories, tasks, task-scoped artifacts) reappears
    on a machine that has never seen the original ``.onmc`` SQLite state.
    """
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)
    _run("ingest", cwd=repo, home=home)
    start = _run(
        "task", "start", "--title", "Fix flaky cache", "--description", "race",
        cwd=repo, home=home,
    )
    task_id = TASK_ID_RE.search(start.stdout).group(0)  # type: ignore[union-attr]
    _run(
        "memory", "add", task_id,
        "--type", "fix",
        "--title", "Route through the cache boundary",
        "--summary", "The shared boundary fixed the worker path",
        cwd=repo, home=home,
    )
    _run("sync", "--commit", cwd=repo, home=home)
    assert (repo / ".agent-memory" / "manifest.json").is_file()

    # Commit the export the way a user would, then clone into a clean dir.
    def git(cwd: Path, *args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
            env={**os.environ, "HOME": str(home)},
        )

    git(repo, "add", "-A")
    git(repo, "commit", "-m", "chore: export agent memory")

    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", str(repo), str(clone)],
        check=True, capture_output=True, text=True,
        env={**os.environ, "HOME": str(home)},
    )
    # A fresh HOME proves nothing leaks through the user account.
    fresh_home = tmp_path / "fresh_home"
    fresh_home.mkdir()

    assert not (clone / ".onmc").exists(), ".onmc is gitignored and must not clone"
    _run("init", cwd=clone, home=fresh_home)
    restore = _run("sync", "--restore", cwd=clone, home=fresh_home)
    assert "Restored" in restore.stdout

    listing = _run("memory", "list", cwd=clone, home=fresh_home)
    assert "cache boundary" in listing.stdout.lower()
    tasks = _run("task", "list", cwd=clone, home=fresh_home)
    assert "flaky cache" in tasks.stdout.lower()


def test_task_attempt_memory_roundtrip(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)

    start = _run(
        "task", "start", "--title", "Fix flaky cache", "--description", "race on refresh",
        cwd=repo, home=home,
    )
    match = TASK_ID_RE.search(start.stdout)
    assert match, f"could not find a task id in:\n{start.stdout}"
    task_id = match.group(0)

    _run(
        "attempt", "add", task_id,
        "--summary", "Tried a cache-only fix",
        "--kind", "fix_attempt",
        "--status", "tried",
        cwd=repo, home=home,
    )
    _run(
        "memory", "add", task_id,
        "--type", "fix",
        "--title", "Use the cache boundary",
        "--summary", "Routing through the shared boundary fixed the worker path",
        cwd=repo, home=home,
    )

    listing = _run("memory", "list", cwd=repo, home=home)
    assert "cache boundary" in listing.stdout.lower()

    tasks = _run("task", "list", cwd=repo, home=home)
    assert task_id in tasks.stdout


# --------------------------------------------------------------------------- #
# Claude Code hook lifecycle — the integration that was previously broken       #
# --------------------------------------------------------------------------- #


def test_hooks_install_writes_project_scoped_config(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)
    _run("hooks", "install", "--yes", cwd=repo, home=home)

    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    events = settings["hooks"]
    assert any(e.get("matcher") == "" for e in events["PreCompact"])
    pre_cmd = events["PreCompact"][0]["hooks"][0]["command"]
    assert pre_cmd == "onmc hooks pre-compact"
    session = events["SessionStart"]
    assert any(e.get("matcher") == "compact" for e in session)
    assert session[0]["hooks"][0]["command"] == "onmc hooks session-start"

    # MCP registration belongs in .mcp.json, NOT settings.json.
    assert "mcpServers" not in settings
    mcp = json.loads((repo / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["onmc"]["command"] == "onmc"
    assert mcp["mcpServers"]["onmc"]["args"] == ["serve", "--mcp"]


def test_pre_compact_then_session_start_contract(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)

    transcript_dir = _transcript_dir(home, repo)
    transcript_dir.mkdir(parents=True)
    transcript = transcript_dir / "sess-e2e.jsonl"
    transcript.write_text(
        _assistant_line(
            repo,
            text="Root caused the stale read. Next: guard the refresh in src/cache.py.",
            edited="src/cache.py",
        )
        + "\n",
        encoding="utf-8",
    )

    pre_payload = json.dumps(
        {
            "session_id": "sess-e2e",
            "transcript_path": str(transcript),
            "cwd": str(repo),
            "hook_event_name": "PreCompact",
            "trigger": "auto",
        }
    )
    pre = _run("hooks", "pre-compact", cwd=repo, home=home, stdin=pre_payload)
    assert pre.returncode == 0

    start_payload = json.dumps(
        {
            "session_id": "sess-e2e",
            "transcript_path": str(transcript),
            "cwd": str(repo),
            "hook_event_name": "SessionStart",
            "source": "compact",
        }
    )
    start = _run("hooks", "session-start", cwd=repo, home=home, stdin=start_payload)

    # stdout MUST be exactly the injection JSON and nothing else — any stray
    # output corrupts Claude Code's context injection.
    payload = json.loads(start.stdout)
    hook_out = payload["hookSpecificOutput"]
    assert hook_out["hookEventName"] == "SessionStart"
    context = hook_out["additionalContext"]
    assert context.strip(), "session-start must inject a non-empty continuation brief"
    # The brief is derived from the live transcript, so the active file surfaces.
    assert "cache" in context.lower()


def test_session_start_noop_for_non_compact_source(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)
    start_payload = json.dumps(
        {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(repo)}
    )
    start = _run("hooks", "session-start", cwd=repo, home=home, stdin=start_payload)
    # A normal startup must not inject anything (stdout empty or no context).
    assert start.stdout.strip() == "" or "additionalContext" not in start.stdout


def test_hooks_uninstall_is_clean(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)
    _run("hooks", "install", "--yes", cwd=repo, home=home)
    _run("hooks", "uninstall", cwd=repo, home=home)

    settings_path = repo / ".claude" / "settings.json"
    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        serialized = json.dumps(settings)
        assert "onmc hooks" not in serialized
    mcp_path = repo / ".mcp.json"
    if mcp_path.exists():
        mcp = json.loads(mcp_path.read_text(encoding="utf-8"))
        assert "onmc" not in mcp.get("mcpServers", {})


# --------------------------------------------------------------------------- #
# Transcript mining discovery against the real layout                           #
# --------------------------------------------------------------------------- #


def test_mine_discovers_real_transcript_layout(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)

    transcript_dir = _transcript_dir(home, repo)
    transcript_dir.mkdir(parents=True)
    (transcript_dir / "sess-e2e.jsonl").write_text(
        _assistant_line(
            repo,
            text="Fixed by editing the cache boundary.",
            edited="src/cache.py",
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run("mine", "--dry-run", "--no-llm", cwd=repo, home=home)
    assert "No Claude Code sessions found" not in result.stdout, (
        "mine must discover transcripts placed in the real "
        "~/.claude/projects/<sanitized-path>/ layout"
    )


# --------------------------------------------------------------------------- #
# MCP server: a real stdio client/server handshake over the wire                #
# --------------------------------------------------------------------------- #


async def _mcp_roundtrip(repo: Path, home: Path) -> dict[str, object]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["ANTHROPIC_API_KEY"] = ""
    env["OPENAI_API_KEY"] = ""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "oh_no_my_claudecode", "serve", "--mcp", "--repo", str(repo)],
        env=env,
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        tools = await session.list_tools()
        tool_names = {tool.name for tool in tools.tools}

        search = await session.call_tool(
            "search_memory", {"query": "cache invalidation", "limit": 5}
        )
        brief = await session.call_tool("get_brief", {"task": "fix the cache"})
        record = await session.call_tool(
            "record_memory",
            {
                "kind": "gotcha",
                "title": "Cache boundary is load-bearing",
                "summary": "Workers must not bypass the shared cache boundary.",
            },
        )
        return {
            "tool_names": tool_names,
            "search_text": search.content[0].text if search.content else "",
            "brief_text": brief.content[0].text if brief.content else "",
            "record_text": record.content[0].text if record.content else "",
        }


def test_mcp_stdio_tools_roundtrip(e2e_env: tuple[Path, Path]) -> None:
    repo, home = e2e_env
    _run("init", cwd=repo, home=home)
    _run("ingest", cwd=repo, home=home)

    result = asyncio.run(asyncio.wait_for(_mcp_roundtrip(repo, home), timeout=60))

    expected = {"search_memory", "get_brief", "record_attempt", "record_memory", "list_tasks"}
    assert expected <= result["tool_names"]  # type: ignore[operator]
    # get_brief returns markdown.
    assert "#" in str(result["brief_text"])
    # record_memory returns the created id and persists a manual memory.
    assert str(result["record_text"]).strip()

    listing = _run("memory", "list", cwd=repo, home=home)
    assert "cache boundary is load-bearing" in listing.stdout.lower()
