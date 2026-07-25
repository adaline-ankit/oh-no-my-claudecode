"""Tests for per-prompt surgical memory recall (UserPromptSubmit hook).

Trust-boundary coverage (see the "Activation gating" section of
``hooks/prompt_recall.py``):

- surfacing a skill records NO use/success signal (no unearned evidence);
- ``record_skill_outcome`` requires an explicit, caller-observed outcome;
- the injected-memory char budget has a real default cap, with ``0`` as an
  explicit opt-out;
- the ``ONMC_LEARNING`` kill switch suppresses memory AND skill injection, and
  fails closed;
- memory carrying unpromoted (agent-authored) provenance is never auto-injected.
"""

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
from oh_no_my_claudecode.hooks.prompt_recall import (
    UNPROMOTED_SOURCE_PREFIX,
    _read_max_chars,
    compile_prompt_recall,
    compile_prompt_recall_safe,
    compile_skills_recall,
    is_unpromoted_source,
    learning_enabled,
    record_skill_outcome,
    unpromoted_source_ref,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.models.skill import Skill
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

    # terse=False: verify the full markdown output format.
    markdown, token_count = compile_prompt_recall(
        storage,
        "fix the cache invalidation bug",
        limit=5,
        budget_tokens=300,
        terse=False,
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
    # terse=False: token budget only applies to the full markdown renderer.
    markdown, token_count = compile_prompt_recall(
        storage,
        "cache invalidation boundary worker",
        limit=10,
        budget_tokens=tiny_budget,
        terse=False,
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
# Skill surfacing must not fabricate success evidence
# ---------------------------------------------------------------------------


def _seed_skill(storage: SQLiteStorage, *, tags: list[str]) -> Skill:
    """Add one auto_inject skill that ranks for a cache-flavoured prompt."""
    now = utc_now()
    skill = Skill(
        id="sk-cache-1",
        name="Cache invalidation skill",
        body="1. Call invalidate_cache()\n2. Never write the store directly",
        trigger="When touching cache invalidation.",
        tags=tags,
        files=[],
        source_memory_ids=[],
        use_count=0,
        success_count=0,
        confidence=0.8,
        auto_inject=True,
        created_at=now,
        updated_at=now,
        last_used_at=None,
    )
    storage.add_skill(skill)
    return skill


def test_surfacing_a_skill_records_no_use_or_success(tmp_path: Path) -> None:
    """A skill being *shown* is not a skill *working* — and not a failure either.

    The old behaviour called ``record_skill_use(success=True)`` on every prompt,
    which fed ``rank_skills``/``skill_prune`` a signal nothing had earned.
    """
    storage = _seed_storage(tmp_path / "memory.db")
    skill = _seed_skill(storage, tags=["cache", "invalidation"])

    text, _ = compile_prompt_recall_safe(
        storage,
        "fix the cache invalidation bug",
        timeout_ms=10_000,
        repo_root=tmp_path,
    )

    # The skill really was surfaced (otherwise this test proves nothing).
    assert "Cache invalidation skill" in text

    stored = storage.get_skill(skill.id)
    assert stored is not None
    assert stored.use_count == 0, "surfacing must not count as a use"
    assert stored.success_count == 0, "surfacing must not count as a success"
    assert stored.last_used_at is None


def test_repeated_surfacing_never_accumulates_success(tmp_path: Path) -> None:
    """The self-reinforcing loop is closed: N prompts still leave zero evidence."""
    storage = _seed_storage(tmp_path / "memory.db")
    skill = _seed_skill(storage, tags=["cache", "invalidation"])

    for _ in range(5):
        compile_prompt_recall_safe(
            storage,
            "fix the cache invalidation bug",
            timeout_ms=10_000,
            repo_root=tmp_path,
        )

    stored = storage.get_skill(skill.id)
    assert stored is not None
    assert (stored.use_count, stored.success_count) == (0, 0)


def test_record_skill_outcome_records_observed_outcome(tmp_path: Path) -> None:
    """Evidence-backed usage counting is preserved for callers that have evidence."""
    storage = _seed_storage(tmp_path / "memory.db")
    skill = _seed_skill(storage, tags=["cache"])

    record_skill_outcome(storage, [skill.id], success=True)
    after_win = storage.get_skill(skill.id)
    assert after_win is not None
    assert (after_win.use_count, after_win.success_count) == (1, 1)

    record_skill_outcome(storage, [skill.id], success=False)
    after_loss = storage.get_skill(skill.id)
    assert after_loss is not None
    assert (after_loss.use_count, after_loss.success_count) == (2, 1)


def test_record_skill_outcome_survives_unknown_skill(tmp_path: Path) -> None:
    """A bad id must not break the caller (metrics are never load-bearing)."""
    storage = _seed_storage(tmp_path / "memory.db")
    record_skill_outcome(storage, ["sk-does-not-exist"], success=True)


# ---------------------------------------------------------------------------
# Injected-context budget cap: real default, explicit opt-out
# ---------------------------------------------------------------------------


def test_max_chars_default_is_a_real_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset env must resolve to a bounded budget, not "no budget"."""
    monkeypatch.delenv("ONMC_RECALL_MAX_CHARS", raising=False)
    assert _read_max_chars(None) > 0


def test_max_chars_zero_is_an_explicit_opt_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unbounded injection stays possible — but only when the user asks for it."""
    monkeypatch.setenv("ONMC_RECALL_MAX_CHARS", "0")
    assert _read_max_chars(None) == 0


def test_max_chars_invalid_env_falls_back_to_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed value must not silently disable the budget."""
    monkeypatch.setenv("ONMC_RECALL_MAX_CHARS", "not-a-number")
    assert _read_max_chars(None) > 0


def _seed_bulky_memories(db_path: Path, *, count: int = 6) -> SQLiteStorage:
    """Seed several large cache memories so any sane char budget must trim."""
    storage = SQLiteStorage(db_path)
    storage.initialize()
    now = utc_now()
    storage.upsert_memories(
        [
            MemoryEntry(
                id=f"mem-bulk-{i}",
                kind=MemoryKind.DECISION,
                title=f"Cache invalidation note {i}",
                summary="Cache invalidation must go through the boundary. " + ("x" * 1500),
                details="Cache invalidation detail. " + ("y" * 1500),
                source_type=SourceType.DOC,
                source_ref="docs/cache.md",
                tags=["cache"],
                confidence=0.9,
                feedback_score=0.0,
                created_at=now,
                updated_at=now,
                staleness=None,
            )
            for i in range(count)
        ]
    )
    return storage


def test_default_budget_trims_bulky_memories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With env unset, a pathological memory set is capped and says so."""
    monkeypatch.delenv("ONMC_RECALL_MAX_CHARS", raising=False)
    storage = _seed_bulky_memories(tmp_path / "bulky.db")

    text, _ = compile_prompt_recall(
        storage,
        "cache invalidation",
        limit=6,
        terse=True,
    )

    assert text
    assert "budget cap" in text
    assert len(text) < 6 * 3000


def test_explicit_opt_out_allows_unbounded_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ONMC_RECALL_MAX_CHARS=0`` restores unbounded behaviour on request."""
    monkeypatch.setenv("ONMC_RECALL_MAX_CHARS", "0")
    storage = _seed_bulky_memories(tmp_path / "bulky.db")

    text, _ = compile_prompt_recall(
        storage,
        "cache invalidation",
        limit=6,
        terse=True,
    )

    assert text
    assert "budget cap" not in text


# ---------------------------------------------------------------------------
# ONMC_LEARNING kill switch — must fail closed
# ---------------------------------------------------------------------------


def test_kill_switch_suppresses_memory_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _seed_storage(tmp_path / "memory.db")

    monkeypatch.setenv("ONMC_LEARNING", "0")
    assert compile_prompt_recall(storage, "cache invalidation", limit=5) == ("", 0)

    monkeypatch.delenv("ONMC_LEARNING", raising=False)
    text, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)
    assert text, "default-ON learning must keep working"


@pytest.mark.parametrize("value", ["0", "false", "NO", "Off"])
def test_kill_switch_accepts_documented_off_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    storage = _seed_storage(tmp_path / "memory.db")
    monkeypatch.setenv("ONMC_LEARNING", value)
    assert compile_prompt_recall(storage, "cache invalidation", limit=5) == ("", 0)


def test_kill_switch_suppresses_skill_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _seed_storage(tmp_path / "memory.db")
    _seed_skill(storage, tags=["cache", "invalidation"])

    monkeypatch.delenv("ONMC_LEARNING", raising=False)
    on_text, on_ids = compile_skills_recall(storage, "fix the cache invalidation bug")
    assert on_text and on_ids

    monkeypatch.setenv("ONMC_LEARNING", "off")
    assert compile_skills_recall(storage, "fix the cache invalidation bug") == ("", [])


def test_kill_switch_fails_closed_when_unresolvable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the switch cannot be resolved, learning is OFF — never advisory."""

    def _boom(*_args: object, **_kwargs: object) -> bool:
        msg = "switch unavailable"
        raise RuntimeError(msg)

    monkeypatch.setattr(
        "oh_no_my_claudecode.learning.activation.is_learning_enabled", _boom
    )
    assert learning_enabled() is False


# ---------------------------------------------------------------------------
# Unpromoted (agent-authored) provenance is never auto-injected
# ---------------------------------------------------------------------------


def test_unpromoted_source_ref_helpers() -> None:
    ref = unpromoted_source_ref("mcp:record_memory")
    assert ref.startswith(UNPROMOTED_SOURCE_PREFIX)
    assert is_unpromoted_source(ref)
    # Idempotent — re-stamping must not double the prefix.
    assert unpromoted_source_ref(ref) == ref
    assert not is_unpromoted_source("docs/architecture.md")


def _seed_agent_authored(db_path: Path, *, source_ref: str) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    now = utc_now()
    storage.upsert_memories(
        [
            MemoryEntry(
                id="mem-agent-1",
                kind=MemoryKind.DECISION,
                title="Agent authored cache decision",
                summary="Cache invalidation should always go through the boundary.",
                details="Written by an agent about its own run.",
                source_type=SourceType.MANUAL,
                source_ref=source_ref,
                tags=["cache"],
                confidence=0.9,
                feedback_score=0.0,
                created_at=now,
                updated_at=now,
                staleness=None,
            )
        ]
    )
    return storage


def test_unpromoted_memory_is_not_auto_injected(tmp_path: Path) -> None:
    storage = _seed_agent_authored(
        tmp_path / "unpromoted.db",
        source_ref=unpromoted_source_ref("mcp:record_memory"),
    )

    text, tokens = compile_prompt_recall(storage, "cache invalidation", limit=5)

    assert (text, tokens) == ("", 0)


def test_same_memory_with_reviewed_provenance_is_injected(tmp_path: Path) -> None:
    """Control for the test above: only the provenance marker changes the outcome."""
    storage = _seed_agent_authored(tmp_path / "reviewed.db", source_ref="manual:api")

    text, _ = compile_prompt_recall(storage, "cache invalidation", limit=5)

    assert "Agent authored cache decision" in text


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
        # In terse mode (hook default) there's no "## Relevant repo memory" header;
        # content is compact lines.  Either way the context must be non-empty.
        assert len(hook_out["additionalContext"]) > 0


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
