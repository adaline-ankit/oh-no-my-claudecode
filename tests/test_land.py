"""Tests for the ``onmc land`` feature.

Coverage
--------
Planner unit tests (pure, no I/O):
  1. CLEAN + all checks green              → MERGE
  2. BEHIND                                → REBASE
  3. CLEAN + pending checks                → WAIT
  4. CodeQL FAILURE                        → FAIL
  5. Unresolved review threads             → RESOLVE_THREADS
  6. already merged                        → DONE
  7. Advisory checks (Sourcery) ignored    → MERGE
  8. BLOCKED merge state                   → FAIL

Driver tests (injectable fake GhProtocol):
  9. Fake: pending → green → merged end-to-end
  10. Contention gate: contention > limit  → deferred
  11. Timeout: deadline expires            → timeout
  12. LandError raised on FAIL step
  13. REBASE loop: behind → clean → merged
  14. RESOLVE_THREADS loop: threads → resolved → merged

CLI surface tests (CliRunner + monkeypatching):
  15. ``land status --json`` emits JSON envelope
  16. ``land run --json`` emits merged envelope on success (patched gh)
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.land.driver import GhProtocol, LandError, land
from oh_no_my_claudecode.land.planner import Step, next_step

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(
    *,
    merged: bool = False,
    merge_state: str = "CLEAN",
    checks: list[dict[str, Any]] | None = None,
    unresolved_threads: int = 0,
    unresolved_thread_ids: list[str] | None = None,
    contention: int | None = None,
) -> dict[str, Any]:
    """Build a minimal PR-state dict for the planner."""
    state: dict[str, Any] = {
        "merged": merged,
        "mergeStateStatus": merge_state,
        "checks": checks or [],
        "unresolved_threads": unresolved_threads,
        "unresolved_thread_ids": unresolved_thread_ids or [],
    }
    if contention is not None:
        state["contention"] = contention
    return state


def _check(
    name: str,
    *,
    status: str = "COMPLETED",
    conclusion: str | None = "SUCCESS",
) -> dict[str, Any]:
    return {"name": name, "status": status, "conclusion": conclusion}


class _FakeGh:
    """Injectable fake that replays a scripted sequence of PR states."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        self._states = list(states)
        self._idx = 0
        self.merged = False
        self.rebased = False
        self.resolved_threads: list[str] = []

    def pr_state(self, pr: int) -> dict[str, Any]:  # noqa: ARG002
        state = self._states[self._idx]
        # Advance only if there are more states; otherwise repeat the last.
        if self._idx < len(self._states) - 1:
            self._idx += 1
        return state

    def update_branch(self, pr: int) -> None:  # noqa: ARG002
        self.rebased = True

    def resolve_thread(self, thread_id: str) -> None:
        self.resolved_threads.append(thread_id)

    def merge(self, pr: int) -> None:  # noqa: ARG002
        self.merged = True


# ---------------------------------------------------------------------------
# 1–8: Planner unit tests
# ---------------------------------------------------------------------------


class TestPlannerMerge:
    """CLEAN + all non-advisory checks green → MERGE."""

    def test_green_clean_returns_merge(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[
                _check("quality"),
                _check("build"),
                _check("typecheck"),
            ],
        )
        assert next_step(state) == Step.MERGE

    def test_no_checks_clean_returns_merge(self) -> None:
        """Empty check list + CLEAN still merges (no blockers detected)."""
        state = _state(merge_state="CLEAN", checks=[])
        assert next_step(state) == Step.MERGE


class TestPlannerRebase:
    """BEHIND → REBASE."""

    def test_behind_returns_rebase(self) -> None:
        state = _state(merge_state="BEHIND")
        assert next_step(state) == Step.REBASE

    def test_behind_with_passing_checks_still_rebase(self) -> None:
        state = _state(merge_state="BEHIND", checks=[_check("quality")])
        assert next_step(state) == Step.REBASE


class TestPlannerWait:
    """Pending checks → WAIT."""

    def test_pending_check_returns_wait(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[_check("quality", status="IN_PROGRESS", conclusion=None)],
        )
        assert next_step(state) == Step.WAIT

    def test_queued_check_returns_wait(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[_check("build", status="QUEUED", conclusion=None)],
        )
        assert next_step(state) == Step.WAIT

    def test_unstable_state_returns_wait(self) -> None:
        """UNSTABLE merge state with no actionable check info → WAIT."""
        state = _state(merge_state="UNSTABLE", checks=[])
        assert next_step(state) == Step.WAIT


class TestPlannerFail:
    """Hard-blocking failures → FAIL."""

    def test_codeql_failure_returns_fail(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[_check("CodeQL", conclusion="FAILURE")],
        )
        assert next_step(state) == Step.FAIL

    def test_codeql_case_insensitive(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[_check("codeql / python", conclusion="FAILURE")],
        )
        assert next_step(state) == Step.FAIL

    def test_regular_check_failure_returns_fail(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[
                _check("quality", conclusion="FAILURE"),
            ],
        )
        assert next_step(state) == Step.FAIL

    def test_blocked_merge_state_returns_fail(self) -> None:
        state = _state(
            merge_state="BLOCKED",
            checks=[_check("quality")],
        )
        assert next_step(state) == Step.FAIL


class TestPlannerResolveThreads:
    """Unresolved review threads → RESOLVE_THREADS."""

    def test_unresolved_threads_returns_resolve(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[_check("quality")],
            unresolved_threads=2,
            unresolved_thread_ids=["tid1", "tid2"],
        )
        assert next_step(state) == Step.RESOLVE_THREADS


class TestPlannerDone:
    """Already merged → DONE."""

    def test_merged_returns_done(self) -> None:
        state = _state(merged=True)
        assert next_step(state) == Step.DONE

    def test_merged_ignores_other_fields(self) -> None:
        state = _state(merged=True, merge_state="BLOCKED", unresolved_threads=5)
        assert next_step(state) == Step.DONE


class TestPlannerAdvisoryChecks:
    """Advisory checks (Sourcery, greetings, apply-area-labels) are ignored."""

    def test_sourcery_failure_does_not_block(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[
                _check("quality"),
                _check("Sourcery AI", conclusion="FAILURE"),
                _check("greetings", conclusion="FAILURE"),
                _check("apply-area-labels", status="IN_PROGRESS", conclusion=None),
            ],
        )
        assert next_step(state) == Step.MERGE

    def test_sourcery_pending_does_not_wait(self) -> None:
        state = _state(
            merge_state="CLEAN",
            checks=[
                _check("quality"),
                _check("sourcery", status="IN_PROGRESS", conclusion=None),
            ],
        )
        assert next_step(state) == Step.MERGE


# ---------------------------------------------------------------------------
# 9–14: Driver tests
# ---------------------------------------------------------------------------


class TestDriverMerge:
    """Driver merges via fake gh end-to-end."""

    def test_pending_then_green_merges(self) -> None:
        """First poll WAIT, second poll CLEAN+green → merged."""
        fake = _FakeGh(
            states=[
                _state(
                    merge_state="CLEAN",
                    checks=[_check("quality", status="IN_PROGRESS", conclusion=None)],
                ),
                _state(
                    merge_state="CLEAN",
                    checks=[_check("quality")],
                ),
            ]
        )
        sleeps: list[float] = []
        result = land(1, gh=fake, sleep=sleeps.append, poll_interval=5.0, max_wait=60.0)
        assert result["outcome"] == "merged"
        assert fake.merged is True
        assert len(sleeps) == 1

    def test_already_merged_returns_done(self) -> None:
        fake = _FakeGh(states=[_state(merged=True)])
        result = land(1, gh=fake, sleep=lambda _: None)
        assert result["outcome"] == "merged"
        assert fake.merged is False  # driver did not call merge (already done)

    def test_clean_green_merges_immediately(self) -> None:
        """First poll already green → merge without sleeping."""
        fake = _FakeGh(states=[_state(merge_state="CLEAN", checks=[_check("quality")])])
        sleeps: list[float] = []
        result = land(99, gh=fake, sleep=sleeps.append)
        assert result["outcome"] == "merged"
        assert len(sleeps) == 0


class TestDriverContention:
    """Contention gate: contention > limit → deferred."""

    def test_contention_above_limit_defers(self) -> None:
        fake = _FakeGh(
            states=[_state(merge_state="CLEAN", checks=[_check("q")], contention=10)]
        )
        result = land(1, gh=fake, sleep=lambda _: None, only_if_contention_le=5)
        assert result["outcome"] == "deferred"
        assert fake.merged is False

    def test_contention_at_limit_proceeds(self) -> None:
        """Contention == limit is allowed (not strictly greater)."""
        fake = _FakeGh(
            states=[_state(merge_state="CLEAN", checks=[_check("q")], contention=5)]
        )
        result = land(1, gh=fake, sleep=lambda _: None, only_if_contention_le=5)
        assert result["outcome"] == "merged"

    def test_contention_gate_disabled_by_default(self) -> None:
        fake = _FakeGh(
            states=[_state(merge_state="CLEAN", checks=[_check("q")], contention=9999)]
        )
        result = land(1, gh=fake, sleep=lambda _: None)
        assert result["outcome"] == "merged"


class TestDriverTimeout:
    """Deadline expires → timeout."""

    def test_timeout_on_perpetual_wait(self) -> None:
        """PR stays pending, deadline expires after first sleep."""
        fake = _FakeGh(
            states=[
                _state(
                    merge_state="CLEAN",
                    checks=[_check("q", status="IN_PROGRESS", conclusion=None)],
                )
            ]
        )
        sleeps: list[float] = []
        result = land(
            1,
            gh=fake,
            sleep=sleeps.append,
            poll_interval=999.0,
            max_wait=0.0,  # deadline already elapsed
        )
        assert result["outcome"] == "timeout"


class TestDriverFail:
    """Step.FAIL raises LandError."""

    def test_codeql_failure_raises_land_error(self) -> None:
        fake = _FakeGh(
            states=[
                _state(
                    merge_state="CLEAN",
                    checks=[_check("CodeQL", conclusion="FAILURE")],
                )
            ]
        )
        with pytest.raises(LandError, match="landing blocked"):
            land(1, gh=fake, sleep=lambda _: None)


class TestDriverRebase:
    """REBASE loop: behind → clean → merged."""

    def test_rebase_then_merge(self) -> None:
        fake = _FakeGh(
            states=[
                _state(merge_state="BEHIND"),
                _state(merge_state="CLEAN", checks=[_check("quality")]),
            ]
        )
        sleeps: list[float] = []
        result = land(1, gh=fake, sleep=sleeps.append, poll_interval=1.0, max_wait=60.0)
        assert result["outcome"] == "merged"
        assert fake.rebased is True
        assert fake.merged is True
        assert len(sleeps) == 1


class TestDriverResolveThreads:
    """RESOLVE_THREADS loop: threads → resolved → merged."""

    def test_resolve_threads_then_merge(self) -> None:
        fake = _FakeGh(
            states=[
                _state(
                    merge_state="CLEAN",
                    checks=[_check("quality")],
                    unresolved_threads=2,
                    unresolved_thread_ids=["tid-a", "tid-b"],
                ),
                _state(merge_state="CLEAN", checks=[_check("quality")]),
            ]
        )
        sleeps: list[float] = []
        result = land(1, gh=fake, sleep=sleeps.append, poll_interval=1.0, max_wait=60.0)
        assert result["outcome"] == "merged"
        assert fake.resolved_threads == ["tid-a", "tid-b"]
        assert fake.merged is True


# ---------------------------------------------------------------------------
# 15–16: CLI surface tests
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestLandCliStatus:
    """``onmc land status`` — read-only, --json output."""

    def test_status_json_envelope(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """``land status <pr> --json`` emits a JSON envelope with kind=land_status."""
        import oh_no_my_claudecode.land.commands as lc

        def _fake_build_gh() -> GhProtocol:
            return _FakeGh(
                states=[_state(merge_state="CLEAN", checks=[_check("quality")])]
            )

        monkeypatch.setattr(lc, "_build_gh_client", _fake_build_gh)
        result = runner.invoke(app, ["land", "status", "42", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["kind"] == "land_status"
        assert envelope["pr"] == 42
        assert "next_step" in envelope
        assert envelope["next_step"] == "merge"

    def test_status_plain_output(self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch) -> None:
        """``land status <pr>`` without --json emits a human-readable summary."""
        import oh_no_my_claudecode.land.commands as lc

        def _fake_build_gh() -> GhProtocol:
            return _FakeGh(
                states=[
                    _state(
                        merge_state="CLEAN",
                        checks=[_check("quality", status="IN_PROGRESS", conclusion=None)],
                    )
                ]
            )

        monkeypatch.setattr(lc, "_build_gh_client", _fake_build_gh)
        result = runner.invoke(app, ["land", "status", "7"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "PR #7" in result.output
        assert "wait" in result.output


class TestLandCliRun:
    """``onmc land run`` — merge happy path + JSON envelope."""

    def test_run_merges_and_outputs_json(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``land run <pr> --json`` emits ``{"kind": "land_result", "outcome": "merged"}``."""
        import oh_no_my_claudecode.land.commands as lc

        fake_gh = _FakeGh(states=[_state(merge_state="CLEAN", checks=[_check("quality")])])

        def _fake_build_gh() -> GhProtocol:
            return fake_gh

        monkeypatch.setattr(lc, "_build_gh_client", _fake_build_gh)
        result = runner.invoke(app, ["land", "run", "99", "--json"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["kind"] == "land_result"
        assert envelope["outcome"] == "merged"
        assert envelope["pr"] == 99
        assert fake_gh.merged is True

    def test_run_plain_success_message(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import oh_no_my_claudecode.land.commands as lc

        def _fake_build_gh() -> GhProtocol:
            return _FakeGh(states=[_state(merge_state="CLEAN", checks=[_check("quality")])])

        monkeypatch.setattr(lc, "_build_gh_client", _fake_build_gh)
        result = runner.invoke(app, ["land", "run", "55"], catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert "merged successfully" in result.output

    def test_run_blocked_exits_nonzero(
        self, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import oh_no_my_claudecode.land.commands as lc

        def _fake_build_gh() -> GhProtocol:
            return _FakeGh(
                states=[
                    _state(
                        merge_state="CLEAN",
                        checks=[_check("CodeQL", conclusion="FAILURE")],
                    )
                ]
            )

        monkeypatch.setattr(lc, "_build_gh_client", _fake_build_gh)
        result = runner.invoke(app, ["land", "run", "11"])
        assert result.exit_code != 0


class TestRealGhClientMergedField:
    """Regression: pr_state must derive `merged` from `state`, not a
    nonexistent `gh pr view --json merged` field (which errors out)."""

    def _run_factory(self, payload: dict[str, Any]):
        import subprocess

        def _fake_run(cmd, capture_output=True, text=True, check=False):  # noqa: ANN001,ANN202
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        return _fake_run

    def test_state_merged_maps_to_merged_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import oh_no_my_claudecode.land.commands as lc

        monkeypatch.setattr(lc.subprocess, "run", self._run_factory({"state": "MERGED"}))
        assert lc._RealGhClient().pr_state(1)["merged"] is True

    def test_open_state_maps_to_merged_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import oh_no_my_claudecode.land.commands as lc

        monkeypatch.setattr(
            lc.subprocess,
            "run",
            self._run_factory({"state": "OPEN", "mergeStateStatus": "CLEAN"}),
        )
        assert lc._RealGhClient().pr_state(1)["merged"] is False

    def test_json_query_requests_state_not_merged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import oh_no_my_claudecode.land.commands as lc

        seen: dict[str, str] = {}

        def _capture(cmd, capture_output=True, text=True, check=False):  # noqa: ANN001,ANN202
            import subprocess

            seen["fields"] = cmd[cmd.index("--json") + 1]
            out = json.dumps({"state": "OPEN"})
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        monkeypatch.setattr(lc.subprocess, "run", _capture)
        lc._RealGhClient().pr_state(1)
        assert "state" in seen["fields"]
        assert "merged" not in seen["fields"].split(",")
