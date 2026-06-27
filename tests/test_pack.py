from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from oh_no_my_claudecode.cli import app
from oh_no_my_claudecode.core.service import OnmcService

runner = CliRunner()


def test_pack_builds_bounded_context(sample_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest(no_llm=True)

    pack = service.pack("fix cache invalidation bug", budget_chars=1800)

    assert pack.goal == "fix cache invalidation bug"
    assert len(pack.markdown) <= 1800
    assert "# ONMC Context Pack" in pack.markdown
    assert "src/cache.py" in pack.markdown
    assert pack.suggested_verify


def test_pack_budget_truncates_deterministically(sample_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest(no_llm=True)

    first = service.pack("cache worker tests invalidation", budget_chars=600)
    second = service.pack("cache worker tests invalidation", budget_chars=600)

    assert first.markdown == second.markdown
    assert len(first.markdown) <= 600
    assert first.truncated is True


def test_pack_cli_json_and_out(sample_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest(no_llm=True)

    result = runner.invoke(app, ["pack", "fix cache invalidation", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["goal"] == "fix cache invalidation"
    assert "markdown" in payload

    out = sample_repo / "pack.md"
    write_result = runner.invoke(app, ["pack", "fix cache invalidation", "--out", str(out)])
    assert write_result.exit_code == 0, write_result.stdout
    assert out.exists()
    assert "# ONMC Context Pack" in out.read_text(encoding="utf-8")
