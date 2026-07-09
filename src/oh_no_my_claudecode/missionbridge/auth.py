"""Mission-bridge auth — who may command a mission from a chat channel.

A deny-by-default allowlist, loaded from ``.onmc/mission-allowlist.json`` and
keyed by *channel-scoped* identity (``"slack:U123"`` / ``"telegram:456"``), so a
Slack ``U123`` is never the same principal as a Telegram ``U123``.

Security posture (see :class:`~oh_no_my_claudecode.missionbridge.models.AuthPolicy`):

- deny by default — an unknown identity is denied,
- an *empty* allowlist denies everyone unless ``open_when_empty`` is explicitly
  set (a single-user local opt-in), and
- **never allow on error** — a missing or malformed allowlist file resolves to
  an empty deny-by-default policy, not an open one.

Everything here is pure I/O over one small JSON file; the decision logic lives on
``AuthPolicy`` and stays trivially testable offline.
"""

from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.missionbridge.models import AuthDecision, AuthPolicy

ALLOWLIST_FILE_NAME = "mission-allowlist.json"


def allowlist_path(repo_root: Path) -> Path:
    """Return the path to the mission allowlist file for ``repo_root``."""
    return repo_root / ".onmc" / ALLOWLIST_FILE_NAME


def load_policy(repo_root: Path) -> AuthPolicy:
    """Load the mission :class:`AuthPolicy` from ``.onmc/mission-allowlist.json``.

    Deterministic and graceful: a missing file, unreadable file, malformed JSON,
    or unexpected shape all resolve to an empty deny-by-default policy
    (``open_when_empty=False``).  We never *widen* access on error.
    """
    empty = AuthPolicy(frozenset(), open_when_empty=False)
    target = allowlist_path(repo_root)
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return empty

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return empty
    if not isinstance(payload, dict):
        return empty

    allowed_raw = payload.get("allowed", [])
    allowed: frozenset[str] = (
        frozenset(item for item in allowed_raw if isinstance(item, str) and item)
        if isinstance(allowed_raw, list)
        else frozenset()
    )

    open_when_empty = payload.get("open_when_empty", False)
    if not isinstance(open_when_empty, bool):
        open_when_empty = False

    return AuthPolicy(allowed_identities=allowed, open_when_empty=open_when_empty)


def scoped_identity(channel: str, user_id: str) -> str:
    """Build the channel-scoped identity used by the allowlist."""
    return f"{channel}:{user_id}"


def authorize(policy: AuthPolicy, *, channel: str, user_id: str) -> AuthDecision:
    """Decide whether ``user_id`` on ``channel`` may command a mission.

    The identity is scoped as ``f"{channel}:{user_id}"`` before the allowlist is
    consulted, so identical user ids on different channels never collide.
    """
    return policy.decide(scoped_identity(channel, user_id))


def _write_policy(target: Path, allowed: frozenset[str], *, open_when_empty: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"allowed": sorted(allowed), "open_when_empty": open_when_empty}
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def add_identity(repo_root: Path, identity: str) -> Path:
    """Add ``identity`` to the allowlist file, idempotently.

    Preserves the existing ``open_when_empty`` flag and returns the file path.
    Adding an already-present identity is a no-op write of the same content.
    """
    policy = load_policy(repo_root)
    target = allowlist_path(repo_root)
    _write_policy(
        target,
        policy.allowed_identities | {identity},
        open_when_empty=policy.open_when_empty,
    )
    return target


def remove_identity(repo_root: Path, identity: str) -> Path:
    """Remove ``identity`` from the allowlist file, idempotently.

    Preserves the existing ``open_when_empty`` flag and returns the file path.
    Removing an absent identity is a no-op write of the same content.
    """
    policy = load_policy(repo_root)
    target = allowlist_path(repo_root)
    _write_policy(
        target,
        policy.allowed_identities - {identity},
        open_when_empty=policy.open_when_empty,
    )
    return target
