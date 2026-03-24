from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService


def test_brief_generation_writes_artifact(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    _, result = service.ingest()
    _, artifact = service.compile_brief("fix flaky cache invalidation bug in worker refresh flow")

    assert result.memory_count > 0
    assert "src/cache.py" in artifact.files_to_inspect
    assert any("pytest" in item.lower() for item in artifact.validation_checklist)
    assert artifact.output_path is not None
    assert Path(artifact.output_path).exists()
