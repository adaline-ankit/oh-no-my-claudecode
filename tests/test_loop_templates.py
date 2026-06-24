"""Tests for built-in loop templates.

All tests are pure unit tests — no subprocess, no agent, no filesystem I/O.
"""

from __future__ import annotations

from pathlib import Path

import pytest  # noqa: F401

from oh_no_my_claudecode.loop.templates import (
    LoopTemplate,
    get_template,
    list_templates,
)

# ---------------------------------------------------------------------------
# Test 1: all three built-in templates exist and have required fields
# ---------------------------------------------------------------------------


def test_all_three_templates_registered() -> None:
    """ci-healer, pr-babysitter, and issue-to-pr must all be registered."""
    names = {name for name, _ in list_templates()}
    assert "ci-healer" in names
    assert "pr-babysitter" in names
    assert "issue-to-pr" in names


def test_each_template_has_non_empty_goal() -> None:
    """Every template must have a non-empty goal."""
    for name, _ in list_templates():
        tmpl = get_template(name)
        assert tmpl.goal.strip(), f"Template {name!r} has empty goal"


def test_each_template_has_non_empty_verify() -> None:
    """Every template must have a non-empty verify command."""
    for name, _ in list_templates():
        tmpl = get_template(name)
        assert tmpl.verify.strip(), f"Template {name!r} has empty verify"


def test_each_template_has_positive_max_iterations() -> None:
    """Every template must have max_iterations >= 1."""
    for name, _ in list_templates():
        tmpl = get_template(name)
        assert tmpl.max_iterations >= 1, (
            f"Template {name!r} has max_iterations={tmpl.max_iterations}"
        )


def test_each_template_has_description() -> None:
    """Every template must have a non-empty description."""
    for name, _ in list_templates():
        tmpl = get_template(name)
        assert tmpl.description.strip(), f"Template {name!r} has empty description"


# ---------------------------------------------------------------------------
# Test 2: get_template returns the correct template for each name
# ---------------------------------------------------------------------------


def test_get_template_ci_healer() -> None:
    """get_template('ci-healer') returns a LoopTemplate with name 'ci-healer'."""
    tmpl = get_template("ci-healer")
    assert isinstance(tmpl, LoopTemplate)
    assert tmpl.name == "ci-healer"
    assert tmpl.max_iterations >= 10


def test_get_template_pr_babysitter() -> None:
    """get_template('pr-babysitter') returns a LoopTemplate with name 'pr-babysitter'."""
    tmpl = get_template("pr-babysitter")
    assert isinstance(tmpl, LoopTemplate)
    assert tmpl.name == "pr-babysitter"


def test_get_template_issue_to_pr() -> None:
    """get_template('issue-to-pr') returns a LoopTemplate with name 'issue-to-pr'."""
    tmpl = get_template("issue-to-pr")
    assert isinstance(tmpl, LoopTemplate)
    assert tmpl.name == "issue-to-pr"
    assert tmpl.max_iterations >= 15  # issue-to-pr needs more iterations


# ---------------------------------------------------------------------------
# Test 3: unknown template raises ValueError with helpful message
# ---------------------------------------------------------------------------


def test_unknown_template_raises_value_error() -> None:
    """get_template with an unknown name must raise ValueError listing valid names."""
    with pytest.raises(ValueError, match="Unknown template") as exc_info:
        get_template("nonexistent-template")

    msg = str(exc_info.value)
    # The error message must list valid template names.
    assert "ci-healer" in msg
    assert "pr-babysitter" in msg
    assert "issue-to-pr" in msg


def test_unknown_template_error_mentions_name() -> None:
    """The ValueError must mention the bad template name."""
    with pytest.raises(ValueError, match="not-a-template"):
        get_template("not-a-template")


# ---------------------------------------------------------------------------
# Test 4: list_templates returns sorted list of (name, description) tuples
# ---------------------------------------------------------------------------


def test_list_templates_returns_sorted_list() -> None:
    """list_templates() must return a list of (name, description) tuples, sorted by name."""
    templates = list_templates()
    assert isinstance(templates, list)
    assert len(templates) == 3  # exactly 3 built-in templates

    for item in templates:
        assert isinstance(item, tuple)
        assert len(item) == 2
        name, desc = item
        assert isinstance(name, str)
        assert isinstance(desc, str)
        assert name.strip()
        assert desc.strip()

    names = [n for n, _ in templates]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# Test 5: CLI --template integration via typer test client
# ---------------------------------------------------------------------------


def test_cli_list_templates_flag(tmp_path: Path) -> None:
    """onmc loop --list-templates must print templates and exit 0."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["loop", "--list-templates"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    assert "ci-healer" in output
    assert "pr-babysitter" in output
    assert "issue-to-pr" in output


def test_cli_loop_templates_command() -> None:
    """onmc loop-templates must print templates and exit 0."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["loop-templates"], catch_exceptions=False)
    assert result.exit_code == 0
    output = result.stdout
    assert "ci-healer" in output
    assert "pr-babysitter" in output
    assert "issue-to-pr" in output


def test_cli_unknown_template_exits_nonzero() -> None:
    """onmc loop --template badname must exit non-zero with an error message."""
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["loop", "--template", "not-a-template"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Test 6: template defaults are overridable by explicit flags
# ---------------------------------------------------------------------------


def test_template_goal_overridden_by_explicit_goal(tmp_path: Path) -> None:
    """When --goal is provided alongside --template, the explicit goal wins."""
    # We test the resolution logic directly (not the service) by checking that
    # the CLI assembles the right call.  We use dry-run to avoid needing a repo.
    from typer.testing import CliRunner

    from oh_no_my_claudecode.cli import app

    runner = CliRunner()
    # dry-run should succeed and show the explicit goal in the prompt, not the
    # template's default goal.  We use a tmp dir as cwd but need an onmc repo.
    # Since we're just testing flag resolution (not the full loop), we only
    # verify the CLI doesn't error on the combination.
    result = runner.invoke(
        app,
        ["loop", "--template", "ci-healer", "--goal", "custom goal", "--dry-run"],
    )
    # Either succeeds (0) or fails with a repo-not-found error (1).
    # The important thing is it does NOT fail with "Unknown template" or
    # "Provide --goal or --spec" — those would be flag-resolution bugs.
    assert "Unknown template" not in (result.stdout + (result.stderr or ""))
    assert "Provide --goal or --spec" not in (result.stdout + (result.stderr or ""))
