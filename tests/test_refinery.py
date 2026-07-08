"""Tests for ``onmc refinery`` — Bors-style serialised merge queue.

Coverage (>= 8 tests, all offline)
-----------------------------------
1.  enqueue / order / priority — higher-priority PRs sort to the front.
2.  FIFO within same priority — insertion order wins for equal priorities.
3.  next_action state-machine transitions — every CiStatus → Action mapping.
4.  process merges a green PR via fake gh — success path.
5.  process kicks a failing PR with reason and continues to the next PR.
6.  CodeQL-fail maps to RED → KICK (blocks merge; CiStatus.RED path).
7.  drop removes a PR regardless of state.
8.  clear empties the queue.
9.  determinism — same inputs reproduce same ordering.
10. --json flag on status command emits valid JSON envelope.
11. empty-queue run is graceful (no crash, no results).
12. BEHIND → REBASE action; failed update-branch kicks the PR.
13. save / load round-trip preserves all fields faithfully.
14. active_entries excludes terminal states (MERGED / KICKED).
15. process with max_n=2 advances two independent PRs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.refinery.driver import FakeGh, process
from oh_no_my_claudecode.refinery.queue import (
    Action,
    CiStatus,
    PRState,
    Queue,
    active_entries,
    clear,
    drop,
    enqueue,
    load_queue,
    next_action,
    save_queue,
    set_state,
)

_RUNNER = CliRunner()


def _make_git_repo(path: Path) -> Path:
    """Create a minimal git repo at *path* (just a .git directory)."""
    (path / ".git").mkdir(parents=True, exist_ok=True)
    return path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _queue_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".onmc" / "refinery"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 1. enqueue / order / priority
# ---------------------------------------------------------------------------


def test_enqueue_priority_order() -> None:
    """Higher-priority PRs appear before lower-priority ones."""
    q = Queue()
    q = enqueue(q, pr=10, priority=0)
    q = enqueue(q, pr=20, priority=5)
    q = enqueue(q, pr=30, priority=1)

    assert q.entries[0].pr == 20
    assert q.entries[1].pr == 30
    assert q.entries[2].pr == 10


# ---------------------------------------------------------------------------
# 2. FIFO within same priority
# ---------------------------------------------------------------------------


def test_enqueue_fifo_within_same_priority() -> None:
    """Equal-priority PRs preserve insertion order (FIFO)."""
    q = Queue()
    q = enqueue(q, pr=1)
    q = enqueue(q, pr=2)
    q = enqueue(q, pr=3)

    assert [e.pr for e in q.entries] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. next_action state-machine transitions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ci_status,expected_action",
    [
        (CiStatus.BEHIND, Action.REBASE),
        (CiStatus.PENDING, Action.WAIT),
        (CiStatus.GREEN, Action.MERGE),
        (CiStatus.RED, Action.KICK),
        (CiStatus.BLOCKED, Action.KICK),
    ],
)
def test_next_action_transitions(ci_status: CiStatus, expected_action: Action) -> None:
    assert next_action(ci_status) == expected_action


# ---------------------------------------------------------------------------
# 4. process merges a green PR via fake gh
# ---------------------------------------------------------------------------


def test_process_merges_green_pr(tmp_path: Path) -> None:
    """A PR with CI_GREEN is merged and marked MERGED in the queue."""
    qd = _queue_dir(tmp_path)
    q = enqueue(Queue(), pr=42)
    save_queue(q, qd)

    fake = FakeGh(states={42: [CiStatus.GREEN]})
    results = process(q, gh=fake, queue_dir=qd, max_n=1)

    assert len(results) == 1
    r = results[0]
    assert r.pr == 42
    assert r.action == Action.MERGE
    assert r.success is True

    persisted = load_queue(qd)
    merged = [e for e in persisted.entries if e.pr == 42]
    assert merged[0].state == PRState.MERGED


# ---------------------------------------------------------------------------
# 5. process kicks a failing PR and continues to the next
# ---------------------------------------------------------------------------


def test_process_kicks_failing_pr_and_continues(tmp_path: Path) -> None:
    """A RED PR is kicked; the next PR (green) is then processed."""
    qd = _queue_dir(tmp_path)
    q = Queue()
    q = enqueue(q, pr=100)
    q = enqueue(q, pr=101)
    save_queue(q, qd)

    fake = FakeGh(states={100: [CiStatus.RED], 101: [CiStatus.GREEN]})
    results = process(q, gh=fake, queue_dir=qd, max_n=2)

    actions = {r.pr: r.action for r in results}
    assert actions[100] == Action.KICK
    assert actions[101] == Action.MERGE

    persisted = load_queue(qd)
    by_pr = {e.pr: e for e in persisted.entries}
    assert by_pr[100].state == PRState.KICKED
    assert by_pr[101].state == PRState.MERGED


# ---------------------------------------------------------------------------
# 6. CodeQL-fail → RED → KICK (blocks merge)
# ---------------------------------------------------------------------------


def test_codeql_fail_results_in_kick(tmp_path: Path) -> None:
    """CiStatus.RED (which maps from CodeQL failure) must kick, not merge."""
    qd = _queue_dir(tmp_path)
    q = enqueue(Queue(), pr=55)
    save_queue(q, qd)

    # Simulates a state where CodeQL failed — driver maps that to RED
    fake = FakeGh(states={55: [CiStatus.RED]})
    results = process(q, gh=fake, queue_dir=qd, max_n=1)

    assert results[0].action == Action.KICK
    assert results[0].success is False
    assert "failed" in results[0].reason.lower() or "ci" in results[0].reason.lower()

    persisted = load_queue(qd)
    entry = next(e for e in persisted.entries if e.pr == 55)
    assert entry.state == PRState.KICKED
    assert entry.reason != ""


# ---------------------------------------------------------------------------
# 7. drop removes a PR
# ---------------------------------------------------------------------------


def test_drop_removes_pr(tmp_path: Path) -> None:
    qd = _queue_dir(tmp_path)
    q = Queue()
    q = enqueue(q, pr=7)
    q = enqueue(q, pr=8)
    save_queue(q, qd)

    q = drop(q, pr=7)
    save_queue(q, qd)

    persisted = load_queue(qd)
    assert all(e.pr != 7 for e in persisted.entries)
    assert any(e.pr == 8 for e in persisted.entries)


# ---------------------------------------------------------------------------
# 8. clear empties the queue
# ---------------------------------------------------------------------------


def test_clear_empties_queue(tmp_path: Path) -> None:
    qd = _queue_dir(tmp_path)
    q = Queue()
    for pr in (1, 2, 3, 4):
        q = enqueue(q, pr=pr)
    save_queue(q, qd)

    q = clear(q)
    save_queue(q, qd)

    persisted = load_queue(qd)
    assert persisted.entries == []


# ---------------------------------------------------------------------------
# 9. determinism — same inputs reproduce same ordering
# ---------------------------------------------------------------------------


def test_deterministic_ordering() -> None:
    """Two queues built with the same insertions must produce identical order."""
    def _build() -> Queue:
        q = Queue()
        for pr, prio in [(3, 0), (1, 2), (2, 1), (4, 0)]:
            q = enqueue(q, pr=pr, priority=prio)
        return q

    q1 = _build()
    q2 = _build()
    assert [e.pr for e in q1.entries] == [e.pr for e in q2.entries]


# ---------------------------------------------------------------------------
# 10. --json flag on status emits valid JSON
# ---------------------------------------------------------------------------


def test_status_json_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``onmc refinery status --json`` emits a valid JSON envelope."""
    repo = _make_git_repo(tmp_path)
    qd = repo / ".onmc" / "refinery"
    qd.mkdir(parents=True)

    q = Queue()
    q = enqueue(q, pr=11)
    q = enqueue(q, pr=12)
    save_queue(q, qd)

    monkeypatch.chdir(repo)
    result = _RUNNER.invoke(app, ["refinery", "status", "--json"], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["kind"] == "refinery_status"
    assert isinstance(payload["entries"], list)
    assert payload["total"] == 2


# ---------------------------------------------------------------------------
# 11. empty-queue run is graceful
# ---------------------------------------------------------------------------


def test_empty_queue_run_is_graceful(tmp_path: Path) -> None:
    """process() with an empty queue returns [] without raising."""
    qd = _queue_dir(tmp_path)
    q = Queue()
    save_queue(q, qd)

    fake = FakeGh()
    results = process(q, gh=fake, queue_dir=qd, max_n=5)
    assert results == []


# ---------------------------------------------------------------------------
# 12. BEHIND → REBASE; failed update-branch → KICK
# ---------------------------------------------------------------------------


def test_behind_pr_triggers_rebase_then_kicks_on_conflict(tmp_path: Path) -> None:
    """A BEHIND PR that fails rebase is kicked (conflict reason)."""
    qd = _queue_dir(tmp_path)
    q = enqueue(Queue(), pr=99)
    save_queue(q, qd)

    fake = FakeGh(
        states={99: [CiStatus.BEHIND]},
        update_branch_results={99: False},  # conflict
    )
    results = process(q, gh=fake, queue_dir=qd, max_n=1)

    assert results[0].action == Action.REBASE
    assert results[0].success is False
    assert "conflict" in results[0].reason.lower()

    persisted = load_queue(qd)
    entry = next(e for e in persisted.entries if e.pr == 99)
    assert entry.state == PRState.KICKED


# ---------------------------------------------------------------------------
# 13. save / load round-trip
# ---------------------------------------------------------------------------


def test_save_load_roundtrip(tmp_path: Path) -> None:
    """All entry fields survive a save/load cycle without corruption."""
    qd = _queue_dir(tmp_path)
    q = enqueue(Queue(), pr=77, priority=3)
    q = set_state(q, pr=77, state=PRState.KICKED, reason="CI failed")
    save_queue(q, qd)

    loaded = load_queue(qd)
    assert len(loaded.entries) == 1
    e = loaded.entries[0]
    assert e.pr == 77
    assert e.priority == 3
    assert e.state == PRState.KICKED
    assert e.reason == "CI failed"


# ---------------------------------------------------------------------------
# 14. active_entries excludes terminal states
# ---------------------------------------------------------------------------


def test_active_entries_excludes_terminal() -> None:
    q = Queue()
    q = enqueue(q, pr=1)
    q = enqueue(q, pr=2)
    q = enqueue(q, pr=3)
    q = set_state(q, pr=2, state=PRState.MERGED)
    q = set_state(q, pr=3, state=PRState.KICKED)

    active = active_entries(q)
    assert len(active) == 1
    assert active[0].pr == 1


# ---------------------------------------------------------------------------
# 15. process with max_n=2 processes two PRs
# ---------------------------------------------------------------------------


def test_process_max_n_advances_two(tmp_path: Path) -> None:
    """max_n=2 processes both a kicked PR and the following green PR."""
    qd = _queue_dir(tmp_path)
    q = Queue()
    q = enqueue(q, pr=200)
    q = enqueue(q, pr=201)
    save_queue(q, qd)

    fake = FakeGh(states={200: [CiStatus.RED], 201: [CiStatus.GREEN]})
    results = process(q, gh=fake, queue_dir=qd, max_n=2)

    assert len(results) == 2
    pr_actions = {r.pr: r for r in results}
    assert pr_actions[200].action == Action.KICK
    assert pr_actions[201].action == Action.MERGE
    assert pr_actions[201].success is True
