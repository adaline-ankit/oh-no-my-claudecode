from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from oh_no_my_claudecode.utils.time import parse_datetime, utc_now


def claude_project_hash(repo_root: str) -> str:
    """Return the Claude Code project hash for a repo path."""
    return hashlib.sha256(repo_root.encode("utf-8")).hexdigest()[:16]


def discover_transcript_dir(repo_root: Path) -> Path:
    """Return the Claude Code transcript directory for the repo."""
    project_hash = claude_project_hash(repo_root.as_posix())
    return Path.home() / ".claude" / "projects" / project_hash / "sessions"


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


def parse_assistant_turns(path: Path) -> tuple[str, list[str]]:
    """Extract assistant-only turns and mentioned files from a transcript."""
    turns: list[str] = []
    files: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        role = str(payload.get("role", payload.get("speaker", ""))).lower()
        if role != "assistant":
            continue
        content = _extract_content(payload)
        if not content:
            continue
        turns.append(content)
        files.update(_extract_files(payload, content))
    return "\n\n".join(turns), sorted(files)


def _extract_content(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    message = payload.get("message")
    if isinstance(message, str):
        return message
    return ""


def _extract_files(payload: dict[str, object], content: str) -> set[str]:
    files: set[str] = set()
    for key in ("files_touched", "files", "paths"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    files.add(item)
    for token in content.split():
        if "/" in token and "." in token:
            files.add(token.strip("`.,:;()[]{}"))
    return {item for item in files if item}


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


def _mtime_iso(path: Path) -> str:
    return _mtime_datetime(path).isoformat()


def _mtime_datetime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
