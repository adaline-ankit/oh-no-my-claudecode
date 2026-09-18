"""Real SQLite/Git tests for adaptive context authority and freshness."""

from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import PromotionState
from oh_no_my_claudecode.models.memory_edge import EdgeType, MemoryEdge
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.working_context import store
from oh_no_my_claudecode.working_context.engine import WorkingContext
from oh_no_my_claudecode.working_context.models import ContextPacket


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkingContext:
    monkeypatch.setenv("ONMC_LEARNING", "1")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "cache.py").write_text("TTL = 30\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "add", "cache.py")
    git(repo, "commit", "-qm", "Initial source")
    storage = SQLiteStorage(repo / ".onmc" / "memory.sqlite3")
    storage.initialize()
    return WorkingContext(repo, storage)


def memory(engine: WorkingContext, id: str = "ttl", **overrides: object) -> MemoryEntry:
    now = utc_now()
    values: dict[str, object] = {
        "id": id,
        "kind": MemoryKind.DOC_FACT,
        "title": "Cache expiration",
        "summary": "TTL is 30 seconds",
        "details": "",
        "source_type": SourceType.CODE,
        "source_ref": "cache.py",
        "confidence": 0.9,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    entry = MemoryEntry.model_validate(values)
    engine.storage.upsert_memories([entry])
    return entry


def reasons(packet: ContextPacket) -> dict[str, str]:
    return {item.id: item.reason for item in packet.excluded}


def test_goal_constraints_and_notes_survive_reload_and_compaction(engine: WorkingContext) -> None:
    engine.configure(enabled=True, constraints=["Preserve public API", "No new dependencies"])
    engine.start("alice", "Fix cache expiration")
    engine.start("bob", "Improve logging", constraints=["Keep log schema"])
    engine.note("alice", "decision", "Keep existing TTL semantics")
    first = engine.context("alice", focus="Add regression test", files=["cache.py"])
    restored = WorkingContext(engine.repo_root, engine.storage)
    assert restored.context("alice").injection == ""
    compact = restored.context("alice", force=True)
    assert compact.markdown == first.markdown
    assert compact.injection and not compact.changed
    assert "Preserve public API" in compact.markdown
    assert "Fix cache expiration" in compact.markdown
    assert "Add regression test" in compact.markdown
    assert "Keep existing TTL semantics" not in restored.context("bob").markdown
    with pytest.raises(ValueError, match="Session exists"):
        restored.start("alice", "Quietly overwrite goal")
    assert (
        restored.start("alice", "Explicit replacement", replace=True).goal == "Explicit replacement"
    )


def test_dirty_edit_with_identical_mtime_withdraws_memory(engine: WorkingContext) -> None:
    memory(engine)
    engine.start("s", "Fix cache expiration")
    assert [item.id for item in engine.context("s").selected] == ["ttl"]
    path = engine.repo_root / "cache.py"
    stat = path.stat()
    path.write_text("TTL = 60\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = engine.context("s")
    assert not changed.selected
    assert reasons(changed)["ttl"] == "source_changed"
    assert changed.withdrawn == ["ttl"]
    assert "TTL is 30 seconds" not in changed.markdown
    assert "source_changed" in changed.markdown
    assert engine.context("s").injection == ""
    engine.verify_memory("ttl")
    acknowledged = engine.context("s")
    assert acknowledged.selected[0].freshness == "acknowledged"
    assert not acknowledged.withdrawn


def test_initial_dirty_or_untracked_source_requires_acknowledgement(engine: WorkingContext) -> None:
    (engine.repo_root / "cache.py").write_text("TTL = 90\n")
    memory(engine)
    engine.start("s", "Cache expiration")
    assert reasons(engine.context("s"))["ttl"] == "source_unverified"
    engine.verify_memory("ttl")
    assert engine.context("s").selected
    (engine.repo_root / "new.py").write_text("NEW = True\n")
    memory(engine, "new", source_ref="new.py")
    assert reasons(engine.context("s"))["new"] == "source_unverified"


def test_acknowledgement_cannot_survive_memory_rewrite(engine: WorkingContext) -> None:
    (engine.repo_root / "cache.py").write_text("TTL = 90\n")
    entry = memory(engine)
    engine.verify_memory("ttl")
    engine.start("s", "Cache expiration")
    assert engine.context("s").selected
    engine.storage.upsert_memories([entry.model_copy(update={"summary": "TTL is one hour"})])
    assert reasons(engine.context("s"))["ttl"] == "source_unverified"


def test_deleted_and_unsafe_sources_never_enter_context(
    engine: WorkingContext, tmp_path: Path
) -> None:
    memory(engine)
    memory(engine, "outside", source_ref="../secret.py")
    memory(engine, "metadata", source_ref=".git/config.txt")
    external = tmp_path / "secret.py"
    external.write_text("secret\n")
    link = engine.repo_root / "link.py"
    try:
        link.symlink_to(external)
    except OSError:
        pytest.skip("Symlinks unavailable")
    memory(engine, "symlink", source_ref="link.py")
    engine.start("s", "Cache expiration")
    (engine.repo_root / "cache.py").unlink()
    packet = engine.context("s")
    assert not packet.selected
    assert set(reasons(packet)) == {"ttl", "outside", "metadata", "symlink"}
    assert all(reason.startswith("source_unavailable:") for reason in reasons(packet).values())


def test_promotion_and_learning_gates_apply_to_every_packet(
    engine: WorkingContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory(engine)
    memory(engine, "unpromoted", promotion_state=PromotionState.QUARANTINED)
    engine.start("s", "Cache expiration")
    first = engine.context("s")
    assert reasons(first)["unpromoted"] == "quarantined"
    assert [item.id for item in first.selected] == ["ttl"]
    with pytest.raises(ValueError, match="no file anchors"):
        engine.verify_memory("unpromoted")
    monkeypatch.setenv("ONMC_LEARNING", "0")
    disabled = engine.context("s")
    assert not disabled.selected
    assert disabled.withdrawn == ["ttl"]
    assert any("Learning disabled" in warning for warning in disabled.warnings)


def test_budget_keeps_whole_constraints_and_bounds_unicode_output(engine: WorkingContext) -> None:
    engine.configure(enabled=True, budget_chars=1000, constraints=["Never change public API"])
    engine.start("s", "Cache expiration")
    memory(engine, summary="缓存" * 1500)
    engine.note("s", "hypothesis", "A" * 2000)
    packet = engine.context("s")
    assert len(packet.markdown) == packet.used_chars <= 1000
    assert "Never change public API" in packet.markdown
    assert reasons(packet)["ttl"] == "budget"
    assert "缓存" not in packet.markdown
    assert any("notes omitted" in warning for warning in packet.warnings)
    with pytest.raises(ValueError, match="exceed budget"):
        engine.start("oversized", "Task", constraints=["Do not " + "x" * 850])
    assert engine.session("oversized") is None


def test_conflict_and_supersession_use_explicit_trusted_edges(engine: WorkingContext) -> None:
    memory(engine, "old")
    memory(engine, "new", summary="Cache expiration now 60 seconds")
    engine.storage.upsert_memory_edge(
        MemoryEdge(
            id="edge",
            from_memory_id="new",
            to_memory_id="old",
            edge_type=EdgeType.SUPERSEDES,
            created_at=utc_now(),
        )
    )
    engine.start("s", "Cache expiration")
    packet = engine.context("s")
    assert [item.id for item in packet.selected] == ["new"]
    assert reasons(packet)["old"] == "superseded_by:new"
    engine.storage.upsert_memory_edge(
        MemoryEdge(
            id="edge",
            from_memory_id="new",
            to_memory_id="old",
            edge_type=EdgeType.CONTRADICTS,
            created_at=utc_now(),
        )
    )
    packet = engine.context("s")
    assert not packet.selected
    assert reasons(packet)["new"] == "conflicts_with:old"
    assert packet.withdrawn == ["new"]


def test_quarantined_memory_cannot_supersede_trusted_memory(engine: WorkingContext) -> None:
    memory(engine, "old")
    memory(engine, "new", promotion_state=PromotionState.QUARANTINED)
    engine.storage.upsert_memory_edge(
        MemoryEdge(
            id="edge",
            from_memory_id="new",
            to_memory_id="old",
            edge_type=EdgeType.SUPERSEDES,
            created_at=utc_now(),
        )
    )
    engine.start("s", "Cache expiration")
    assert [item.id for item in engine.context("s").selected] == ["old"]


def test_note_evidence_and_next_step_updates(engine: WorkingContext) -> None:
    engine.start("s", "Cache expiration")
    engine.note("s", "hypothesis", "Cache causes timeout", files=["cache.py"])
    engine.note("s", "next_step", "Write regression")
    engine.note("s", "next_step", "Run regression")
    first = engine.context("s")
    assert "unverified hypothesis" in first.markdown
    assert "Write regression" not in first.markdown
    assert "Run regression" in first.markdown
    (engine.repo_root / "cache.py").write_text("TTL = 90\n")
    second = engine.context("s")
    assert "Cache causes timeout" not in second.markdown
    assert "SOURCE CHANGED" in second.markdown


def test_parallel_notes_do_not_lose_updates(engine: WorkingContext) -> None:
    engine.start("s", "Cache expiration")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: engine.note("s", "decision", f"Choice {i}"), range(16)))
    session = engine.session("s")
    assert session is not None
    assert len(session.notes) == 16
    assert {note.text for note in session.notes} == {f"Choice {i}" for i in range(16)}
    count = session.revision
    engine.note("s", "decision", "Choice 0")
    assert engine.session("s").revision == count  # type: ignore[union-attr]


def test_notes_bounded_with_visible_retirement(engine: WorkingContext) -> None:
    engine.start("s", "Cache expiration")
    for i in range(36):
        engine.note("s", "decision", f"Choice {i}")
    session = engine.session("s")
    assert session is not None and len(session.notes) == 32 and session.pruned_notes == 4
    assert any("retired" in warning for warning in engine.context("s").warnings)


def test_preview_does_not_consume_hook_delivery(engine: WorkingContext) -> None:
    memory(engine)
    engine.start("s", "Cache expiration")
    preview = engine.context("s", consume=False)
    assert preview.injection
    assert engine.context("s").injection == preview.injection
    assert not engine.context("s").injection


def test_invalid_updates_rollback_and_corrupt_state_is_not_reset(engine: WorkingContext) -> None:
    engine.start("s", "Cache expiration")
    with pytest.raises(ValueError, match="traversal"):
        engine.context("s", focus="New focus", files=["../other.py"])
    assert engine.session("s").focus == ""  # type: ignore[union-attr]
    engine.storage.set_meta(store.session_key("s"), "{broken}")
    with pytest.raises(ValidationError):
        engine.context("s")
    assert engine.storage.get_meta(store.session_key("s")) == "{broken}"


@pytest.mark.parametrize("session_id", ["", " ", "s" * 257])
def test_invalid_session_ids(engine: WorkingContext, session_id: str) -> None:
    with pytest.raises(ValueError, match="session_id"):
        engine.start(session_id, "Cache expiration")


def test_no_anchor_and_missing_memory_acknowledgement_errors(engine: WorkingContext) -> None:
    memory(engine, source_ref="manual:human")
    with pytest.raises(ValueError, match="no file anchors"):
        engine.verify_memory("ttl")
    with pytest.raises(ValueError, match="not found"):
        engine.verify_memory("absent")
    with pytest.raises(ValueError, match="No working session"):
        engine.context("absent")


def test_multi_anchor_changes_and_hash_limit(engine: WorkingContext) -> None:
    other = engine.repo_root / "other.py"
    other.write_text("OTHER = 1\n")
    git(engine.repo_root, "add", "other.py")
    git(engine.repo_root, "commit", "-qm", "Second anchor")
    memory(engine, source_ref="cache.py|other.py")
    engine.start("s", "Cache expiration")
    assert engine.context("s").selected
    other.write_text("OTHER = 2\n")
    assert reasons(engine.context("s"))["ttl"] == "source_changed"
    other.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    assert "hash limit" in reasons(engine.context("s"))["ttl"]


def test_hash_budget_exhaustion_is_not_reported_as_source_change(engine: WorkingContext) -> None:
    engine.start("s", "Unrelated task")
    for group in range(5):
        files = []
        for index in range(16):
            name = f"source_{group}_{index}.py"
            (engine.repo_root / name).write_text("VALUE = 1\n")
            files.append(name)
        engine.note("s", "decision", f"Choice {group}", files=files)
    packet = engine.context("s")
    assert "SOURCE UNVERIFIED" in packet.markdown
    assert "SOURCE CHANGED" not in packet.markdown


def test_initial_source_check_ignores_assume_unchanged_flag(engine: WorkingContext) -> None:
    git(engine.repo_root, "update-index", "--assume-unchanged", "cache.py")
    (engine.repo_root / "cache.py").write_text("TTL = 90\n")
    memory(engine)
    engine.start("s", "Cache expiration")
    assert reasons(engine.context("s"))["ttl"] == "source_unverified"


def test_context_does_not_load_entire_memory_graph(
    engine: WorkingContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory(engine)

    def fail_full_scan() -> None:
        raise AssertionError("Entire graph was loaded")

    monkeypatch.setattr(engine.storage, "list_memory_edges", fail_full_scan)
    engine.start("s", "Cache expiration")
    assert engine.context("s").selected


@pytest.mark.parametrize("reference", ["cache.py", "cache.py:12", "README.md|cache.py"])
def test_active_file_retrieval_does_not_require_prose_overlap(
    engine: WorkingContext,
    reference: str,
) -> None:
    (engine.repo_root / "README.md").write_text("Docs\n")
    memory(
        engine,
        title="Billing replay",
        summary="Only issue one credit per event",
        source_ref=reference,
    )
    engine.verify_memory("ttl")
    engine.start("s", "Inspect implementation")
    packet = engine.context("s", files=["cache.py"])
    assert [item.id for item in packet.selected] == ["ttl"]
    assert packet.selected[0].reason == "active_file"


@pytest.mark.parametrize(
    ("path", "reference"),
    [
        ("worker", "worker"),
        ("bin/worker", "bin/worker"),
        (".python-version", ".python-version"),
        ("worker", "manual:review|worker"),
        ("worker", "https://example.test/guide.md|worker"),
        ("worker", "worker|https://example.test/guide.md"),
    ],
)
def test_all_file_anchors_are_checked_even_in_mixed_references(
    engine: WorkingContext, path: str, reference: str
) -> None:
    source = engine.repo_root / path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("INITIAL = 1\n")
    memory(engine, source_ref=reference)
    engine.verify_memory("ttl")
    engine.start("s", "Cache expiration")
    assert engine.context("s").selected[0].freshness == "acknowledged"
    source.write_text("INITIAL = 2\n")
    changed = engine.context("s")
    assert not changed.selected
    assert reasons(changed)["ttl"] == "source_changed"
    source.unlink()
    missing = engine.context("s")
    assert not missing.selected
    assert reasons(missing)["ttl"].startswith("source_unavailable:")


@pytest.mark.parametrize(
    "reference", [" cache.py:12 ", "./cache.py", "README.md | cache.py:12"]
)
def test_active_file_lookup_normalizes_reference_tokens(
    engine: WorkingContext, reference: str
) -> None:
    (engine.repo_root / "README.md").write_text("Docs\n")
    memory(engine, title="Billing replay", summary="One credit per event", source_ref=reference)
    engine.verify_memory("ttl")
    engine.start("s", "Inspect implementation")
    packet = engine.context("s", files=["cache.py"])
    assert [item.id for item in packet.selected] == ["ttl"]
    assert packet.selected[0].reason == "active_file"


@pytest.mark.parametrize(
    "reference",
    [
        "manual:review|../secret",
        "https://example.test/guide.md|.git/config",
        "manual:review|.onmc/memory",
        "loop:../secret.py",
    ],
)
def test_mixed_unsafe_references_are_excluded_instead_of_unanchored(
    engine: WorkingContext, reference: str
) -> None:
    memory(engine, source_ref=reference)
    engine.start("s", "Cache expiration")
    packet = engine.context("s")
    assert not packet.selected
    assert reasons(packet)["ttl"].startswith("source_unavailable:")


@pytest.mark.parametrize(
    "reference", ["loop:engine", "manual_seed:setup", "https://example.test/guide.md", "unknown"]
)
def test_non_file_provenance_remains_explicitly_unanchored(
    engine: WorkingContext, reference: str
) -> None:
    memory(engine, source_ref=reference)
    engine.start("s", "Cache expiration")
    assert engine.context("s").selected[0].freshness == "unanchored"
