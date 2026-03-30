from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.models import CompactionSnapshotRecord


def write_continuation_brief(
    *,
    home: Path,
    snapshot: CompactionSnapshotRecord,
    continuation_brief_md: str,
    token_count: int,
) -> tuple[Path, CompactionSnapshotRecord]:
    """Write the continuation brief to a well-known file and update the snapshot."""
    brief_path = home / ".onmc-continuation-brief.md"
    brief_path.write_text(continuation_brief_md, encoding="utf-8")
    updated_snapshot = snapshot.model_copy(
        update={
            "brief_token_count": token_count,
            "continuation_brief_md": continuation_brief_md,
        }
    )
    return brief_path, updated_snapshot
