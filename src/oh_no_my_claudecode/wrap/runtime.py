"""Durable completion contract for interactive Claude Code sessions.

Strict ``onmc wrap`` sessions arm a mission when a user submits an actionable
coding prompt. Claude Code's ``Stop`` hook then consults this state and refuses
premature completion until:

1. the workspace changed relative to the prompt-time baseline, and
2. the repository's detected verifier exits successfully.

The guard is deliberately bounded. It stops blocking after a fixed number of
attempts or wall-clock deadline, records why, and lets Claude return control to
the user. This prevents an evaluation hook from becoming an infinite token
loop.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

_SCHEMA_VERSION = 1
_DEFAULT_MAX_BLOCKS = 6
_DEFAULT_MAX_RUNTIME_SECONDS = 45 * 60
_VERIFY_TIMEOUT_SECONDS = 120
_UNTRACKED_HASH_LIMIT_BYTES = 8 * 1024 * 1024
_ACTION_RE = re.compile(
    r"\b(add|build|change|create|debug|fix|implement|migrate|refactor|remove|"
    r"repair|ship|test|update|write)\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(
    r"\b(api|app|bug|ci|class|cli|code|component|database|endpoint|feature|"
    r"function|module|package|pr|repo|repository|schema|service|test|tests|ui)\b",
    re.IGNORECASE,
)
_ALLOWED_VERIFIER_PREFIXES = {
    "cargo",
    "go",
    "make",
    "npm",
    "pnpm",
    "pytest",
    "python",
    "uv",
    "yarn",
}


def _parse_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("expected integer")
    return int(value)


def _parse_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("expected number")
    return float(value)


class MissionStatus(StrEnum):
    ACTIVE = "active"
    VERIFIED = "verified"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class InteractiveMission:
    schema_version: int
    session_id: str
    goal: str
    verifier: str
    baseline_fingerprint: str
    status: MissionStatus
    blocks_used: int
    max_blocks: int
    started_at: str
    deadline_at_epoch: float
    last_reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> InteractiveMission:
        return cls(
            schema_version=_parse_int(payload["schema_version"]),
            session_id=str(payload["session_id"]),
            goal=str(payload["goal"]),
            verifier=str(payload["verifier"]),
            baseline_fingerprint=str(payload["baseline_fingerprint"]),
            status=MissionStatus(str(payload["status"])),
            blocks_used=_parse_int(payload["blocks_used"]),
            max_blocks=_parse_int(payload["max_blocks"]),
            started_at=str(payload["started_at"]),
            deadline_at_epoch=_parse_float(payload["deadline_at_epoch"]),
            last_reason=str(payload.get("last_reason", "")),
        )


@dataclass(frozen=True, slots=True)
class CompletionDecision:
    block: bool
    reason: str
    status: MissionStatus

    def hook_output(self) -> str:
        if self.block:
            return json.dumps({"decision": "block", "reason": self.reason})
        if self.reason:
            return json.dumps({"systemMessage": self.reason})
        return ""


FingerprintReader = Callable[[Path], str]
VerifierRunner = Callable[[str, Path], tuple[bool, str]]


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(UTC)


def _mission_key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]


def mission_path(repo_root: Path, session_id: str) -> Path:
    return repo_root / ".onmc" / "runtime" / f"{_mission_key(session_id)}.json"


def prompt_is_coding_work(prompt: str) -> bool:
    """Return whether *prompt* requests a repository-changing coding outcome."""
    text = prompt.strip()
    return bool(text and _ACTION_RE.search(text) and _CODE_RE.search(text))


def detect_verifier(repo_root: Path) -> str | None:
    """Detect one conservative repository test command without executing it."""
    if (repo_root / "pyproject.toml").is_file() or (repo_root / "pytest.ini").is_file():
        return "pytest"
    package_json = repo_root / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        scripts = payload.get("scripts") if isinstance(payload, dict) else None
        if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
            return "npm test"
    if (repo_root / "Cargo.toml").is_file():
        return "cargo test"
    if (repo_root / "go.mod").is_file():
        return "go test ./..."
    makefile = repo_root / "Makefile"
    if makefile.is_file():
        try:
            if re.search(r"(?m)^test\s*:", makefile.read_text(encoding="utf-8")):
                return "make test"
        except OSError:
            pass
    return None


def workspace_fingerprint(repo_root: Path) -> str:
    """Hash tracked changes and untracked file contents relative to HEAD."""
    digest = hashlib.sha256()
    try:
        diff = subprocess.run(  # noqa: S603
            ["git", "diff", "--binary", "HEAD", "--"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=20,
        )
        digest.update(diff.stdout)
        untracked = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=20,
        )
        for raw_path in sorted(filter(None, untracked.stdout.split(b"\0"))):
            digest.update(raw_path)
            path = repo_root / os.fsdecode(raw_path)
            if path.is_file() and not path.is_symlink():
                digest.update(str(path.stat().st_size).encode("ascii"))
                with path.open("rb") as handle:
                    remaining = _UNTRACKED_HASH_LIMIT_BYTES
                    while remaining > 0 and (chunk := handle.read(min(1024 * 1024, remaining))):
                        digest.update(chunk)
                        remaining -= len(chunk)
        return digest.hexdigest()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_verifier(command: str, repo_root: Path) -> tuple[bool, str]:
    """Run a detected verifier with argv-only execution and bounded output."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return False, f"invalid verifier command: {exc}"
    if not argv or argv[0] not in _ALLOWED_VERIFIER_PREFIXES:
        return False, "verifier command is outside the ONMC allowlist"
    try:
        completed = subprocess.run(  # noqa: S603
            argv,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_VERIFY_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"verifier timed out after {_VERIFY_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return False, f"verifier unavailable: {exc}"
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode == 0, output[-1500:]


def _write_mission(path: Path, mission: InteractiveMission) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(mission)
    payload["status"] = mission.status.value
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_mission(repo_root: Path, session_id: str) -> InteractiveMission | None:
    path = mission_path(repo_root, session_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        mission = InteractiveMission.from_dict(payload)
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    return mission if mission.schema_version == _SCHEMA_VERSION else None


def arm_mission(
    repo_root: Path,
    session_id: str,
    prompt: str,
    *,
    strict: bool,
    now: datetime | None = None,
    verifier: str | None = None,
    fingerprint_reader: FingerprintReader = workspace_fingerprint,
) -> InteractiveMission | None:
    """Create a completion contract for a strict actionable coding prompt."""
    if not strict or not session_id or not prompt_is_coding_work(prompt):
        return None
    existing = load_mission(repo_root, session_id)
    if existing is not None and existing.status is MissionStatus.ACTIVE:
        return existing
    verify_command = verifier or detect_verifier(repo_root)
    if verify_command is None:
        return None
    moment = _now(now)
    mission = InteractiveMission(
        schema_version=_SCHEMA_VERSION,
        session_id=session_id,
        goal=prompt.strip(),
        verifier=verify_command,
        baseline_fingerprint=fingerprint_reader(repo_root),
        status=MissionStatus.ACTIVE,
        blocks_used=0,
        max_blocks=_DEFAULT_MAX_BLOCKS,
        started_at=moment.isoformat(),
        deadline_at_epoch=moment.timestamp() + _DEFAULT_MAX_RUNTIME_SECONDS,
    )
    _write_mission(mission_path(repo_root, session_id), mission)
    return mission


def evaluate_completion(
    repo_root: Path,
    session_id: str,
    *,
    strict: bool,
    now: datetime | None = None,
    fingerprint_reader: FingerprintReader = workspace_fingerprint,
    verifier_runner: VerifierRunner = run_verifier,
) -> CompletionDecision | None:
    """Evaluate a Stop event and persist an honest bounded decision."""
    if not strict or not session_id:
        return None
    mission = load_mission(repo_root, session_id)
    if mission is None or mission.status is not MissionStatus.ACTIVE:
        return None
    moment = _now(now)
    if mission.blocks_used >= mission.max_blocks or moment.timestamp() >= mission.deadline_at_epoch:
        reason = (
            "ONMC runtime budget exhausted before verified completion. "
            f"Last evidence: {mission.last_reason or 'none'}"
        )
        exhausted = InteractiveMission(
            **{
                **asdict(mission),
                "status": MissionStatus.EXHAUSTED,
                "last_reason": reason,
            }
        )
        _write_mission(mission_path(repo_root, session_id), exhausted)
        return CompletionDecision(False, reason, MissionStatus.EXHAUSTED)

    current = fingerprint_reader(repo_root)
    if not current or current == mission.baseline_fingerprint:
        passed = False
        evidence = "No repository change was observed after the mission started."
    else:
        passed, output = verifier_runner(mission.verifier, repo_root)
        evidence = (
            f"Verifier `{mission.verifier}` passed."
            if passed
            else f"Verifier `{mission.verifier}` failed:\n{output or '(no output)'}"
        )

    if passed:
        verified = InteractiveMission(
            **{
                **asdict(mission),
                "status": MissionStatus.VERIFIED,
                "last_reason": evidence,
            }
        )
        _write_mission(mission_path(repo_root, session_id), verified)
        return CompletionDecision(False, "", MissionStatus.VERIFIED)

    reason = (
        f"ONMC completion contract is not satisfied for: {mission.goal}\n"
        f"{evidence}\n"
        "Continue autonomously: inspect the evidence, make the smallest correct "
        "change, rerun the relevant tests, and do not ask the user for low-risk "
        "implementation choices."
    )
    blocked = InteractiveMission(
        **{
            **asdict(mission),
            "blocks_used": mission.blocks_used + 1,
            "last_reason": evidence,
        }
    )
    _write_mission(mission_path(repo_root, session_id), blocked)
    return CompletionDecision(True, reason, MissionStatus.ACTIVE)
