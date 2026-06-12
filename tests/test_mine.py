from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mine.extractor import _link_task
from oh_no_my_claudecode.mine.transcript import (
    claude_project_dir_name,
    discover_transcript_dir,
    discover_transcripts,
    parse_assistant_turns,
)
from oh_no_my_claudecode.models import LLMProviderType


def _assistant_line(
    content: list[dict[str, object]],
    *,
    is_sidechain: bool = False,
    uuid: str = "0c1a8a1e-0000-4000-8000-000000000001",
) -> str:
    """Build a transcript line shaped like a real Claude Code assistant turn."""
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": content,
                "model": "claude-fable-5",
            },
            "cwd": "/Users/example/code/sample-repo",
            "sessionId": "5f0e2a44-0000-4000-8000-00000000abcd",
            "timestamp": "2026-06-12T10:00:00.000Z",
            "uuid": uuid,
            "parentUuid": None,
            "gitBranch": "main",
            "isSidechain": is_sidechain,
            "version": "2.1.0",
        }
    )


def _user_line(text: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": text},
            "timestamp": "2026-06-12T09:59:00.000Z",
            "uuid": "0c1a8a1e-0000-4000-8000-0000000000aa",
            "isSidechain": False,
        }
    )


def test_project_dir_name_and_transcript_directory_detection(
    sample_repo: Path,
    monkeypatch: object,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("oh_no_my_claudecode.mine.transcript.Path.home", lambda: tmp_path)

    assert (
        claude_project_dir_name("/Users/ankit/Desktop/Adaline/pegasus1/pegasus")
        == "-Users-ankit-Desktop-Adaline-pegasus1-pegasus"
    )
    assert claude_project_dir_name("/home/dev/my_repo.v2") == "-home-dev-my-repo-v2"

    transcript_dir = discover_transcript_dir(sample_repo)

    expected_name = claude_project_dir_name(sample_repo.as_posix())
    assert expected_name.startswith("-")
    assert "/" not in expected_name
    assert transcript_dir == tmp_path / ".claude" / "projects" / expected_name


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
    session_path = transcript_dir / "5f0e2a44-0000-4000-8000-00000000abcd.jsonl"
    session_path.write_text(
        _assistant_line(
            [
                {"type": "text", "text": "Touched src/cache.py to debug the bug."},
                {
                    "type": "tool_use",
                    "name": "Edit",
                    "input": {"file_path": (sample_repo / "src" / "cache.py").as_posix()},
                },
            ]
        )
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
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    transcript = tmp_path / "5f0e2a44-0000-4000-8000-00000000abcd.jsonl"
    transcript.write_text(
        "\n".join(
            [
                _user_line("Please fix src/cache.py"),
                _assistant_line(
                    [
                        {"type": "thinking", "thinking": "Secret scratchpad reasoning."},
                        {"type": "text", "text": "I inspected the cache module."},
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": (repo_root / "src" / "cache.py").as_posix()},
                        },
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "/etc/hosts"},
                        },
                    ]
                ),
                json.dumps({"type": "summary", "summary": "Cache fix session"}),
                json.dumps({"type": "system", "content": "hook ran"}),
                "{not valid json at all",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    text, files = parse_assistant_turns(transcript, repo_root=repo_root)

    assert "Please fix" not in text
    assert "Secret scratchpad" not in text
    assert "Cache fix session" not in text
    assert "I inspected the cache module." in text
    assert files == ["/etc/hosts", "src/cache.py"]


def test_parse_assistant_turns_skips_sidechain_lines(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                _assistant_line(
                    [
                        {"type": "text", "text": "Subagent noise."},
                        {
                            "type": "tool_use",
                            "name": "Write",
                            "input": {"file_path": (repo_root / "ignored.py").as_posix()},
                        },
                    ],
                    is_sidechain=True,
                ),
                _assistant_line(
                    [{"type": "text", "text": "Main thread conclusion."}],
                    uuid="0c1a8a1e-0000-4000-8000-000000000002",
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    text, files = parse_assistant_turns(transcript, repo_root=repo_root)

    assert "Subagent noise" not in text
    assert "Main thread conclusion." in text
    assert files == []


def test_parse_assistant_turns_does_not_scrape_paths_from_text(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        _assistant_line(
            [
                {
                    "type": "text",
                    "text": "See https://example.com/docs and bump to v1.2.3 in src/cache.py.",
                }
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    text, files = parse_assistant_turns(transcript)

    assert "bump to v1.2.3" in text
    assert files == []


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
