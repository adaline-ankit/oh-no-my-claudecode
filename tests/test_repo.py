from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.repo import discover_repo_root


def test_discover_repo_root_from_nested_directory(sample_repo: Path) -> None:
    nested = sample_repo / "src"
    assert discover_repo_root(nested) == sample_repo
