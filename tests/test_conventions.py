"""Tests for ``onmc conventions`` — capture + inherit repo conventions.

Coverage
--------
- detect_conventions reads a seeded pyproject's [tool.ruff] line-length, select
  rule codes, target-version, and [tool.mypy] strict.
- Missing keys (and a missing/blank pyproject) degrade gracefully to defaults.
- render_conventions_markdown is deterministic and lists the fixed norms.
- capture writes .onmc/conventions.md and is idempotent; --force re-writes.
- show emits the fixed norms; --json output has the expected shape.
- Everything offline + deterministic; no Rich --help text is asserted — the CLI
  is exercised via flags and the JSON / file outcomes instead.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.conventions import (
    CONVENTIONS_FILE_NAME,
    Conventions,
    conventions_path,
    detect_conventions,
    render_conventions_markdown,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEEDED_PYPROJECT = textwrap.dedent(
    """
    [tool.ruff]
    target-version = "py311"
    line-length = 100

    [tool.ruff.lint]
    select = ["E", "F", "I", "B", "SIM"]

    [tool.mypy]
    strict = true
    """
).strip()


def _runner() -> CliRunner:
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _seed_pyproject(repo_root: Path, body: str) -> None:
    (repo_root / "pyproject.toml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Unit: detect_conventions
# ---------------------------------------------------------------------------


def test_detect_reads_ruff_and_mypy(tmp_path: Path) -> None:
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    conv = detect_conventions(tmp_path)
    assert conv.line_length == 100
    assert conv.ruff_rule_codes == ["E", "F", "I", "B", "SIM"]
    assert conv.target_version == "py311"
    assert conv.type_checked is True


def test_detect_missing_pyproject_is_graceful(tmp_path: Path) -> None:
    conv = detect_conventions(tmp_path)
    assert conv.line_length is None
    assert conv.ruff_rule_codes == []
    assert conv.target_version is None
    assert conv.type_checked is False
    # Fixed norms are always attached.
    assert len(conv.norms) == 3


def test_detect_missing_keys_are_graceful(tmp_path: Path) -> None:
    _seed_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [tool.ruff]
            line-length = 88
            """
        ).strip(),
    )
    conv = detect_conventions(tmp_path)
    assert conv.line_length == 88
    # select / target-version / mypy.strict all absent → defaults
    assert conv.ruff_rule_codes == []
    assert conv.target_version is None
    assert conv.type_checked is False


def test_detect_malformed_pyproject_is_graceful(tmp_path: Path) -> None:
    _seed_pyproject(tmp_path, "this is = = not valid toml [[[")
    conv = detect_conventions(tmp_path)
    assert conv.line_length is None
    assert conv.ruff_rule_codes == []


def test_detect_is_deterministic(tmp_path: Path) -> None:
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    first = detect_conventions(tmp_path)
    second = detect_conventions(tmp_path)
    assert first == second


def test_detect_strict_false_is_not_type_checked(tmp_path: Path) -> None:
    _seed_pyproject(
        tmp_path,
        textwrap.dedent(
            """
            [tool.mypy]
            strict = false
            """
        ).strip(),
    )
    conv = detect_conventions(tmp_path)
    assert conv.type_checked is False


# ---------------------------------------------------------------------------
# Unit: render_conventions_markdown
# ---------------------------------------------------------------------------


def test_render_markdown_contains_settings_and_norms() -> None:
    conv = Conventions(
        line_length=100,
        ruff_rule_codes=["E", "F"],
        target_version="py311",
        type_checked=True,
    )
    body = render_conventions_markdown(conv)
    assert "Line length: 100" in body
    assert "py311" in body
    assert "E, F" in body
    assert "mypy --strict" in body
    for norm in conv.norms:
        assert norm in body


def test_render_markdown_handles_unset(tmp_path: Path) -> None:
    conv = detect_conventions(tmp_path)  # nothing seeded → all defaults
    body = render_conventions_markdown(conv)
    assert "Line length: unset" in body
    assert "Ruff rule codes: unset" in body
    assert "Type checked: no" in body


def test_render_markdown_is_deterministic() -> None:
    conv = Conventions(line_length=100, ruff_rule_codes=["E"], target_version="py311")
    assert render_conventions_markdown(conv) == render_conventions_markdown(conv)


# ---------------------------------------------------------------------------
# CLI: capture
# ---------------------------------------------------------------------------


def test_capture_writes_conventions_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    monkeypatch.chdir(tmp_path)
    result = _runner().invoke(app, ["conventions", "capture"])
    assert result.exit_code == 0
    out = conventions_path(tmp_path)
    assert out.name == CONVENTIONS_FILE_NAME
    assert out.exists()
    body = out.read_text(encoding="utf-8")
    assert "Line length: 100" in body


def test_capture_is_idempotent(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(app, ["conventions", "capture"])
    out = conventions_path(tmp_path)
    # Tamper with the file; a no-force re-run must NOT overwrite it.
    out.write_text("SENTINEL", encoding="utf-8")
    result = runner.invoke(app, ["conventions", "capture"])
    assert result.exit_code == 0
    assert out.read_text(encoding="utf-8") == "SENTINEL"


def test_capture_force_rewrites(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    monkeypatch.chdir(tmp_path)
    runner = _runner()
    runner.invoke(app, ["conventions", "capture"])
    out = conventions_path(tmp_path)
    out.write_text("SENTINEL", encoding="utf-8")
    result = runner.invoke(app, ["conventions", "capture", "--force"])
    assert result.exit_code == 0
    body = out.read_text(encoding="utf-8")
    assert body != "SENTINEL"
    assert "Line length: 100" in body


# ---------------------------------------------------------------------------
# CLI: show
# ---------------------------------------------------------------------------


def test_show_json_shape(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    monkeypatch.chdir(tmp_path)
    result = _runner().invoke(app, ["conventions", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["line_length"] == 100
    assert payload["ruff_rule_codes"] == ["E", "F", "I", "B", "SIM"]
    assert payload["target_version"] == "py311"
    assert payload["type_checked"] is True
    assert len(payload["norms"]) == 3


def test_show_json_emits_norms(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)  # no pyproject → defaults, but norms still present
    result = _runner().invoke(app, ["conventions", "show", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    norms = payload["norms"]
    assert any("Conventional Commits" in norm for norm in norms)
    assert any("schema migration" in norm for norm in norms)
    assert any("deterministic" in norm for norm in norms)


def test_show_does_not_write_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _seed_pyproject(tmp_path, _SEEDED_PYPROJECT)
    monkeypatch.chdir(tmp_path)
    result = _runner().invoke(app, ["conventions", "show"])
    assert result.exit_code == 0
    assert not conventions_path(tmp_path).exists()
