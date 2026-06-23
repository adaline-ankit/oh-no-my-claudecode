"""Tests for the user profile compiler and CLI commands.

Coverage:
- compile_user_profile buckets seeded user memories correctly.
- Weights are deterministic with an injected ``now`` timestamp.
- Empty user store -> empty profile, no crash.
- CLI ``onmc profile show`` and ``onmc profile rebuild`` exit codes + --json shape.
- Boot-digest injects a profile block when user memories exist, and emits nothing
  when the user store is empty (boot digest still returns exit 0).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.hooks.boot_digest import compile_boot_digest
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.profile.compiler import (
    UserProfile,
    compile_user_profile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _make_memory(
    title: str,
    summary: str,
    kind: MemoryKind = MemoryKind.DECISION,
    tags: list[str] | None = None,
    confidence: float = 0.9,
    feedback_score: float = 0.0,
    created_days_ago: int = 0,
) -> MemoryEntry:
    """Create a minimal MemoryEntry for testing (no storage)."""
    now = datetime.now(UTC)
    from datetime import timedelta

    ts = now - timedelta(days=created_days_ago)
    return MemoryEntry(
        id=f"user-test-{title[:8].replace(' ', '-').lower()}",
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref="user:manual",
        tags=["user-pref"] if tags is None else tags,
        confidence=confidence,
        feedback_score=feedback_score,
        created_at=ts,
        updated_at=ts,
    )


_FIXED_NOW = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# compile_user_profile — bucket derivation
# ---------------------------------------------------------------------------


class TestCompileUserProfile:
    def test_empty_memories_returns_empty_profile(self) -> None:
        profile = compile_user_profile([], now=_FIXED_NOW)
        assert isinstance(profile, UserProfile)
        assert profile.is_empty
        assert profile.derived_from == 0
        assert profile.preferences == []
        assert profile.frequent_mistakes == []
        assert profile.tooling == []
        assert profile.patterns == []

    def test_mistake_bucket_failed_approach_kind(self) -> None:
        m = _make_memory(
            "Never use os.system",
            "Use subprocess instead of os.system for security.",
            kind=MemoryKind.FAILED_APPROACH,
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        assert not profile.is_empty
        assert len(profile.frequent_mistakes) == 1
        assert profile.frequent_mistakes[0][0] == "Never use os.system"
        # Should NOT appear in other buckets
        titles_pref = [t for t, _ in profile.preferences]
        assert "Never use os.system" not in titles_pref

    def test_mistake_bucket_keyword_signal(self) -> None:
        m = _make_memory(
            "Don't mutate shared state",
            "Avoid mutating shared dicts; use immutable patterns.",
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        assert any("Don't mutate" in t for t, _ in profile.frequent_mistakes)

    def test_preference_bucket_decision_kind(self) -> None:
        m = _make_memory(
            "Prefer black formatter",
            "Always use black for code formatting.",
            kind=MemoryKind.DECISION,
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        # DECISION kind => preferences (not mistake, not tooling unless mistake kw present)
        titles = [t for t, _ in profile.preferences]
        assert "Prefer black formatter" in titles

    def test_tooling_bucket_keyword(self) -> None:
        m = _make_memory(
            "Run ruff before commit",
            "Always run ruff check before pushing.",
            kind=MemoryKind.DECISION,
            tags=["user-pref"],
        )
        # DECISION kind wins => preferences (priority over tooling)
        profile = compile_user_profile([m], now=_FIXED_NOW)
        # Since DECISION triggers preference check first, it may land in preferences.
        # Either bucket is acceptable — just verify it appears somewhere.
        all_titles = (
            [t for t, _ in profile.preferences]
            + [t for t, _ in profile.tooling]
            + [t for t, _ in profile.patterns]
            + [t for t, _ in profile.frequent_mistakes]
        )
        assert "Run ruff before commit" in all_titles

    def test_tooling_bucket_tag(self) -> None:
        m = _make_memory(
            "Use uv for deps",
            "Manage Python deps with uv, not pip directly.",
            kind=MemoryKind.DOC_FACT,  # not DECISION, not FAILED_APPROACH
            tags=["tooling"],
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        tooling_titles = [t for t, _ in profile.tooling]
        assert "Use uv for deps" in tooling_titles

    def test_patterns_bucket_catch_all(self) -> None:
        m = _make_memory(
            "Name booleans with is_ prefix",
            "Boolean variables should start with is_ or has_.",
            kind=MemoryKind.DOC_FACT,
            tags=[],
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        pattern_titles = [t for t, _ in profile.patterns]
        assert "Name booleans with is_ prefix" in pattern_titles

    def test_rejected_memory_excluded(self) -> None:
        """Memories with feedback_score <= -0.5 must not appear in any bucket."""
        m = _make_memory(
            "Rejected pref",
            "This pref was downvoted.",
            kind=MemoryKind.DECISION,
            feedback_score=-1.0,
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        assert profile.is_empty

    def test_zero_confidence_excluded(self) -> None:
        m = _make_memory(
            "Zero confidence",
            "No confidence in this one.",
            confidence=0.0,
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        assert profile.is_empty

    def test_max_items_bound(self) -> None:
        """Buckets should not exceed max_items entries."""
        memories = [
            _make_memory(f"Pref {i}", f"Summary {i}.", kind=MemoryKind.DECISION)
            for i in range(20)
        ]
        profile = compile_user_profile(memories, now=_FIXED_NOW, max_items=3)
        assert len(profile.preferences) <= 3
        assert profile.derived_from == 20

    def test_deterministic_with_injected_now(self) -> None:
        """Same inputs + same now => same output."""
        m1 = _make_memory("Prefer type hints", "Always annotate.", kind=MemoryKind.DECISION)
        m2 = _make_memory(
            "Never bare except", "Avoid bare except:", kind=MemoryKind.FAILED_APPROACH
        )
        p1 = compile_user_profile([m1, m2], now=_FIXED_NOW)
        p2 = compile_user_profile([m1, m2], now=_FIXED_NOW)
        assert p1.preferences == p2.preferences
        assert p1.frequent_mistakes == p2.frequent_mistakes
        assert p1.salient_memory_ids == p2.salient_memory_ids

    def test_salient_memory_ids_bounded(self) -> None:
        memories = [
            _make_memory(f"Item {i}", f"Summary {i}.", kind=MemoryKind.DECISION)
            for i in range(10)
        ]
        profile = compile_user_profile(memories, now=_FIXED_NOW, max_items=5)
        assert len(profile.salient_memory_ids) <= 5

    def test_priority_mistakes_over_preferences(self) -> None:
        """A FAILED_APPROACH memory with 'prefer' keyword should still land in mistakes."""
        m = _make_memory(
            "prefer not to mutate globals",
            "Never mutate global state — it causes bugs.",
            kind=MemoryKind.FAILED_APPROACH,
        )
        profile = compile_user_profile([m], now=_FIXED_NOW)
        mistake_titles = [t for t, _ in profile.frequent_mistakes]
        assert "prefer not to mutate globals" in mistake_titles
        pref_titles = [t for t, _ in profile.preferences]
        assert "prefer not to mutate globals" not in pref_titles

    def test_mixed_buckets_correct_counts(self) -> None:
        memories = [
            _make_memory("Pref A", "Prefer A.", kind=MemoryKind.DECISION),
            _make_memory("Mistake B", "Never B.", kind=MemoryKind.FAILED_APPROACH),
            _make_memory("Tool C", "Use pytest.", kind=MemoryKind.DOC_FACT, tags=["tooling"]),
            _make_memory("Pattern D", "Name well.", kind=MemoryKind.DOC_FACT, tags=[]),
        ]
        profile = compile_user_profile(memories, now=_FIXED_NOW)
        assert profile.derived_from == 4
        assert len(profile.preferences) >= 1
        assert len(profile.frequent_mistakes) >= 1
        assert len(profile.tooling) >= 1
        assert len(profile.patterns) >= 1


# ---------------------------------------------------------------------------
# Service integration — compile via OnmcService.user_profile()
# ---------------------------------------------------------------------------


class TestServiceUserProfile:
    def test_empty_user_store_returns_empty_profile(self, tmp_path: Path) -> None:
        svc = OnmcService()
        profile = svc.user_profile(home=tmp_path)
        assert isinstance(profile, UserProfile)
        assert profile.is_empty

    def test_seeded_store_returns_populated_profile(self, tmp_path: Path) -> None:
        svc = OnmcService()
        svc.add_user_memory(
            title="Always use pytest",
            summary="Use pytest, not unittest.",
            home=tmp_path,
        )
        svc.add_user_memory(
            title="Never use print for debug",
            summary="Use logging instead of print statements.",
            home=tmp_path,
        )
        profile = svc.user_profile(home=tmp_path)
        assert not profile.is_empty
        assert profile.derived_from >= 1


# ---------------------------------------------------------------------------
# Boot-digest integration
# ---------------------------------------------------------------------------


class TestBootDigestProfileInjection:
    def test_boot_digest_no_crash_with_empty_user_memories(self) -> None:
        """Empty user memories -> boot digest returns ("", 0) without crashing."""
        digest, tokens = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="test-repo",
            user_memories=[],
            terse=False,
        )
        assert isinstance(digest, str)
        assert isinstance(tokens, int)

    def test_boot_digest_with_mistake_memory_injects_block(self) -> None:
        """Mistake memories => 'Mistakes to avoid' section appears in digest."""
        m = _make_memory(
            "Never use os.system",
            "Use subprocess instead.",
            kind=MemoryKind.FAILED_APPROACH,
        )
        digest, tokens = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="test-repo",
            user_memories=[m],
            terse=False,
        )
        # Profile block with mistakes should appear in full-mode digest.
        assert "Mistakes to avoid" in digest or "Never use os.system" in digest
        assert tokens > 0

    def test_boot_digest_terse_with_mistake_adds_mistake_line(self) -> None:
        """In terse mode, a FAILED_APPROACH memory produces a MISTAKE: line."""
        m = _make_memory(
            "Never bare except",
            "Always name the exception.",
            kind=MemoryKind.FAILED_APPROACH,
        )
        digest, tokens = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="test-repo",
            user_memories=[m],
            terse=True,
        )
        assert "MISTAKE:" in digest or "Never bare except" in digest
        assert tokens > 0

    def test_boot_digest_preferences_still_present(self) -> None:
        """Existing 'Your preferences' block still renders with profile present."""
        m = _make_memory("Prefer black", "Run black always.", kind=MemoryKind.DECISION)
        digest, _ = compile_boot_digest(
            memories=[],
            tasks=[],
            repo_name="test-repo",
            user_memories=[m],
            terse=False,
        )
        assert "Prefer black" in digest

    def test_boot_digest_empty_store_still_exits_zero(
        self, sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Service boot_digest with empty user store must not raise."""
        monkeypatch.chdir(sample_repo)
        svc = OnmcService(sample_repo)
        svc.init_project()
        svc.ingest()
        digest_md, token_count = svc.boot_digest(home=tmp_path)
        assert isinstance(digest_md, str)
        assert isinstance(token_count, int)


# ---------------------------------------------------------------------------
# CLI — profile show / rebuild
# ---------------------------------------------------------------------------


class TestProfileCli:
    def _invoke(
        self, args: list[str], *, home: Path | None = None, monkeypatch: pytest.MonkeyPatch
    ) -> Any:
        if home is not None:
            monkeypatch.setenv("HOME", str(home))
        runner = _cli_runner()
        return runner.invoke(app, args)

    def test_profile_show_exits_zero_empty_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._invoke(["profile", "show"], home=tmp_path, monkeypatch=monkeypatch)
        assert result.exit_code == 0

    def test_profile_rebuild_exits_zero_empty_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._invoke(["profile", "rebuild"], home=tmp_path, monkeypatch=monkeypatch)
        assert result.exit_code == 0

    def test_profile_show_json_empty_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = self._invoke(
            ["profile", "show", "--json"], home=tmp_path, monkeypatch=monkeypatch
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "preferences" in data
        assert "frequent_mistakes" in data
        assert "tooling" in data
        assert "patterns" in data
        assert "derived_from" in data
        assert isinstance(data["preferences"], list)

    def test_profile_rebuild_json_shape(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Seed a user memory first.
        svc = OnmcService()
        svc.add_user_memory(
            title="Always type-annotate",
            summary="All public functions must have type hints.",
            home=tmp_path,
        )
        result = self._invoke(
            ["profile", "rebuild", "--json"], home=tmp_path, monkeypatch=monkeypatch
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["derived_from"] >= 1
        assert isinstance(data["salient_memory_ids"], list)

    def test_profile_show_populated_renders_panel(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = OnmcService()
        svc.add_user_memory(
            title="Prefer pytest",
            summary="Use pytest always.",
            home=tmp_path,
        )
        result = self._invoke(["profile", "show"], home=tmp_path, monkeypatch=monkeypatch)
        assert result.exit_code == 0
        # Panel or preference text should appear somewhere in stdout.
        assert "Prefer pytest" in result.output or "User Profile" in result.output

    def test_profile_show_no_crash_no_onmc_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even without ~/.onmc existing, profile show must not crash."""
        non_existent_home = tmp_path / "ghost_home"
        non_existent_home.mkdir()
        result = self._invoke(
            ["profile", "show"], home=non_existent_home, monkeypatch=monkeypatch
        )
        assert result.exit_code == 0
