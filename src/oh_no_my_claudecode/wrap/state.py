"""Persistent state + CLAUDE.md stanza management for the ``onmc wrap`` layer.

The wrap hooks (``onmc hooks task-intercept`` / ``onmc hooks prompt-router``)
are mode-agnostic command strings in ``settings.json`` so ``unwrap`` can remove
them verbatim. The strict-vs-soft mode is read at hook time from a tiny state
file written by ``onmc wrap``:

    ``.onmc/wrap.json`` → ``{"strict": true|false, "wrapped_at": "<iso>"}``

``onmc wrap`` also injects a fenced policy stanza into the repo's ``CLAUDE.md``
so the model is told, in-context, that onmc is the default layer. ``onmc
unwrap`` removes exactly that stanza (and the state file), leaving the rest of
CLAUDE.md byte-for-byte intact.

Every reader here fails open (returns a safe default) — wrap state is advisory,
never load-bearing for whether Claude Code keeps working.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "CLAUDE_MD_BEGIN",
    "CLAUDE_MD_END",
    "read_wrap_strict",
    "remove_claude_md_stanza",
    "remove_wrap_state",
    "upsert_claude_md_stanza",
    "wrap_state_path",
    "write_wrap_state",
]

CLAUDE_MD_BEGIN = "<!-- onmc:wrap:begin -->"
CLAUDE_MD_END = "<!-- onmc:wrap:end -->"

_STANZA_BODY = """\
## onmc is the active layer

`onmc wrap` is active for this repo. Prefer onmc paths over raw Claude Code
defaults:

- Fan-out work via `onmc swarm plan` (receipted), not raw `Task` subagents.
- Recall prior context with `onmc recall` and check `onmc guard` for dead-ends
  before retrying an approach.
- Iterate to green with `onmc loop`; run `onmc preflight` before declaring done.

Remove this layer at any time with `onmc unwrap`.\
"""


def wrap_state_path(repo_root: Path) -> Path:
    """Return the ``.onmc/wrap.json`` state-file path for *repo_root*."""
    return repo_root / ".onmc" / "wrap.json"


def write_wrap_state(repo_root: Path, *, strict: bool, now: datetime | None = None) -> Path:
    """Write the wrap-state file recording the active mode. Returns its path."""
    path = wrap_state_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    moment = now if now is not None else datetime.now(UTC)
    path.write_text(
        json.dumps({"strict": bool(strict), "wrapped_at": moment.isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def read_wrap_strict(repo_root: Path, *, default: bool = True) -> bool:
    """Return the recorded strict flag, or *default* when state is unreadable.

    The default is ``True`` (strict): if a wrap hook is firing at all, the
    settings.json command was installed by ``onmc wrap``, so the safer reading
    of a missing/garbled state file is the stricter policy.
    """
    path = wrap_state_path(repo_root)
    if not path.is_file():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if isinstance(data, dict) and isinstance(data.get("strict"), bool):
        return bool(data["strict"])
    return default


def remove_wrap_state(repo_root: Path) -> bool:
    """Delete the wrap-state file if present. Returns whether it was removed."""
    path = wrap_state_path(repo_root)
    try:
        if path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def claude_md_path(repo_root: Path) -> Path:
    """Return the repo-root ``CLAUDE.md`` path."""
    return repo_root / "CLAUDE.md"


def _stanza_block() -> str:
    """Return the full fenced stanza (begin marker … body … end marker)."""
    return f"{CLAUDE_MD_BEGIN}\n{_STANZA_BODY}\n{CLAUDE_MD_END}"


def upsert_claude_md_stanza(repo_root: Path) -> Path:
    """Insert (or refresh) the onmc-wrap policy stanza in ``CLAUDE.md``.

    Idempotent: if the marked stanza already exists it is replaced in place;
    otherwise the stanza is appended. A missing CLAUDE.md is created with just
    the stanza. Returns the CLAUDE.md path.
    """
    path = claude_md_path(repo_root)
    block = _stanza_block()
    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    stripped = _strip_stanza(existing)
    if not stripped.strip():
        new_text = block + "\n"
    else:
        # Append the stanza after the existing content, separated by a blank line.
        new_text = stripped.rstrip("\n") + "\n\n" + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return path


def remove_claude_md_stanza(repo_root: Path) -> bool:
    """Remove the onmc-wrap stanza from ``CLAUDE.md``. Returns whether changed.

    Restores CLAUDE.md to its pre-wrap content: the marked block is removed and
    the surrounding whitespace normalised back to a single trailing newline. If
    removing the stanza empties the file *and* the file did not exist before
    wrap (i.e. it contained only the stanza), the file is deleted.
    """
    path = claude_md_path(repo_root)
    if not path.is_file():
        return False
    try:
        existing = path.read_text(encoding="utf-8")
    except OSError:
        return False
    if CLAUDE_MD_BEGIN not in existing:
        return False
    stripped = _strip_stanza(existing)
    if not stripped.strip():
        try:
            path.unlink()
        except OSError:
            return False
        return True
    path.write_text(stripped.rstrip("\n") + "\n", encoding="utf-8")
    return True


def _strip_stanza(text: str) -> str:
    """Remove every onmc-wrap fenced block from *text*, tidying blank lines.

    Tolerates a begin marker with a missing end marker (strips to EOF) so a
    half-written stanza never lingers.
    """
    if CLAUDE_MD_BEGIN not in text:
        return text
    out = text
    while CLAUDE_MD_BEGIN in out:
        start = out.index(CLAUDE_MD_BEGIN)
        end_idx = out.find(CLAUDE_MD_END, start)
        if end_idx == -1:
            out = out[:start]
            break
        end = end_idx + len(CLAUDE_MD_END)
        out = out[:start] + out[end:]
    # Collapse the blank-line gap the removed block leaves behind.
    while "\n\n\n" in out:
        out = out.replace("\n\n\n", "\n\n")
    return out
