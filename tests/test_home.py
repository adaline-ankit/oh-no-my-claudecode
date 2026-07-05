from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.home import list_known_repos, register_repo


def test_register_and_list_known_repos(tmp_path: Path) -> None:
    """A registered repo with a .onmc dir round-trips through the registry."""
    home = tmp_path / "home"
    repo = tmp_path / "repo-a"
    (repo / ".onmc").mkdir(parents=True)

    register_repo(repo, home=home)

    assert str(repo.resolve()) in list_known_repos(home=home)


def test_register_repo_is_idempotent(tmp_path: Path) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo-a"
    (repo / ".onmc").mkdir(parents=True)

    register_repo(repo, home=home)
    register_repo(repo, home=home)

    assert list_known_repos(home=home).count(str(repo.resolve())) == 1


def test_list_known_repos_prunes_stale_entries(tmp_path: Path) -> None:
    """Repos without a .onmc dir (deleted/reset) are filtered out on read."""
    home = tmp_path / "home"
    live = tmp_path / "repo-live"
    (live / ".onmc").mkdir(parents=True)
    stale = tmp_path / "repo-stale"
    stale.mkdir()  # exists but has no .onmc

    register_repo(live, home=home)
    register_repo(stale, home=home)

    known = list_known_repos(home=home)
    assert str(live.resolve()) in known
    assert str(stale.resolve()) not in known


def test_list_known_repos_empty_when_no_registry(tmp_path: Path) -> None:
    assert list_known_repos(home=tmp_path / "nope") == []
