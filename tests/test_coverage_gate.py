"""Default coverage-backed false-green gate: parser + verdicts."""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.harness_run.controller import default_dependencies
from oh_no_my_claudecode.harness_run.coverage_gate import (
    changed_lines_from_diff,
    coverage_false_green_check,
)

DIFF = """\
diff --git a/pkg/mod.py b/pkg/mod.py
--- a/pkg/mod.py
+++ b/pkg/mod.py
@@ -10,3 +10,4 @@
 context
-old line
+new line ten plus one
+new line ten plus two
 tail
"""


class _Change:
    def __init__(self, diff_text: str) -> None:
        self.changed_files = ("pkg/mod.py",)
        self.diff_text = diff_text


def _report(tmp_path: Path, executed: list[int], missing: list[int] | None = None) -> None:
    payload = {
        "files": {"pkg/mod.py": {"executed_lines": executed, "missing_lines": missing or []}}
    }
    (tmp_path / "coverage.json").write_text(json.dumps(payload), encoding="utf-8")


def test_changed_lines_from_diff_tracks_new_file_numbers() -> None:
    assert changed_lines_from_diff(DIFF) == {"pkg/mod.py": {11, 12}}


def test_deleted_file_contributes_nothing() -> None:
    diff = "--- a/gone.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"
    assert changed_lines_from_diff(diff) == {}


def test_no_change_is_not_false_green(tmp_path: Path) -> None:
    check = coverage_false_green_check(tmp_path)
    assert check(None, (), _Change("")) is False


def test_missing_report_fails_closed(tmp_path: Path) -> None:
    check = coverage_false_green_check(tmp_path)
    assert check(None, (), _Change(DIFF)) is True


def test_unreadable_report_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "coverage.json").write_text("{ not json", encoding="utf-8")
    check = coverage_false_green_check(tmp_path)
    assert check(None, (), _Change(DIFF)) is True


def test_covered_change_clears(tmp_path: Path) -> None:
    _report(tmp_path, executed=[10, 11, 12, 13])
    check = coverage_false_green_check(tmp_path)
    assert check(None, (), _Change(DIFF)) is False


def test_unreached_change_is_false_green(tmp_path: Path) -> None:
    _report(tmp_path, executed=[10], missing=[11, 12])
    check = coverage_false_green_check(tmp_path)
    assert check(None, (), _Change(DIFF)) is True


def test_default_dependencies_wire_the_coverage_gate(tmp_path: Path) -> None:
    deps = default_dependencies(tmp_path)
    assert deps.verifier_false_green_check is not None
