"""CLI surface for the ``land`` feature — auto-discovered.

Follows the auto-discovery convention (see
:mod:`oh_no_my_claudecode.command_registry` and the "Adding a command" section
of ``CONTRIBUTING.md``): this module exposes a top-level ``register(app)`` that
the registry invokes at CLI build time, so ``onmc land`` ships with **zero edits**
to ``cli.py`` or any other shared hub.

Commands
--------
``onmc land run <pr>``
    Poll checks, rebase if behind, resolve advisory threads, then
    squash-merge when the quality matrix is green and CodeQL has not failed.

``onmc land status <pr>``
    Fetch PR state and show what the lander *would* do next — read-only,
    no mutations.

Real gh calls are isolated in ``_RealGhClient``; the factory function
``_build_gh_client()`` is module-level so tests can monkeypatch it to inject
a ``FakeGh`` without touching the network.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Annotated, Any

import typer

from oh_no_my_claudecode.land.driver import GhProtocol, LandError, LandResult, land
from oh_no_my_claudecode.land.planner import Step, next_step

# ---------------------------------------------------------------------------
# Real GitHub client
# ---------------------------------------------------------------------------


class _RealGhClient:
    """GitHub client that shells out to ``gh``.

    Implements ``GhProtocol`` so the driver can use it transparently.
    """

    def pr_state(self, pr: int) -> dict[str, Any]:
        """Fetch PR state via ``gh pr view --json``."""
        result = subprocess.run(  # noqa: S603
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--json",
                "mergeStateStatus,state,statusCheckRollup,reviewThreads",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise LandError(f"gh pr view failed (exit {result.returncode}): {msg}")
        data: dict[str, Any] = json.loads(result.stdout)

        checks: list[dict[str, Any]] = []
        for chk in data.get("statusCheckRollup") or []:
            checks.append(
                {
                    "name": chk.get("name") or chk.get("context", ""),
                    "status": chk.get("status", ""),
                    "conclusion": chk.get("conclusion"),
                }
            )

        threads: list[dict[str, Any]] = data.get("reviewThreads") or []
        unresolved = [t for t in threads if not t.get("isResolved", True)]

        return {
            "merged": str(data.get("state", "")).upper() == "MERGED",
            "mergeStateStatus": str(data.get("mergeStateStatus", "UNKNOWN")),
            "checks": checks,
            "unresolved_threads": len(unresolved),
            "unresolved_thread_ids": [t["id"] for t in unresolved if "id" in t],
        }

    def update_branch(self, pr: int) -> None:
        """Rebase the PR branch onto the current target."""
        result = subprocess.run(  # noqa: S603
            ["gh", "pr", "update-branch", str(pr), "--rebase"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise LandError(f"gh pr update-branch failed (exit {result.returncode}): {msg}")

    def resolve_thread(self, thread_id: str) -> None:
        """Resolve a review thread via the GitHub GraphQL API."""
        query = (
            "mutation ResolveThread($tid: ID!) "
            "{ resolveReviewThread(input: {threadId: $tid}) { thread { id } } }"
        )
        result = subprocess.run(  # noqa: S603
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"query={query}",
                "-f",
                f"tid={thread_id}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise LandError(f"resolve thread {thread_id!r} failed: {msg}")

    def merge(self, pr: int) -> None:
        """Squash-merge with ``--admin --delete-branch``."""
        result = subprocess.run(  # noqa: S603
            ["gh", "pr", "merge", str(pr), "--squash", "--admin", "--delete-branch"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            raise LandError(f"gh pr merge failed (exit {result.returncode}): {msg}")


def _build_gh_client() -> GhProtocol:
    """Return the real GitHub client.

    Module-level factory so tests can monkeypatch it to inject a fake.
    """
    return _RealGhClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STEP_LABELS: dict[Step, str] = {
    Step.WAIT: "waiting for checks",
    Step.REBASE: "needs rebase (branch is behind)",
    Step.RESOLVE_THREADS: "needs thread resolution",
    Step.MERGE: "ready to merge",
    Step.DONE: "already merged",
    Step.FAIL: "blocked — cannot merge",
}


def _render_status(pr: int, state: dict[str, Any], step: Step, *, as_json: bool) -> None:
    """Print the current landing status to stdout."""
    checks: list[dict[str, Any]] = state.get("checks", [])
    checks_total = len(checks)
    checks_pending = sum(
        1
        for c in checks
        if c.get("conclusion") is None or c.get("status") in ("QUEUED", "IN_PROGRESS")
    )
    checks_failed = sum(1 for c in checks if c.get("conclusion") == "FAILURE")

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "kind": "land_status",
                    "pr": pr,
                    "next_step": step.value,
                    "next_step_label": _STEP_LABELS.get(step, step.value),
                    "merge_state": state.get("mergeStateStatus", "UNKNOWN"),
                    "checks_total": checks_total,
                    "checks_pending": checks_pending,
                    "checks_failed": checks_failed,
                    "unresolved_threads": state.get("unresolved_threads", 0),
                },
                indent=2,
            )
        )
        return

    label = _STEP_LABELS.get(step, step.value)
    typer.echo(f"  PR #{pr}  next: {step.value}  ({label})")
    typer.echo(
        f"  merge-state: {state.get('mergeStateStatus', 'UNKNOWN')}  "
        f"checks: {checks_total} total / {checks_pending} pending / {checks_failed} failed  "
        f"unresolved-threads: {state.get('unresolved_threads', 0)}"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

land_app = typer.Typer(
    help="Safe PR lander: poll checks, rebase if behind, squash-merge when green.",
    no_args_is_help=True,
)


def register(app: typer.Typer) -> None:
    """Register the ``onmc land`` command group onto the root ``app``.

    Called automatically by
    :func:`oh_no_my_claudecode.command_registry.register_feature_commands`.
    """
    app.add_typer(land_app, name="land")


@land_app.command("run")
def land_run_command(
    pr: Annotated[
        int,
        typer.Argument(help="PR number to land."),
    ],
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help='Emit a JSON envelope {"kind": "land_result", ...} on completion.',
        ),
    ] = False,
    max_wait: Annotated[
        int,
        typer.Option(
            "--max-wait",
            help="Maximum seconds to wait for checks to go green (default: 1800).",
            metavar="SECONDS",
        ),
    ] = 1800,
    poll_interval: Annotated[
        int,
        typer.Option(
            "--poll-interval",
            help="Seconds between status polls (default: 30).",
            metavar="SECONDS",
        ),
    ] = 30,
    only_if_contention_le: Annotated[
        int | None,
        typer.Option(
            "--only-if-contention-le",
            help=(
                "Defer without action if the repo has more than N concurrent "
                "CI runs (as reported in PR state).  Omit to disable."
            ),
            metavar="N",
        ),
    ] = None,
) -> None:
    """Land PR safely: poll checks, rebase if behind, squash-merge when green.

    Polls ``gh pr view`` on a cadence, applies the landing planner, and takes
    the appropriate action (rebase, resolve threads, or merge) until the PR
    lands or the deadline is reached.

    Gate logic:

    \\b
    - CodeQL FAILURE → abort immediately (exit 1).
    - Branch BEHIND  → ``gh pr update-branch --rebase``, then re-poll.
    - Unresolved threads → resolve via GraphQL, then re-poll.
    - All non-advisory checks green + CLEAN → ``gh pr merge --squash --admin``.
    - Advisory checks (Sourcery, greetings, apply-area-labels) are ignored.

    Examples:

        onmc land run 123

        onmc land run 456 --json

        onmc land run 789 --max-wait 3600 --only-if-contention-le 5
    """
    gh_client = _build_gh_client()
    try:
        result: LandResult = land(
            pr,
            gh=gh_client,
            poll_interval=float(poll_interval),
            max_wait=float(max_wait),
            only_if_contention_le=only_if_contention_le,
        )
    except LandError as exc:
        if as_json:
            typer.echo(
                json.dumps(
                    {"kind": "land_result", "pr": pr, "outcome": "failed", "error": str(exc)}
                )
            )
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    outcome = result["outcome"]
    reason = result.get("reason")

    if as_json:
        payload: dict[str, object] = {"kind": "land_result", "pr": pr, "outcome": outcome}
        if reason:
            payload["reason"] = reason
        typer.echo(json.dumps(payload, indent=2))
    else:
        if outcome == "merged":
            typer.echo(f"PR #{pr} merged successfully.")
        elif outcome == "deferred":
            typer.echo(f"PR #{pr} deferred: {reason or 'contention too high'}.")
        elif outcome == "timeout":
            typer.echo(
                f"PR #{pr} timed out after {max_wait}s — checks did not go green.",
                err=True,
            )
            raise typer.Exit(code=1)


@land_app.command("status")
def land_status_command(
    pr: Annotated[
        int,
        typer.Argument(help="PR number to query."),
    ],
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help='Emit a JSON status envelope {"kind": "land_status", ...}.',
        ),
    ] = False,
) -> None:
    """Show what the lander would do for this PR — read-only, no mutations.

    Fetches current PR state via ``gh`` and runs the planner to determine
    the next action.  Nothing is changed.

    Examples:

        onmc land status 123

        onmc land status 456 --json
    """
    gh_client = _build_gh_client()
    try:
        state = gh_client.pr_state(pr)
    except LandError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    step = next_step(state)
    _render_status(pr, state, step, as_json=as_json)

    # Exit non-zero when the PR is blocked so callers can gate on this.
    if step == Step.FAIL:
        sys.exit(1)
