"""Tests for the ``onmc handoff`` portable task-context bundle.

Covers:
- build_handoff on an empty/constructed repo does not crash and records notes
  for every missing source (all four sources fail-safe).
- injected fake pack/orggraph-memory/guard/receipt sources produce a fully
  populated bundle deterministically given a fixed ``now``.
- write_bundle → read_bundle round-trips every field.
- read_bundle tolerates a partial dict and rejects non-JSON / non-object files.
- render_resume output contains the goal and the dead-ends to avoid.

The four data sources are injected as fakes, so these tests are pure and need no
storage, repo, or network. ``storage``/``repo_root`` are only forwarded to the
fakes, so a trivial sentinel object suffices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.handoff.handoff import (
    BUNDLE_VERSION,
    HandoffBundle,
    build_handoff,
    read_bundle,
    render_resume,
    summarize,
    write_bundle,
)
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.time import utc_now

_NOW = "2026-07-05T00:00:00+00:00"
_SENTINEL_STORAGE: Any = object()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakePack:
    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": "add handoff",
            "reuse_hints": [{"symbol": "build_pack", "location": "pack/builder.py:113"}],
            "context_files": ["src/a.py", "src/b.py"],
        }


class _FakeGuardEntry:
    def __init__(self, title: str, why: str) -> None:
        self.title = title
        self.why_it_failed = why


class _FakeGuardResult:
    def __init__(self, entries: list[_FakeGuardEntry]) -> None:
        self.entries = entries


def _decision_memory(idx: int, title: str) -> MemoryEntry:
    now = utc_now()
    return MemoryEntry(
        id=f"mem-{idx}",
        kind=MemoryKind.DECISION,
        title=title,
        summary=f"summary {idx}",
        details=f"details {idx}",
        source_type=SourceType.DOC,
        source_ref="doc:notes.md",
        tags=[],
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )


def _fake_pack_builder(_storage: Any, _root: Path, _goal: str) -> _FakePack:
    return _FakePack()


def _fake_memory_loader() -> list[MemoryEntry]:
    return [
        _decision_memory(1, "Use handoff bundle for resume"),
        _decision_memory(2, "Store receipts under agent-memory"),
    ]


def _fake_guard_compiler(_storage: Any, _goal: str) -> _FakeGuardResult:
    return _FakeGuardResult(
        [_FakeGuardEntry("Retrying wall-clock in core", "broke determinism")]
    )


def _fake_receipt_loader(_root: Path, n: int) -> list[dict[str, Any]]:
    return [
        {"goal": "prior attempt", "agent": "claude", "verified": True, "stop_reason": "converged"}
    ][:n]


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_build_on_empty_repo_does_not_crash(tmp_path: Path) -> None:
    """Every source failing/empty yields a valid bundle with notes, not a crash."""

    def _raise_pack(_s: Any, _r: Path, _g: str) -> Any:
        raise RuntimeError("no pack")

    def _empty_memories() -> list[MemoryEntry]:
        return []

    def _raise_guard(_s: Any, _g: str) -> Any:
        raise RuntimeError("no guard")

    def _empty_receipts(_r: Path, _n: int) -> list[dict[str, Any]]:
        return []

    bundle = build_handoff(
        _SENTINEL_STORAGE,
        tmp_path,
        "some goal",
        now=_NOW,
        pack_builder=_raise_pack,
        memory_loader=_empty_memories,
        guard_compiler=_raise_guard,
        receipt_loader=_empty_receipts,
    )

    assert bundle.version == BUNDLE_VERSION
    assert bundle.goal == "some goal"
    assert bundle.context_pack == {}
    assert bundle.decisions == []
    assert bundle.dead_ends == []
    assert bundle.recent_receipts == []
    # One note per degraded source.
    joined = " ".join(bundle.notes)
    assert "context pack unavailable" in joined
    assert "no memories stored" in joined
    assert "dead-ends unavailable" in joined
    assert "no recent run receipts" in joined


def test_default_receipt_loader_missing_dir_is_graceful(tmp_path: Path) -> None:
    """The real default receipt loader returns [] when the receipts dir is absent."""
    bundle = build_handoff(
        _SENTINEL_STORAGE,
        tmp_path,
        "goal",
        now=_NOW,
        pack_builder=_fake_pack_builder,
        memory_loader=_fake_memory_loader,
        guard_compiler=_fake_guard_compiler,
        # receipt_loader omitted → exercises the real default loader.
    )
    assert bundle.recent_receipts == []
    assert any("no recent run receipts" in n for n in bundle.notes)


# ---------------------------------------------------------------------------
# Fully populated + deterministic
# ---------------------------------------------------------------------------


def _populated_bundle(tmp_path: Path) -> HandoffBundle:
    return build_handoff(
        _SENTINEL_STORAGE,
        tmp_path,
        "add handoff bundle",
        now=_NOW,
        pack_builder=_fake_pack_builder,
        memory_loader=_fake_memory_loader,
        guard_compiler=_fake_guard_compiler,
        receipt_loader=_fake_receipt_loader,
    )


def test_populated_bundle_has_all_sections(tmp_path: Path) -> None:
    bundle = _populated_bundle(tmp_path)
    assert bundle.created_at == _NOW
    assert bundle.context_pack["context_files"] == ["src/a.py", "src/b.py"]
    assert [d["title"] for d in bundle.decisions] == [
        "Use handoff bundle for resume",
        "Store receipts under agent-memory",
    ]
    assert bundle.dead_ends == ["Retrying wall-clock in core — broke determinism"]
    assert bundle.recent_receipts[0]["goal"] == "prior attempt"


def test_build_is_deterministic(tmp_path: Path) -> None:
    a = _populated_bundle(tmp_path).to_dict()
    b = _populated_bundle(tmp_path).to_dict()
    assert a == b


def test_decisions_ranked_by_goal_overlap(tmp_path: Path) -> None:
    """A decision whose title shares tokens with the goal ranks first."""

    def _loader() -> list[MemoryEntry]:
        return [
            _decision_memory(1, "Unrelated cleanup of logging"),
            _decision_memory(2, "Handoff bundle schema versioning"),
        ]

    bundle = build_handoff(
        _SENTINEL_STORAGE,
        tmp_path,
        "handoff bundle",
        now=_NOW,
        pack_builder=_fake_pack_builder,
        memory_loader=_loader,
        guard_compiler=_fake_guard_compiler,
        receipt_loader=_fake_receipt_loader,
    )
    assert bundle.decisions[0]["title"] == "Handoff bundle schema versioning"
    assert bundle.decisions[0]["relevance"] >= 1


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_write_read_round_trip(tmp_path: Path) -> None:
    bundle = _populated_bundle(tmp_path)
    path = tmp_path / "nested" / "handoff.json"
    written = write_bundle(bundle, path)
    assert written == path
    assert path.is_file()

    restored = read_bundle(path)
    assert restored.to_dict() == bundle.to_dict()


def test_read_bundle_tolerates_partial(tmp_path: Path) -> None:
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"goal": "just a goal"}), encoding="utf-8")
    restored = read_bundle(path)
    assert restored.goal == "just a goal"
    assert restored.version == BUNDLE_VERSION
    assert restored.decisions == []
    assert restored.dead_ends == []


def test_read_bundle_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    try:
        read_bundle(path)
    except ValueError:
        pass
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError for non-object JSON")


def test_read_bundle_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    try:
        read_bundle(path)
    except ValueError:
        pass
    else:  # pragma: no cover - failure path
        raise AssertionError("expected ValueError for invalid JSON")


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class _CaptureConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, text: str = "") -> None:
        self.lines.append(text)


def test_render_resume_contains_goal_and_dead_ends(tmp_path: Path) -> None:
    bundle = _populated_bundle(tmp_path)
    console = _CaptureConsole()
    render_resume(bundle, console)
    out = "\n".join(console.lines)
    assert "add handoff bundle" in out
    assert "DO NOT retry" in out
    assert "Retrying wall-clock in core" in out
    assert "Use handoff bundle for resume" in out
    assert "src/a.py" in out


def test_render_resume_empty_bundle_is_explicit() -> None:
    bundle = HandoffBundle(version=BUNDLE_VERSION, goal="x", created_at=None)
    console = _CaptureConsole()
    render_resume(bundle, console)
    out = "\n".join(console.lines)
    assert "(none recorded)" in out
    assert "(no recent run receipts)" in out


def test_summarize_counts(tmp_path: Path) -> None:
    bundle = _populated_bundle(tmp_path)
    summary = summarize(bundle)
    assert "2 decision(s)" in summary
    assert "1 dead-end(s)" in summary
    assert "2 context file(s)" in summary
    assert "1 recent receipt(s)" in summary
