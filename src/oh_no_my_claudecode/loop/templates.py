"""Built-in loop templates for common autonomous-agent workflows.

Usage
-----
::

    # Fill defaults from a named template:
    from oh_no_my_claudecode.loop.templates import get_template, list_templates

    tmpl = get_template("ci-healer")
    # tmpl.goal, tmpl.verify, tmpl.max_iterations, tmpl.description, ...

    # List all available template names + one-line summaries:
    for name, desc in list_templates():
        print(f"  {name}: {desc}")

Available templates
-------------------
ci-healer
    Goal: fix failing CI without changing public behaviour.
    Verify: ``pytest`` (or the repo's configured CI check command).
    Reasonable caps: 15 iterations, no cost cap by default (operators can
    override with ``--max-cost-usd``).

pr-babysitter
    Goal: keep a pull request green — rebase, fix conflicts, re-run checks.
    Verify: ``pytest`` by default (override with ``--verify``).
    Caps: 8 iterations (less aggressive than ci-healer; assumes PR is mostly done).

issue-to-pr
    Goal: implement the described issue as a PR-ready change with passing tests.
    Verify: ``pytest`` by default.
    Caps: 20 iterations (issues need more exploration than a simple CI fix).

Explicit flags always override template defaults.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopTemplate:
    """A named preset that fills loop defaults.

    All fields map 1:1 to ``onmc loop`` flags.  ``None`` means "use the
    command default" — only non-None fields are applied.
    """

    name: str
    description: str
    goal: str
    verify: str
    max_iterations: int
    max_cost_usd: float | None = None
    max_wall_seconds: int | None = None


# ---------------------------------------------------------------------------
# Built-in registry
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, LoopTemplate] = {
    "ci-healer": LoopTemplate(
        name="ci-healer",
        description=(
            "Fix failing CI without changing public behaviour. "
            "Runs up to 15 iterations against pytest."
        ),
        goal=(
            "Fix all failing CI checks without changing any public API or behaviour. "
            "Run the test suite after each change. "
            "Stop as soon as all tests pass. "
            "Do NOT add new tests to paper over failures — fix the root cause."
        ),
        verify="pytest",
        max_iterations=15,
        max_cost_usd=None,
        max_wall_seconds=None,
    ),
    "pr-babysitter": LoopTemplate(
        name="pr-babysitter",
        description=(
            "Keep a pull request green: rebase, resolve conflicts, re-run checks. "
            "Runs up to 8 iterations."
        ),
        goal=(
            "Keep this pull request in a mergeable state. "
            "Rebase against the base branch if needed, resolve merge conflicts, "
            "fix any test failures introduced by the rebase, and confirm all "
            "CI checks pass. Do NOT introduce new functionality — only stabilise "
            "what is already here."
        ),
        verify="pytest",
        max_iterations=8,
        max_cost_usd=None,
        max_wall_seconds=None,
    ),
    "issue-to-pr": LoopTemplate(
        name="issue-to-pr",
        description=(
            "Implement a GitHub issue as a PR-ready change with passing tests. "
            "Runs up to 20 iterations."
        ),
        goal=(
            "Implement the issue described above as a complete, PR-ready change. "
            "Requirements:\n"
            "1. All existing tests must continue to pass.\n"
            "2. Add or update tests to cover the new behaviour.\n"
            "3. Follow the existing code style and patterns.\n"
            "4. Do not change unrelated code.\n"
            "Stop only when the full test suite passes with the new behaviour in place."
        ),
        verify="pytest",
        max_iterations=20,
        max_cost_usd=None,
        max_wall_seconds=None,
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_template(name: str) -> LoopTemplate:
    """Return the named template, or raise ``ValueError`` listing valid names.

    Parameters
    ----------
    name:
        The template name (case-sensitive).

    Raises
    ------
    ValueError
        When *name* is not a known template.  The error message includes the
        list of valid names so CLI users see it directly.
    """
    tmpl = _TEMPLATES.get(name)
    if tmpl is None:
        valid = ", ".join(sorted(_TEMPLATES))
        raise ValueError(
            f"Unknown template {name!r}. Valid templates: {valid}"
        )
    return tmpl


def list_templates() -> list[tuple[str, str]]:
    """Return ``[(name, description), ...]`` sorted by name."""
    return sorted(
        ((name, t.description) for name, t in _TEMPLATES.items()),
        key=lambda x: x[0],
    )


__all__ = [
    "LoopTemplate",
    "get_template",
    "list_templates",
]
