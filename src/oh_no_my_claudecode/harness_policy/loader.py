"""Load and persist the repo-scoped harness policy from ``.onmc/policy.json``.

Absent or malformed files fall back to the safe permissive default so a repo
without an explicit policy still gets secret scanning and destructive-command
denial rather than silently running unguarded.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import HarnessPolicy

POLICY_FILE = "policy.json"


def policy_dir(repo_root: Path) -> Path:
    """Return the directory holding the policy file (``<repo>/.onmc``)."""
    return Path(repo_root) / ".onmc"


def load_policy(*, policy_dir: Path) -> HarnessPolicy:
    """Load the policy from *policy_dir*/policy.json, or the safe default.

    A malformed policy file is a *hard* error — silently degrading to the
    permissive default would let a typo disable the guardrails the author
    believed were active.
    """
    path = policy_dir / POLICY_FILE
    if not path.exists():
        return HarnessPolicy.permissive()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"policy file is unreadable: {path} ({exc})") from exc
    return HarnessPolicy.from_dict(payload)


def save_policy(policy: HarnessPolicy, *, policy_dir: Path) -> Path:
    """Persist *policy* to *policy_dir*/policy.json and return the path."""
    policy_dir.mkdir(parents=True, exist_ok=True)
    path = policy_dir / POLICY_FILE
    path.write_text(
        json.dumps(policy.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


__all__ = ["POLICY_FILE", "load_policy", "policy_dir", "save_policy"]
