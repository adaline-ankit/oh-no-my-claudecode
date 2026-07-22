"""Append-only, SHA-256 hash-chained broker audit events."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import stat
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from ._serialization import canonical_json_bytes

GENESIS_HASH = "0" * 64


def _event_hash(event_without_hash: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(event_without_hash)).hexdigest()


class AuditLog:
    """A JSONL audit ledger that only appends new, chained events."""

    _thread_lock = threading.Lock()

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(UTC))

    def append(self, event_type: str, data: Mapping[str, object]) -> dict[str, object]:
        if not event_type or "\x00" in event_type:
            raise ValueError("audit event type must be non-empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow and self.path.is_symlink():
            raise ValueError("audit log target cannot be a symlink")
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | nofollow
        with self._thread_lock:
            try:
                fd = os.open(self.path, flags, 0o600)
            except OSError as exc:
                if nofollow and exc.errno == errno.ELOOP:
                    raise ValueError("audit log target cannot be a symlink") from exc
                raise
            try:
                mode = os.fstat(fd).st_mode
                if not stat.S_ISREG(mode):
                    raise ValueError("audit log target must be a regular file")
                fcntl.flock(fd, fcntl.LOCK_EX)
                with os.fdopen(fd, "r+", encoding="utf-8", closefd=False) as handle:
                    line_count = 0
                    last_line: str | None = None
                    for line in handle:
                        line_count += 1
                        last_line = line
                    previous_hash = GENESIS_HASH
                    if last_line is not None:
                        last = json.loads(last_line)
                        previous_hash = str(last["event_hash"])
                    timestamp = self._clock()
                    if timestamp.tzinfo is None:
                        raise ValueError("audit clock must return a timezone-aware datetime")
                    event: dict[str, object] = {
                        "sequence": line_count,
                        "timestamp": timestamp.astimezone(UTC).isoformat(),
                        "event_type": event_type,
                        "data": dict(data),
                        "previous_hash": previous_hash,
                    }
                    event["event_hash"] = _event_hash(event)
                    audit_line = canonical_json_bytes(event) + b"\n"
                    os.write(fd, audit_line)
                    os.fsync(fd)
                    return event
            finally:
                os.close(fd)

    @staticmethod
    def verify(
        path: str | Path,
        *,
        expected_sequence: int | None = None,
        expected_head: str | None = None,
    ) -> bool:
        """Verify chain integrity and, optionally, an externally retained head."""

        ledger = Path(path)
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if not nofollow and ledger.is_symlink():
            return False
        previous_hash = GENESIS_HASH
        final_sequence = -1
        try:
            fd = os.open(ledger, os.O_RDONLY | nofollow)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    return False
                fcntl.flock(fd, fcntl.LOCK_SH)
                with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as handle:
                    for sequence, line in enumerate(handle):
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            return False
                        claimed_hash = event.pop("event_hash", None)
                        if event.get("sequence") != sequence:
                            return False
                        if event.get("previous_hash") != previous_hash:
                            return False
                        if claimed_hash != _event_hash(event):
                            return False
                        final_sequence = sequence
                        previous_hash = str(claimed_hash)
            finally:
                os.close(fd)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return False
        if expected_sequence is not None and final_sequence != expected_sequence:
            return False
        return expected_head is None or previous_hash == expected_head
