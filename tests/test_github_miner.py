from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.mine.github_miner import (
    GitHubPRFinding,
    fetch_prs,
    get_github_remote,
    mine_github_prs,
)
from oh_no_my_claudecode.models import LLMProviderType, SourceType


def test_get_github_remote_parses_https_and_ssh(sample_repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/widgets.git"],
        cwd=sample_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert get_github_remote(sample_repo) == ("acme", "widgets")

    subprocess.run(
        ["git", "remote", "set-url", "origin", "git@github.com:acme/widgets.git"],
        cwd=sample_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    assert get_github_remote(sample_repo) == ("acme", "widgets")


def test_get_github_remote_returns_none_for_non_github(sample_repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.com/acme/widgets.git"],
        cwd=sample_repo,
        check=True,
        capture_output=True,
        text=True,
    )

    assert get_github_remote(sample_repo) is None


def test_fetch_prs_with_mocked_http_response(monkeypatch: object) -> None:
    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps([{"number": 1, "title": "Fix cache"}]).encode("utf-8")

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _Response())

    payload = fetch_prs("acme", "widgets")

    assert payload == [{"number": 1, "title": "Fix cache"}]


def test_mine_github_prs_stores_records_with_github_source(
    sample_repo: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.chdir(sample_repo)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/widgets.git"],
        cwd=sample_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    service = OnmcService(sample_repo)
    repo_root, _ = service.init_project()
    service.configure_llm(
        provider=LLMProviderType.MOCK,
        model="mock-model",
        api_key_env_var=None,
        temperature=0.0,
        max_tokens=1200,
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.mine.github_miner.fetch_prs",
        lambda owner, repo, limit=50: [{"number": 42, "title": "Cache boundary"}],
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.mine.github_miner.fetch_pr_reviews",
        lambda owner, repo, pr_number: [{"body": "Do not bypass cache boundary."}],
    )
    monkeypatch.setattr(
        "oh_no_my_claudecode.mine.github_miner.extract_github_pr_findings",
        lambda **kwargs: [
            GitHubPRFinding(
                kind="decision",
                title="Keep cache boundary",
                summary="Reviewers preserved the shared cache boundary.",
                confidence=0.9,
                source_pr=42,
            )
        ],
    )

    result = service.mine(github=True)
    memories = service.list_memories(source_type=SourceType.GITHUB_PR)

    assert result["message"] is not None
    assert len(memories) == 1
    assert memories[0].source_type == SourceType.GITHUB_PR
    assert memories[0].source_ref == "pr:42"


def test_mine_github_prs_handles_missing_remote(sample_repo: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(sample_repo)
    service = OnmcService(sample_repo)
    repo_root, config = service.init_project()
    storage = service._load_context()[2]

    result = mine_github_prs(
        repo_root=repo_root,
        storage=storage,
        provider=None,
        log_path=service._llm_log_path(repo_root, config),
    )

    assert result["message"] == "No GitHub remote found. Skipping GitHub PR mining."


def test_fetch_prs_handles_github_api_error(monkeypatch: object) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError(
            url="https://api.github.com/repos/acme/widgets/pulls",
            code=403,
            msg="rate limited",
            hdrs=None,
            fp=io.BytesIO(b"{}"),
        )

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    assert fetch_prs("acme", "widgets") == []
