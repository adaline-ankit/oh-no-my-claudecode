"""Tests for ``onmc ask`` — natural-language query over the repo memory brain.

Coverage:
- compile_ask offline (no provider): returns ranked+cited entries, answer=None,
  used_synthesis=False.
- compile_ask with a stub provider: answer populated, used_synthesis=True.
- compile_ask with a provider that raises: answer=None, entries still returned,
  no exception propagated.
- compile_ask with empty question: empty result, no crash.
- CLI ``onmc ask``: exit code 0, basic output.
- CLI ``onmc ask --json``: JSON shape.
- CLI ``onmc ask --no-synth``: used_synthesis=False even if provider configured.
- CLI uninitialised repo: exit code != 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.ask.compiler import AskResult, compile_ask
from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.llm.base import BaseLLMProvider, LLMProviderError
from oh_no_my_claudecode.models import MemoryKind, SourceType
from oh_no_my_claudecode.models.llm import (
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMProviderType,
    LLMSettings,
)
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.text import stable_id
from oh_no_my_claudecode.utils.time import utc_now

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cli_runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _init_storage(db_path: Path) -> SQLiteStorage:
    storage = SQLiteStorage(db_path)
    storage.initialize()
    return storage


def _seed_memory(
    storage: SQLiteStorage,
    *,
    title: str,
    summary: str,
    kind: MemoryKind = MemoryKind.DECISION,
    tags: list[str] | None = None,
) -> str:
    """Seed a single memory entry and return its id."""
    now = utc_now()
    entry_id = stable_id(kind.value, title, summary, "test:ask", prefix="ask-test")
    from oh_no_my_claudecode.models.memory import MemoryEntry

    entry = MemoryEntry(
        id=entry_id,
        kind=kind,
        title=title,
        summary=summary,
        details=summary,
        source_type=SourceType.MANUAL,
        source_ref="test:ask",
        tags=tags or [kind.value],
        confidence=0.85,
        created_at=now,
        updated_at=now,
    )
    storage.upsert_memories([entry])
    return entry_id


# ---------------------------------------------------------------------------
# Stub providers
# ---------------------------------------------------------------------------


class _FixedProvider(BaseLLMProvider):
    """Provider that always returns a fixed answer string."""

    def __init__(self, answer: str) -> None:
        super().__init__(LLMSettings(provider=LLMProviderType.MOCK, model="stub"))
        self._answer = answer

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        return LLMGenerationResponse(
            provider=LLMProviderType.MOCK,
            model="stub",
            text=self._answer,
            raw={},
        )


class _RaisingProvider(BaseLLMProvider):
    """Provider that always raises LLMProviderError."""

    def __init__(self) -> None:
        super().__init__(LLMSettings(provider=LLMProviderType.MOCK, model="stub"))

    def generate(self, request: LLMGenerationRequest) -> LLMGenerationResponse:
        msg = "Simulated provider failure"
        raise LLMProviderError(msg)


# ---------------------------------------------------------------------------
# Unit tests: compile_ask
# ---------------------------------------------------------------------------


def test_compile_ask_offline_no_provider(tmp_path: Path) -> None:
    """Without a provider, entries are returned with answer=None and used_synthesis=False."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    result = compile_ask(
        storage,
        tmp_path,
        "why do we avoid bypassing the cache boundary",
        limit=5,
        provider=None,
    )

    assert isinstance(result, AskResult)
    assert result.answer is None
    assert result.used_synthesis is False
    # At least one entry should match "cache boundary" tokens
    assert len(result.entries) >= 1
    # Citation must be present (source_type + source_ref)
    for entry in result.entries:
        assert isinstance(entry.citation, str)


def test_compile_ask_with_stub_provider_answer_populated(tmp_path: Path) -> None:
    """With a working provider, answer is populated and used_synthesis=True."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    expected_answer = "The cache boundary must not be bypassed (mem-id)."
    provider = _FixedProvider(expected_answer)

    result = compile_ask(
        storage,
        tmp_path,
        "why do we avoid bypassing the cache boundary",
        limit=5,
        provider=provider,
    )

    assert result.used_synthesis is True
    assert result.answer == expected_answer
    assert len(result.entries) >= 1


def test_compile_ask_raising_provider_returns_entries_no_exception(tmp_path: Path) -> None:
    """A provider that raises must not propagate the exception; entries still returned."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    provider = _RaisingProvider()

    # Must not raise
    result = compile_ask(
        storage,
        tmp_path,
        "why do we avoid bypassing the cache boundary",
        limit=5,
        provider=provider,
    )

    assert result.answer is None
    assert result.used_synthesis is False
    assert len(result.entries) >= 1  # entries still returned


def test_compile_ask_empty_question_returns_empty(tmp_path: Path) -> None:
    """An empty question returns an empty AskResult without crashing."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
    )

    result = compile_ask(storage, tmp_path, "", limit=5, provider=None)

    assert isinstance(result, AskResult)
    assert result.entries == []
    assert result.answer is None
    assert result.used_synthesis is False


def test_compile_ask_no_matching_memories_returns_hint(tmp_path: Path) -> None:
    """When no memories match the question, no_data_hint is set."""
    storage = _init_storage(tmp_path / "memory.db")

    result = compile_ask(
        storage,
        tmp_path,
        "something completely unrelated xyzzy frobnicator",
        limit=5,
        provider=None,
    )

    assert result.entries == []
    assert result.no_data_hint != ""


def test_compile_ask_entries_have_citations(tmp_path: Path) -> None:
    """Every returned entry must carry a non-empty citation string."""
    storage = _init_storage(tmp_path / "memory.db")
    _seed_memory(
        storage,
        title="Auth decision",
        summary="Use JWT tokens for stateless auth across services.",
        kind=MemoryKind.DECISION,
        tags=["auth", "jwt", "token", "stateless", "decision"],
    )

    result = compile_ask(
        storage,
        tmp_path,
        "what is the auth token decision",
        limit=5,
        provider=None,
    )

    assert len(result.entries) >= 1
    for entry in result.entries:
        # citation is built from source_type + source_ref
        assert entry.citation, f"Expected non-empty citation for entry {entry.memory_id}"


# ---------------------------------------------------------------------------
# CLI tests: onmc ask
# ---------------------------------------------------------------------------


def test_cli_ask_exits_zero(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """onmc ask returns exit code 0 with a seeded memory."""
    from oh_no_my_claudecode.core.service import OnmcService

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, _, storage = service._load_context()
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    runner = _cli_runner()
    result = runner.invoke(app, ["ask", "why do we avoid bypassing the cache boundary"])

    assert result.exit_code == 0


def test_cli_ask_json_shape(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc ask --json`` emits a JSON object with expected keys."""
    from oh_no_my_claudecode.core.service import OnmcService

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, _, storage = service._load_context()
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    runner = _cli_runner()
    result = runner.invoke(app, ["ask", "--json", "cache boundary"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert "question" in parsed
    assert "entries" in parsed
    assert "answer" in parsed
    assert "used_synthesis" in parsed


def test_cli_ask_no_synth_forces_offline(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--no-synth`` keeps used_synthesis=False and answer=None in JSON output."""
    from oh_no_my_claudecode.core.service import OnmcService

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()

    _, _, storage = service._load_context()
    _seed_memory(
        storage,
        title="Cache boundary invariant",
        summary="Do not bypass the shared cache boundary from worker flows.",
        kind=MemoryKind.INVARIANT,
        tags=["cache", "boundary", "invariant", "worker"],
    )

    runner = _cli_runner()
    result = runner.invoke(app, ["ask", "--no-synth", "--json", "cache boundary"])

    assert result.exit_code == 0
    parsed = json.loads(result.stdout)
    assert parsed["used_synthesis"] is False
    assert parsed["answer"] is None


def test_cli_ask_uninit_repo_exits_nonzero(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onmc ask exits non-zero when the repo is not initialised."""
    monkeypatch.chdir(sample_repo)
    # Deliberately no init_project() call.

    runner = _cli_runner()
    result = runner.invoke(app, ["ask", "what is the auth decision"])

    assert result.exit_code != 0


def test_cli_ask_no_matches_exits_zero(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """onmc ask exits 0 even when no memories match the question."""
    from oh_no_my_claudecode.core.service import OnmcService

    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    # Empty store — no memories seeded.

    runner = _cli_runner()
    result = runner.invoke(app, ["ask", "xyzzy frabbitz quux unrelated"])

    assert result.exit_code == 0
