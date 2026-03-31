from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mine.extractor import _link_task
from oh_no_my_claudecode.mine.transcript import (
    claude_project_hash,
    discover_transcript_dir,
    discover_transcripts,
    parse_assistant_turns,
)
from oh_no_my_claudecode.models import LLMProviderType


def test_project_hash_and_transcript_directory_detection(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    project_hash = claude_project_hash(sample_repo.as_posix())
    transcript_dir = discover_transcript_dir(sample_repo)

    assert len(project_hash) == 16
    assert transcript_dir == tmp_path / ".claude" / "projects" / project_hash / "sessions"


def test_mine_dry_run_does_not_write_to_db(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)
    service = OnmcService(sample_repo)
    service.init_project()
    service.ingest()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )
    task = service.start_task(
        title="Fix src/cache.py behavior",
        description="Investigate src/cache.py and tests/test_cache.py",
        labels=["mine"],
    )
    transcript_dir = discover_transcript_dir(sample_repo)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    session_path = transcript_dir / "session-1.jsonl"
    session_path.write_text(
        json.dumps({"role": "assistant", "content": "Touched src/cache.py to debug the bug."})
        + "\n",
        encoding="utf-8",
    )

    result = service.mine(dry_run=True)

    assert result["message"] is None
    assert service.list_attempts_for_task(task.task_id) == []


def test_task_linking_uses_file_overlap_tokens(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    service.init_project()
    task = service.start_task(
        title="Fix src/cache.py",
        description="Update src/cache.py and tests/test_cache.py",
        labels=[],
    )

    linked = _link_task([task], ["src/cache.py", "tests/test_cache.py"])

    assert linked is not None
    assert linked.task_id == task.task_id


def test_parse_assistant_turns_excludes_user_turns(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"role": "user", "content": "Please fix src/cache.py"}),
                json.dumps(
                    {
                        "role": "assistant",
                        "content": "I inspected src/cache.py and tests/test_cache.py.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    text, files = parse_assistant_turns(transcript)

    assert "Please fix" not in text
    assert "inspected src/cache.py" in text
    assert files == ["src/cache.py", "tests/test_cache.py"]


def test_mine_handles_missing_transcript_directory_gracefully(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(sample_repo)
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)
    service = OnmcService(sample_repo)
    service.init_project()

    result = service.mine(dry_run=True, no_llm=True)

    assert result["message"] == "No Claude Code sessions found for this repo yet."
    assert discover_transcripts(sample_repo) == []
