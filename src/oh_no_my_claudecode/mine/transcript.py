from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_no_my_claudecode.utils.time import parse_datetime, utc_now

_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")
_TOOL_INPUT_PATH_KEYS = ("file_path", "path", "notebook_path")


def claude_project_dir_name(repo_root: str) -> str:
    """Return the Claude Code project directory name for an absolute repo path.

    Claude Code stores transcripts under ``~/.claude/projects/<name>/`` where
    ``<name>`` is the absolute repo path with every character outside
    ``[A-Za-z0-9]`` replaced by ``-``. For example
    ``/Users/ankit/code/my_repo`` becomes ``-Users-ankit-code-my-repo``
    (note the leading ``-`` from the leading ``/``).
    """
    return _NON_ALNUM_RE.sub("-", repo_root)


def discover_transcript_dir(repo_root: Path) -> Path:
    """Return the Claude Code transcript directory for the repo.

    Session files (``<session-uuid>.jsonl``) live directly inside this
    directory; there is no ``sessions/`` subdirectory.
    """
    return Path.home() / ".claude" / "projects" / claude_project_dir_name(repo_root.as_posix())


def discover_transcripts(
    repo_root: Path,
    *,
    session_id: str | None = None,
    since: str | None = None,
) -> list[Path]:
    """Return transcript files for the repo, optionally filtered by session or time."""
    transcript_dir = discover_transcript_dir(repo_root)
    if not transcript_dir.exists():
        return []
    candidates = sorted(transcript_dir.glob("*.jsonl"))
    if session_id is not None:
        candidates = [path for path in candidates if path.stem == session_id]
    if since is not None:
        cutoff = _parse_since(since)
        candidates = [
            path
            for path in candidates
            if _mtime_datetime(path) >= cutoff
        ]
    return candidates


def parse_assistant_turns(path: Path, *, repo_root: Path | None = None) -> tuple[str, list[str]]:
    """Extract assistant turn text and touched files from a Claude Code transcript.

    Each transcript line is a JSON object with a top-level ``type``. Only
    main-thread assistant lines are read: ``type == "assistant"`` with
    ``isSidechain`` falsy (sidechain lines come from subagents, so mined
    memory reflects the main conversation). All other line types ("user",
    "summary", "system", ...) and malformed lines are skipped silently.

    Text is taken from ``message.content`` blocks of type ``"text"``.
    ``"thinking"`` blocks are ignored — they are not durable output. File
    paths are taken only from ``"tool_use"`` blocks' ``input`` (the
    ``file_path``, ``path``, and ``notebook_path`` keys); free-text content
    is never scanned for paths because that produced garbage like URLs and
    version numbers. Absolute paths under ``repo_root`` are rewritten to
    repo-relative POSIX form; paths outside the repo are kept as-is so
    callers can still see cross-repo touches.
    """
    turns: list[str] = []
    files: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "assistant":
            continue
        if payload.get("isSidechain"):
            continue
        message = payload.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif block_type == "tool_use":
                files.update(_tool_use_paths(block, repo_root))
        if parts:
            turns.append("\n".join(parts))
    return "\n\n".join(turns), sorted(files)


def _tool_use_paths(block: dict[str, object], repo_root: Path | None) -> set[str]:
    paths: set[str] = set()
    tool_input = block.get("input")
    if not isinstance(tool_input, dict):
        return paths
    for key in _TOOL_INPUT_PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            paths.add(_normalize_path(value.strip(), repo_root))
    return paths


def _normalize_path(value: str, repo_root: Path | None) -> str:
    candidate = Path(value)
    if repo_root is None or not candidate.is_absolute():
        return value
    for root in (repo_root, repo_root.resolve()):
        try:
            return candidate.relative_to(root).as_posix()
        except ValueError:
            continue
    return value


def _parse_since(value: str) -> datetime:
    stripped = value.strip().lower()
    now = utc_now()
    if stripped.endswith("days ago"):
        count = int(stripped.split()[0])
        return now - timedelta(days=count)
    if stripped.endswith("day ago"):
        return now - timedelta(days=1)
    if stripped.endswith("hours ago"):
        count = int(stripped.split()[0])
        return now - timedelta(hours=count)
    if stripped.endswith("hour ago"):
        return now - timedelta(hours=1)
    parsed = parse_datetime(value)
    return parsed or now


def _mtime_datetime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
