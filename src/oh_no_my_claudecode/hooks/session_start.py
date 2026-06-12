from __future__ import annotations

import json
from pathlib import Path

from oh_no_my_claudecode.models import CompactionSnapshotRecord

CONTINUATION_BRIEF_FILENAME = "continuation-brief.md"


def session_start_context_json(continuation_brief_md: str) -> str:
    """Serialize the SessionStart hook stdout contract for Claude Code.

    Claude Code injects ``hookSpecificOutput.additionalContext`` into the model
    context when a session starts (matcher ``"compact"`` fires right after
    compaction). The hook's stdout must contain ONLY this JSON — any other
    output corrupts the injection.
    """
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": continuation_brief_md,
            }
        }
    )


def write_continuation_brief_artifact(
    *,
    state_dir: Path,
    snapshot: CompactionSnapshotRecord,
    continuation_brief_md: str,
    token_count: int,
) -> tuple[Path, CompactionSnapshotRecord]:
    """Persist the brief as a debug artifact and update the snapshot record.

    Context injection happens via the SessionStart hook stdout; this file
    (``.onmc/continuation-brief.md``) exists only so users can inspect what was
    injected. It is NOT read back by anything.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    brief_path = state_dir / CONTINUATION_BRIEF_FILENAME
    brief_path.write_text(continuation_brief_md, encoding="utf-8")
    updated_snapshot = snapshot.model_copy(
        update={
            "brief_token_count": token_count,
            "continuation_brief_md": continuation_brief_md,
        }
    )
    return brief_path, updated_snapshot
