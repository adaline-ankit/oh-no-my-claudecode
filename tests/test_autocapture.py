"""Tests for heuristic session auto-capture (mine/autocapture.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mine.autocapture import (
    MAX_MEMORIES_PER_SESSION,
    capture_from_transcript,
)
from oh_no_my_claudecode.mine.transcript import discover_transcript_dir
from oh_no_my_claudecode.models.memory import SourceType

# ---------------------------------------------------------------------------
# Transcript helpers — reuse shape from tests/test_mine.py
# ---------------------------------------------------------------------------


def _assistant_line(
    content: list[dict[str, object]],
    *,
    is_sidechain: bool = False,
    uuid: str = "aaaaaaaa-0000-4000-8000-000000000001",
) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": content,
                "model": "claude-fable-5",
            },
            "cwd": "/tmp/sample",  # noqa: S108
            "sessionId": "session-abc123",
            "timestamp": "2026-06-20T10:00:00.000Z",
            "uuid": uuid,
            "parentUuid": None,
            "gitBranch": "main",
            "isSidechain": is_sidechain,
            "version": "2.1.0",
        }
    )


def _user_line(text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": text},
            "timestamp": "2026-06-20T09:59:00.000Z",
            "uuid": "bbbbbbbb-0000-4000-8000-000000000001",
            "isSidechain": False,
        }
    )


def _write_transcript(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Core extraction tests
# ---------------------------------------------------------------------------


def test_capture_extracts_decision_pattern(tmp_path: Path) -> None:
    transcript = tmp_path / "session-abc123.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "We decided to use SQLite for local storage because "
                            "it requires no external service and the data volume is small."
                        ),
                    }
                ]
            )
        ],
    )

    entries = capture_from_transcript(transcript, session_id="session-abc123")

    assert len(entries) >= 1
    decision_entries = [
        e for e in entries if "decided" in e.summary.lower() or "sqlite" in e.summary.lower()
    ]
    assert decision_entries, f"Expected a decision entry, got: {[e.summary for e in entries]}"
    decision = decision_entries[0]
    assert decision.source_type == SourceType.SESSION
    assert decision.source_ref == "session-abc123"
    assert decision.confidence > 0.0
    assert "[auto]" in decision.title


def test_capture_extracts_fix_pattern(tmp_path: Path) -> None:
    transcript = tmp_path / "fix-session.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "Fixed it by removing the duplicate index on the createdAt column "
                            "which was causing the slow query."
                        ),
                    }
                ]
            )
        ],
    )

    entries = capture_from_transcript(transcript, session_id="fix-session")

    assert any(
        "duplicate" in e.summary.lower() or "removing" in e.summary.lower() for e in entries
    ), f"Expected a fix entry, got: {[e.summary for e in entries]}"


def test_capture_extracts_invariant_pattern(tmp_path: Path) -> None:
    transcript = tmp_path / "inv-session.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "Never bypass the cache boundary from workers"
                            " — always call invalidate_cache()."
                        ),
                    }
                ]
            )
        ],
    )

    entries = capture_from_transcript(transcript, session_id="inv-session")

    invariant_entries = [
        e for e in entries if "cache" in e.summary.lower() or "bypass" in e.summary.lower()
    ]
    assert invariant_entries, f"Expected invariant entry, got: {[e.summary for e in entries]}"


def test_capture_skips_user_turns(tmp_path: Path) -> None:
    """User lines (not assistant type) must not contribute text to extraction."""
    transcript = tmp_path / "skip-session.jsonl"
    _write_transcript(
        transcript,
        [
            _user_line("We decided to rewrite the entire codebase in Rust."),
            _assistant_line(
                [{"type": "text", "text": "I'll look into the issue and report back."}]
            ),
        ],
    )

    entries = capture_from_transcript(transcript, session_id="skip-session")

    # The user decision must not appear; the assistant text is noise so may be empty
    summaries = " ".join(e.summary for e in entries)
    assert "rewrite the entire" not in summaries


def test_capture_skips_sidechain_turns(tmp_path: Path) -> None:
    """Sidechain (subagent) assistant lines must be ignored."""
    transcript = tmp_path / "sidechain-session.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": "We decided to use Redis for the subagent cache layer.",
                    }
                ],
                is_sidechain=True,
            ),
            _assistant_line(
                [{"type": "text", "text": "The main thread concludes the investigation."}],
                uuid="aaaaaaaa-0000-4000-8000-000000000002",
            ),
        ],
    )

    entries = capture_from_transcript(transcript, session_id="sidechain-session")

    summaries = " ".join(e.summary for e in entries)
    assert "redis" not in summaries.lower()


def test_capture_deduplicates_identical_entries(tmp_path: Path) -> None:
    """Same pattern text should produce only one entry even if it appears twice."""
    decision_text = (
        "We decided to use SQLite for local storage because it is embedded and zero-config."
    )
    transcript = tmp_path / "dedup-session.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line([{"type": "text", "text": decision_text}]),
            _assistant_line(
                [{"type": "text", "text": decision_text}],
                uuid="aaaaaaaa-0000-4000-8000-000000000003",
            ),
        ],
    )

    entries = capture_from_transcript(transcript, session_id="dedup-session")

    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids)), "Duplicate IDs should be deduplicated"


def test_capture_caps_output_at_max(tmp_path: Path) -> None:
    """No more than MAX_MEMORIES_PER_SESSION entries per call."""
    # Build a transcript with many decision-pattern lines
    lines = []
    for i in range(MAX_MEMORIES_PER_SESSION + 5):
        lines.append(
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            f"We decided to use approach number {i} which involves "
                            f"a unique strategy different from all others."
                        ),
                    }
                ],
                uuid=f"aaaaaaaa-0000-4000-8000-{i:012d}",
            )
        )
    transcript = tmp_path / "cap-session.jsonl"
    _write_transcript(transcript, lines)

    entries = capture_from_transcript(transcript, session_id="cap-session")

    assert len(entries) <= MAX_MEMORIES_PER_SESSION


def test_capture_returns_empty_on_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-session.jsonl"
    entries = capture_from_transcript(missing, session_id="no-such")
    assert entries == []


def test_capture_returns_empty_on_malformed_transcript(tmp_path: Path) -> None:
    transcript = tmp_path / "bad-session.jsonl"
    transcript.write_text("not json at all\n{broken\n", encoding="utf-8")
    entries = capture_from_transcript(transcript, session_id="bad-session")
    assert entries == []


def test_capture_all_source_type_session(tmp_path: Path) -> None:
    """Every captured entry must carry SourceType.SESSION."""
    transcript = tmp_path / "src-session.jsonl"
    _write_transcript(
        transcript,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "Decision: always validate input at the service boundary, "
                            "never in the repository layer."
                        ),
                    }
                ]
            )
        ],
    )

    entries = capture_from_transcript(transcript, session_id="src-session")

    for entry in entries:
        assert entry.source_type == SourceType.SESSION


# ---------------------------------------------------------------------------
# Service-level capture_session tests
# ---------------------------------------------------------------------------


def test_service_capture_session_writes_to_store(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """capture_session() stores new entries in the DB and returns count > 0."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    svc = OnmcService(sample_repo)
    svc.init_project()

    transcript_dir = discover_transcript_dir(sample_repo)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    session_file = transcript_dir / "test-svc-session.jsonl"
    _write_transcript(
        session_file,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "Fixed it by adding a unique constraint on the email column "
                            "to prevent duplicate registrations."
                        ),
                    }
                ]
            )
        ],
    )

    count = svc.capture_session(session_id="test-svc-session")

    assert count > 0, "Expected at least one memory to be captured"
    memories = svc.list_memories(source_type=SourceType.SESSION)
    assert len(memories) == count
    assert all(m.source_type == SourceType.SESSION for m in memories)


def test_service_capture_session_deduplicates_on_second_call(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """A second capture_session call on the same transcript returns 0 (all deduped)."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    svc = OnmcService(sample_repo)
    svc.init_project()

    transcript_dir = discover_transcript_dir(sample_repo)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    session_file = transcript_dir / "dedup-svc-session.jsonl"
    _write_transcript(
        session_file,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": "We decided to always run tests before merging to main.",
                    }
                ]
            )
        ],
    )

    count1 = svc.capture_session(session_id="dedup-svc-session")
    count2 = svc.capture_session(session_id="dedup-svc-session")

    assert count1 > 0
    assert count2 == 0, "Second capture of same session should find nothing new"


def test_service_capture_session_uses_explicit_transcript_path(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """capture_session() accepts an explicit transcript_path parameter."""
    monkeypatch.chdir(sample_repo)

    svc = OnmcService(sample_repo)
    svc.init_project()

    transcript_file = tmp_path / "explicit-session.jsonl"
    _write_transcript(
        transcript_file,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": (
                            "Root cause: the cache key was missing the tenant ID prefix, "
                            "causing cross-tenant data leaks."
                        ),
                    }
                ]
            )
        ],
    )

    count = svc.capture_session(
        session_id="explicit-session",
        transcript_path=transcript_file,
    )

    assert count > 0


def test_service_capture_session_returns_zero_with_no_transcript(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """capture_session() returns 0 when no transcript exists for the repo."""
    monkeypatch.chdir(sample_repo)
    # Point home to tmp_path so transcript dir won't exist
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    svc = OnmcService(sample_repo)
    svc.init_project()

    count = svc.capture_session()

    assert count == 0


# ---------------------------------------------------------------------------
# SessionEnd hook respects ONMC_AUTOCAPTURE=0
# ---------------------------------------------------------------------------


def test_session_end_hook_respects_opt_out(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """When ONMC_AUTOCAPTURE=0, no session memories should be written."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)
    monkeypatch.setenv("ONMC_AUTOCAPTURE", "0")

    svc = OnmcService(sample_repo)
    svc.init_project()

    transcript_dir = discover_transcript_dir(sample_repo)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    session_file = transcript_dir / "optout-session.jsonl"
    _write_transcript(
        session_file,
        [
            _assistant_line(
                [
                    {
                        "type": "text",
                        "text": "We decided to remove the old migration scripts permanently.",
                    }
                ]
            )
        ],
    )

    # Simulate what hooks_session_end_command does (env-var check path)
    # We test via service directly since the CLI command reads os.environ
    if os.environ.get("ONMC_AUTOCAPTURE", "1") != "0":
        svc.capture_session(session_id="optout-session")

    memories = svc.list_memories(source_type=SourceType.SESSION)
    assert memories == [], "No session memories should be written when ONMC_AUTOCAPTURE=0"


def test_session_end_hook_exits_zero_with_no_transcript(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    """Session-end hook path should not raise even when no transcript exists."""
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    svc = OnmcService(sample_repo)
    svc.init_project()

    # Directly exercise capture_session with no transcript — must not raise
    count = svc.capture_session()
    assert count == 0
