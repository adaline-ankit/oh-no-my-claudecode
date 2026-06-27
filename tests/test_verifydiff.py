"""Tests for onmc verify-diff — the adversarial diff-level gate.

Coverage
--------
- EMPTY diff → non-empty check FAILS (the headline false-converge bug).
- Whitespace-only diff → also FAILS non-empty.
- Diff adding an expected symbol, with covered added lines and no banned
  pattern → PASS.
- An added executable line not in the coverage set → coverage check FAILS.
- No coverage supplied → coverage is a soft passing note.
- Banned substring in an added line → lawful:banned FAILS.
- Secret pattern (AWS key) in an added line → lawful:secret FAILS.
- Missing expected symbol → symbol check FAILS.
- Missing expected file → file check FAILS.
- Determinism: same inputs → identical findings.
- --json: emits ok + findings, exit 1 on failure.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.verifydiff import (
    DiffFinding,
    VerifyReport,
    verify_diff,
)

runner = CliRunner()


# ---------------------------------------------------------------------------
# Diff fixtures
# ---------------------------------------------------------------------------


def _diff_add_function() -> str:
    """A diff that adds a new function `widget_total` to a fresh file."""
    return (
        "diff --git a/src/pkg/widget.py b/src/pkg/widget.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/pkg/widget.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def widget_total(items):\n"
        "+    # sum the items\n"
        "+    return sum(items)\n"
    )


def _finding(report: VerifyReport, rule: str) -> DiffFinding:
    for finding in report.findings:
        if finding.rule == rule:
            return finding
    raise AssertionError(f"no finding for rule {rule!r}: {[f.rule for f in report.findings]}")


# ---------------------------------------------------------------------------
# Headline: empty diff must fail
# ---------------------------------------------------------------------------


def test_empty_diff_fails() -> None:
    report = verify_diff(diff_text="")
    assert report.ok is False
    assert _finding(report, "non-empty").ok is False


def test_whitespace_only_diff_fails() -> None:
    report = verify_diff(diff_text="   \n\n  \t\n")
    assert report.ok is False
    assert _finding(report, "non-empty").ok is False


# ---------------------------------------------------------------------------
# Happy path: real, covered, lawful change with expected symbol
# ---------------------------------------------------------------------------


def test_real_covered_lawful_passes() -> None:
    coverage = {"src/pkg/widget.py": {1, 3}}  # lines 1 & 3 are executable + covered
    report = verify_diff(
        diff_text=_diff_add_function(),
        coverage=coverage,
        expect_symbols=("widget_total",),
        expect_files=("src/pkg/widget.py",),
    )
    assert report.ok is True, [f for f in report.findings if not f.ok]
    assert _finding(report, "non-empty").ok is True
    assert _finding(report, "symbol:widget_total").ok is True
    assert _finding(report, "file:src/pkg/widget.py").ok is True
    assert _finding(report, "coverage").ok is True
    assert _finding(report, "lawful:banned").ok is True
    assert _finding(report, "lawful:secret").ok is True


# ---------------------------------------------------------------------------
# Coverage gate
# ---------------------------------------------------------------------------


def test_uncovered_added_line_flagged() -> None:
    # Cover line 1 (def) but NOT line 3 (the return) — line 3 is executable.
    coverage = {"src/pkg/widget.py": {1}}
    report = verify_diff(diff_text=_diff_add_function(), coverage=coverage)
    cov = _finding(report, "coverage")
    assert cov.ok is False
    assert "src/pkg/widget.py:3" in cov.detail
    assert report.ok is False


def test_no_coverage_is_soft_note() -> None:
    report = verify_diff(
        diff_text=_diff_add_function(),
        expect_symbols=("widget_total",),
    )
    cov = _finding(report, "coverage")
    assert cov.ok is True
    assert "skipped" in cov.detail.lower()


# ---------------------------------------------------------------------------
# Lawful gate
# ---------------------------------------------------------------------------


def test_banned_substring_fails() -> None:
    diff = (
        "--- /dev/null\n"
        "+++ b/src/pkg/widget.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def helper():\n"
        "+    pass  # secretword in here\n"
    )
    report = verify_diff(diff_text=diff, banned_patterns=("secretword",))
    banned = _finding(report, "lawful:banned")
    assert banned.ok is False
    assert "secretword" in banned.detail
    assert report.ok is False


def test_secret_pattern_fails() -> None:
    # A realistic-looking AWS access key id (matches SECRET-001 in audit rules).
    diff = (
        "--- /dev/null\n"
        "+++ b/src/pkg/config.py\n"
        "@@ -0,0 +1,1 @@\n"
        '+AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
    )
    report = verify_diff(diff_text=diff)
    secret = _finding(report, "lawful:secret")
    assert secret.ok is False
    assert "SECRET-001" in secret.detail
    assert report.ok is False


# ---------------------------------------------------------------------------
# Expectation gates
# ---------------------------------------------------------------------------


def test_missing_expected_symbol_fails() -> None:
    report = verify_diff(
        diff_text=_diff_add_function(),
        expect_symbols=("nonexistent_symbol",),
    )
    sym = _finding(report, "symbol:nonexistent_symbol")
    assert sym.ok is False
    assert "missing" in sym.detail.lower()
    assert report.ok is False


def test_missing_expected_file_fails() -> None:
    report = verify_diff(
        diff_text=_diff_add_function(),
        expect_files=("src/pkg/other.py",),
    )
    fil = _finding(report, "file:src/pkg/other.py")
    assert fil.ok is False
    assert report.ok is False


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic() -> None:
    coverage = {"src/pkg/widget.py": {1, 3}}
    kwargs = {
        "diff_text": _diff_add_function(),
        "coverage": coverage,
        "expect_symbols": ("widget_total",),
        "expect_files": ("src/pkg/widget.py",),
    }
    a = verify_diff(**kwargs)  # type: ignore[arg-type]
    b = verify_diff(**kwargs)  # type: ignore[arg-type]
    assert a.ok == b.ok
    assert [(f.rule, f.ok, f.detail) for f in a.findings] == [
        (f.rule, f.ok, f.detail) for f in b.findings
    ]


# ---------------------------------------------------------------------------
# CLI --json (exercise flags, not Rich --help)
# ---------------------------------------------------------------------------


def test_cli_json_failure_on_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Force collect_diff to return an empty diff so the gate fails deterministically
    # without touching real git state.
    import oh_no_my_claudecode.verifydiff.checker as checker_mod

    monkeypatch.setattr(checker_mod, "collect_diff", lambda repo_root, base: "")
    result = runner.invoke(app, ["verify-diff", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    rules = {f["rule"] for f in payload["findings"]}
    assert "non-empty" in rules


def test_cli_json_pass(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import oh_no_my_claudecode.verifydiff.checker as checker_mod

    monkeypatch.setattr(
        checker_mod,
        "collect_diff",
        lambda repo_root, base: _diff_add_function(),
    )
    result = runner.invoke(
        app,
        ["verify-diff", "--json", "--expect-symbol", "widget_total"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
