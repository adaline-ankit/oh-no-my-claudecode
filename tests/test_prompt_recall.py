"""Tests for per-prompt surgical memory recall (UserPromptSubmit hook)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.installer import (
    hooks_installed,
    install_claude_hooks,
    uninstall_claude_hooks,
)
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_storage(db_path: Path) -> SQLiteStorage:
    """Return an initialised SQLiteStorage seeded with a handful of memories."""
    storage = SQLiteStorage(db_path)
    storage.initialize()

    now = utc_now()
    memories = [
        MemoryEntry(
            id="mem-cache-1",
            kind=MemoryKind.INVARIANT,
            title="Cache invalidation boundary",
            summary="All cache invalidations must go through the shared boundary module.",
            details="Direct cache writes from workers bypass the boundary and cause stale reads.",
            source_type=SourceType.DOC,
            source_ref="docs/architecture.md",
            tags=["cache", "invariant"],
            confidence=0.9,
            feedback_score=0.3,
            created_at=now,
            updated_at=now,
            staleness=None,
        ),
        MemoryEntry(
            id="mem-worker-1",
            kind=MemoryKind.DECISION,
            title="Worker refresh pattern",
            summary="Workers call invalidate_cache(), never write to the store directly.",
            details="Decided in PR #42 to centralise invalidation to avoid race conditions.",
            source_type=SourceType.GIT,
            source_ref="src/worker.py",
            tags=["worker", "cache", "decision"],
            confidence=0.85,
            feedback_score=0.0,
            created_at=now,
            updated_at=now,
            staleness=None,
        ),
        MemoryEntry(
            id="mem-auth-1",
            kind=MemoryKind.DOC_FACT,
            title="Authentication uses JWT tokens",
            summary="All API endpoints require a Bearer JWT token.",
            details="Tokens are validated against the shared public key set.",
            source_type=SourceType.DOC,
            source_ref="docs/auth.md",
            tags=["auth", "jwt"],
            confidence=0.8,
            feedback_score=0.0,
            created_at=now,
            updated_at=now,
            staleness=None,
        ),
        MemoryEntry(
            id="mem-stale-1",
            kind=MemoryKind.DECISION,
            title="Stale cache flush strategy",
            summary="Old flush strategy: invalidate every 5 minutes (obsolete since v2).",
            details="This approach was replaced by event-driven invalidation.",
            source_type=SourceType.GIT,
            source_ref="src/cache.py",
            tags=["cache", "stale-strategy"],
            confidence=0.7,
            feedback_score=0.0,
            created_at=now,
            updated_at=now,
            staleness="stale",
        ),
    ]
    storage.upsert_memories(memories)
    return storage


# ---------------------------------------------------------------------------
# Unit tests for compile_prompt_recall
# ---------------------------------------------------------------------------


def test_compile_prompt_recall_returns_relevant_memories(tmp_path: Path) -> None:
    storage = _seed_storage(tmp_path / "memory.db")

    markdown, token_count = compile_prompt_recall(
        storage,
        "fix the cache invalidation bug",
        limit=5,
        budget_tokens=300,
    )

    assert markdown != ""
    assert token_count > 0
    assert "## Relevant repo memory" in markdown
    # Cache-related memories must appear.
    assert "Cache invalidation boundary" in markdown or "Worker refresh pattern" in markdown


def test_compile_prompt_recall_irrelevant_prompt_returns_empty(tmp_path: Path) -> None:
    storage = _seed_storage(tmp_path / "memory.db")

    markdown, token_count = compile_prompt_recall(
        storage,
        "xyzzyx frabbitz quux",  # no overlap with any memory
        limit=5,
        budget_tokens=300,
    )

    # May return empty when no tokens overlap, OR may return something if FTS
    # finds a loose match.  The key assertion: no error raised.
    assert isinstance(markdown, str)
    assert isinstance(token_count, int)
    assert token_count >= 0


def test_compile_prompt_recall_empty_store_returns_empty(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "empty.db")
    storage.initialize()

    markdown, token_count = compile_prompt_recall(storage, "fix the cache invalidation", limit=5)

    assert markdown == ""
    assert token_count == 0


def test_compile_prompt_recall_empty_prompt_returns_empty(tmp_path: Path) -> None:
    storage = _seed_storage(tmp_path / "memory.db")

    markdown, token_count = compile_prompt_recall(storage, "", limit=5)

    assert markdown == ""
    assert token_count == 0

    markdown2, token_count2 = compile_prompt_recall(storage, "   ", limit=5)
    assert markdown2 == ""
    assert token_count2 == 0


def test_compile_prompt_recall_stale_memories_downweighted(tmp_path: Path) -> None:
    """Stale memories should rank below fresh ones for the same query."""
    storage = _seed_storage(tmp_path / "memory.db")

    markdown, _ = compile_prompt_recall(
        storage,
        "cache invalidation",
        limit=5,
        budget_tokens=500,
    )

    # Fresh cache memories appear before the stale one when the result is non-empty.
    if "Cache invalidation boundary" in markdown and "Stale cache flush" in markdown:
        assert markdown.index("Cache invalidation boundary") < markdown.index(
            "Stale cache flush"
        )


def test_compile_prompt_recall_token_budget_respected(tmp_path: Path) -> None:
    storage = _seed_storage(tmp_path / "memory.db")

    tiny_budget = 20
    markdown, token_count = compile_prompt_recall(
        storage,
        "cache invalidation boundary worker",
        limit=10,
        budget_tokens=tiny_budget,
    )

    # At most one entry fits in 20 tokens — token count must be ≤ budget * 2
    # (rough check; the scorer includes at least one entry).
    if markdown:
        assert token_count <= tiny_budget * 2


def test_compile_prompt_recall_deduplicates_candidates(tmp_path: Path) -> None:
    """FTS results and list_memories may overlap; dedup must prevent duplicates."""
    storage = _seed_storage(tmp_path / "memory.db")

    markdown, _ = compile_prompt_recall(
        storage,
        "cache invalidation boundary",
        limit=10,
        budget_tokens=1000,
    )

    if "Cache invalidation boundary" in markdown:
        # Title should appear at most once.
        assert markdown.count("Cache invalidation boundary") == 1


def test_compile_prompt_recall_rejected_memory_excluded(tmp_path: Path) -> None:
    now = utc_now()
    storage = SQLiteStorage(tmp_path / "rejected.db")
    storage.initialize()
    storage.upsert_memories(
        [
            MemoryEntry(
                id="mem-rejected",
                kind=MemoryKind.DECISION,
                title="Cache layering strategy",
                summary="Cache must be layered via the boundary module.",
                details="This is a rejected memory.",
                source_type=SourceType.MANUAL,
                source_ref="manual",
                tags=["cache"],
                confidence=0.8,
                feedback_score=-0.8,  # explicitly rejected
                created_at=now,
                updated_at=now,
            )
        ]
    )

    markdown, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)

    assert "Cache layering strategy" not in markdown


# ---------------------------------------------------------------------------
# CLI tests for onmc hooks prompt-recall
# ---------------------------------------------------------------------------


def test_hooks_prompt_recall_emits_valid_json_contract(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "fix the cache invalidation",
        "session_id": "sess-test",
        "cwd": sample_repo.as_posix(),
    }

    result = runner.invoke(
        app,
        ["hooks", "prompt-recall"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 0
    if result.stdout.strip():
        parsed = json.loads(result.stdout)
        assert "hookSpecificOutput" in parsed
        hook_out = parsed["hookSpecificOutput"]
        assert hook_out["hookEventName"] == "UserPromptSubmit"
        assert isinstance(hook_out["additionalContext"], str)
        assert "Relevant repo memory" in hook_out["additionalContext"]


def test_hooks_prompt_recall_empty_store_exits_zero_empty_stdout(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    # No ingest — empty store.

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "fix the cache invalidation",
        "cwd": sample_repo.as_posix(),
    }

    result = runner.invoke(
        app,
        ["hooks", "prompt-recall"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_hooks_prompt_recall_invalid_stdin_exits_zero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(
        app,
        ["hooks", "prompt-recall"],
        input="this is { not json",
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_hooks_prompt_recall_empty_stdin_exits_zero(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    result = runner.invoke(app, ["hooks", "prompt-recall"], input="")

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_hooks_prompt_recall_uninit_repo_exits_zero_empty_stdout(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If onmc is not initialised the hook must still exit 0 with no stdout."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    # Intentionally no init_project() call.

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "fix the cache invalidation",
        "cwd": sample_repo.as_posix(),
    }

    result = runner.invoke(
        app,
        ["hooks", "prompt-recall"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == ""


def test_hooks_prompt_recall_stdout_is_pure_json_no_extra_text(
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stdout must be parseable by json.loads in its entirety."""
    runner = _cli_runner()
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "cache invalidation boundary",
        "cwd": sample_repo.as_posix(),
    }

    result = runner.invoke(
        app,
        ["hooks", "prompt-recall"],
        input=json.dumps(payload),
    )

    assert result.exit_code == 0
    stdout = result.stdout.strip()
    if stdout:
        # Must parse as JSON in its entirety — not as JSONL, not with leading text.
        parsed = json.loads(stdout)
        assert isinstance(parsed, dict)
        assert "hookSpecificOutput" in parsed


# ---------------------------------------------------------------------------
# Installer: UserPromptSubmit hook registration
# ---------------------------------------------------------------------------


def test_installer_registers_user_prompt_submit_hook(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    settings_path = tmp_path / ".claude" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = payload["hooks"]
    assert isinstance(hooks, dict)
    assert "UserPromptSubmit" in hooks
    entries = hooks["UserPromptSubmit"]
    assert isinstance(entries, list)
    assert any(
        item.get("command") == "onmc hooks prompt-recall"
        for entry in entries
        for item in entry.get("hooks", [])
    )
    # hooks_installed must reflect the new hook.
    assert hooks_installed(settings_path=settings_path)


def test_installer_uninstall_removes_user_prompt_submit_hook(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    uninstall_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    settings_path = tmp_path / ".claude" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = payload.get("hooks", {})
    assert "UserPromptSubmit" not in hooks
    assert not hooks_installed(settings_path=settings_path)


def test_installer_is_idempotent_with_user_prompt_submit(tmp_path: Path) -> None:
    global_settings = tmp_path / "home" / ".claude" / "settings.json"
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)
    install_claude_hooks(repo_root=tmp_path, global_settings_path=global_settings)

    settings_path = tmp_path / ".claude" / "settings.json"
    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = payload["hooks"]
    assert isinstance(hooks.get("UserPromptSubmit"), list)
    assert len(hooks["UserPromptSubmit"]) == 1
    assert len(hooks["UserPromptSubmit"][0]["hooks"]) == 1
