"""Pure, deterministic core for the ``soundboard`` feature.

This module owns:

- :data:`DEFAULTS` — the built-in event→reaction map.
- :class:`Reaction` — a lightweight wrapper around a reaction string that
  exposes ``text`` (the printable part) and ``has_bell`` (whether ``\\a`` is
  appended).
- :func:`react` — resolve an event to its :class:`Reaction` given a merged
  bindings dict.
- :func:`load_bindings` / :func:`save_bindings` — read and write the user's
  ``.onmc/soundboard/bindings.json`` override file.
- :func:`merged_bindings` — merge :data:`DEFAULTS` with user overrides so the
  caller never has to think about fallback order.

All functions are **pure over in-memory data** and accept an injectable
``soundboard_dir: Path`` so tests can run without touching the real filesystem.
No external deps — stdlib only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Sub-directory under the repo/home root where soundboard state lives.
SOUNDBOARD_SUBDIR: Path = Path(".onmc") / "soundboard"

#: JSON file holding user binding overrides.
BINDINGS_FILE: str = "bindings.json"

#: Terminal bell character (opt-in, never emitted by default).
_BELL: str = "\a"

# ---------------------------------------------------------------------------
# Reaction dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reaction:
    """A soundboard reaction for a single event.

    Attributes
    ----------
    event:
        The event name this reaction belongs to (e.g. ``"test_pass"``).
    text:
        The printable reaction string (emoji / ASCII art / short phrase).
    has_bell:
        ``True`` when a terminal bell (``\\a``) is appended on emit.
    """

    event: str
    text: str
    has_bell: bool = False

    def emit(self) -> str:
        """Return the full string to print (text + optional bell)."""
        return self.text + (_BELL if self.has_bell else "")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON output."""
        return {"event": self.event, "text": self.text, "has_bell": self.has_bell}


# ---------------------------------------------------------------------------
# Default reaction map
# ---------------------------------------------------------------------------

#: Built-in event → reaction text map.  Keys are the canonical event names.
#: Values are the printable reaction strings (no bell by default).
DEFAULTS: dict[str, str] = {
    # Success
    "test_pass": "🎉 ding!",
    "build_pass": "✅ green!",
    "pr_merged": "🚀 shipped!",
    "deploy_done": "🌐 live!",
    "task_complete": "🏁 done!",
    # Failure / break
    "build_break": "💥 womp womp",
    "test_fail": "🔴 oops",
    "pr_rejected": "😬 back to the drawing board",
    "deploy_fail": "🔥 it's on fire",
    "lint_error": "🚨 linter not happy",
    # Progress / info
    "commit_made": "📦 committed",
    "branch_created": "🌿 branching out",
    "review_requested": "👀 eyes on it",
    "comment_added": "💬 noted",
    "file_saved": "💾 saved",
    # Workflow
    "session_start": "👋 hello!",
    "session_end": "👋 bye!",
    "agent_idle": "🥱 waiting...",
    "agent_thinking": "🤔 hmm...",
    "rate_limited": "⏳ hold on...",
}


# ---------------------------------------------------------------------------
# Bindings I/O
# ---------------------------------------------------------------------------


def load_bindings(soundboard_dir: Path) -> dict[str, str]:
    """Load user binding overrides from ``bindings.json``.

    Returns an empty dict if the file is absent or malformed.

    Parameters
    ----------
    soundboard_dir:
        The ``.onmc/soundboard/`` directory (injectable for tests).
    """
    path = soundboard_dir / BINDINGS_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def save_bindings(bindings: dict[str, str], soundboard_dir: Path) -> None:
    """Persist *bindings* to ``bindings.json``.

    Creates parent directories if they do not exist.

    Parameters
    ----------
    bindings:
        The full user override dict to persist.
    soundboard_dir:
        The ``.onmc/soundboard/`` directory (injectable for tests).
    """
    soundboard_dir.mkdir(parents=True, exist_ok=True)
    path = soundboard_dir / BINDINGS_FILE
    path.write_text(
        json.dumps(bindings, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Merged bindings + react
# ---------------------------------------------------------------------------


def merged_bindings(user_bindings: dict[str, str]) -> dict[str, str]:
    """Return the effective event→text map (defaults overridden by *user_bindings*).

    Parameters
    ----------
    user_bindings:
        The dict returned by :func:`load_bindings`.  May be empty.
    """
    result = dict(DEFAULTS)
    result.update(user_bindings)
    return result


def react(event: str, bindings: dict[str, str]) -> Reaction:
    """Resolve *event* to its :class:`Reaction` using *bindings*.

    If *event* is not present in *bindings*, a safe default ``"…"`` reaction
    is returned so callers never have to guard against ``None``.

    The *bindings* dict is expected to be the output of :func:`merged_bindings`
    (defaults + user overrides), but any ``dict[str, str]`` is accepted.

    Parameters
    ----------
    event:
        The event name to react to (e.g. ``"test_pass"``).
    bindings:
        The effective event→text map.
    """
    raw = bindings.get(event)
    if raw is None:
        return Reaction(event=event, text="…", has_bell=False)
    # Bindings may already carry a trailing bell character if the user used
    # ``--bell`` when binding (the commands layer appends ``\\a``).
    has_bell = raw.endswith(_BELL)
    text = raw.rstrip(_BELL) if has_bell else raw
    return Reaction(event=event, text=text, has_bell=has_bell)
