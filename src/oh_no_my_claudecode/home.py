"""Machine-wide registry of onmc repos, for the global ("all projects") dashboard.

onmc is normally scoped to one repo. The dashboard's global mode needs to know
*every* repo you've used onmc in so it can show all your agent activity in one
place — the local, zero-infra equivalent of a hosted "all projects" view.

The registry is a small JSON list of repo roots at ``~/.onmc/known_repos.json``.
It is populated best-effort whenever ``onmc ui`` runs in a repo, and pruned on
read to the repos that still exist and still have a ``.onmc`` state dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.config import user_state_dir

_KNOWN_REPOS_NAME = "known_repos.json"


def known_repos_path(home: Path | None = None) -> Path:
    """Return the path to the known-repos registry (``~/.onmc/known_repos.json``)."""
    return user_state_dir(home) / _KNOWN_REPOS_NAME


def register_repo(repo_root: Path, home: Path | None = None) -> None:
    """Remember *repo_root* in the machine-wide registry. Idempotent, best-effort.

    Never raises — a registry write failure must not break the CLI.
    """
    try:
        root = str(Path(repo_root).resolve())
        path = known_repos_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = _read_raw(path)
        if root not in current:
            current.append(root)
        path.write_text(json.dumps(sorted(set(current)), indent=0), encoding="utf-8")
    except OSError:
        pass


def list_known_repos(home: Path | None = None) -> list[str]:
    """Return registered repo roots that still exist and still have a ``.onmc`` dir.

    Deterministic (sorted) and self-healing: stale entries (deleted repos, or
    repos whose ``.onmc`` was removed) are filtered out of the result.
    """
    out: list[str] = []
    for item in _read_raw(known_repos_path(home)):
        candidate = Path(item)
        if (candidate / ".onmc").is_dir():
            out.append(str(candidate))
    return sorted(set(out))


def _read_raw(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(x) for x in data] if isinstance(data, list) else []
