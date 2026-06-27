from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from time import sleep, time
from typing import Any

DEFAULT_TTL_SECONDS = 3600
LEDGER_VERSION = 1
LOCK_STALE_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class Claim:
    owner: str
    path: str
    acquired_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class ClaimResult:
    ok: bool
    claims: list[Claim]
    conflicts: list[Claim]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "claims": [asdict(claim) for claim in self.claims],
            "conflicts": [asdict(claim) for claim in self.conflicts],
        }


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    released: int
    claims: list[Claim]

    def to_dict(self) -> dict[str, object]:
        return {
            "released": self.released,
            "claims": [asdict(claim) for claim in self.claims],
        }


@dataclass(frozen=True, slots=True)
class StatusResult:
    claims: list[Claim]

    def to_dict(self) -> dict[str, object]:
        return {"claims": [asdict(claim) for claim in self.claims]}


class ClaimLedger:
    def __init__(self, repo_root: Path, *, clock: Callable[[], float] | None = None) -> None:
        self.repo_root = repo_root
        self.path = repo_root / ".onmc" / "claims.json"
        self.lock_path = repo_root / ".onmc" / "claims.lock"
        self._clock = clock or time

    def acquire(
        self,
        owner: str,
        paths: Iterable[str],
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> ClaimResult:
        with self._locked():
            now = self._clock()
            active = self._active_claims(now)
            wanted = _normalize_paths(paths)
            conflicts = [
                claim for claim in active if claim.path in wanted and claim.owner != owner
            ]
            if conflicts:
                return ClaimResult(ok=False, claims=active, conflicts=conflicts)

            remaining = [
                claim
                for claim in active
                if not (claim.owner == owner and claim.path in wanted)
            ]
            new_claims = [
                Claim(
                    owner=owner,
                    path=path,
                    acquired_at=now,
                    expires_at=now + ttl_seconds,
                )
                for path in wanted
            ]
            claims = _sort_claims([*remaining, *new_claims])
            self._write(claims)
            return ClaimResult(ok=True, claims=claims, conflicts=[])

    def release(self, owner: str, *, path: str | None = None) -> ReleaseResult:
        with self._locked():
            now = self._clock()
            active = self._active_claims(now)
            normalized_path = _normalize_path(path) if path is not None else None
            claims = [
                claim
                for claim in active
                if not (
                    claim.owner == owner
                    and (normalized_path is None or claim.path == normalized_path)
                )
            ]
            released = len(active) - len(claims)
            self._write(claims)
            return ReleaseResult(released=released, claims=claims)

    def status(self) -> StatusResult:
        with self._locked():
            claims = self._active_claims(self._clock())
            self._write(claims)
            return StatusResult(claims=claims)

    def check(self, paths: Iterable[str], *, owner: str | None = None) -> ClaimResult:
        with self._locked():
            active = self._active_claims(self._clock())
            wanted = _normalize_paths(paths)
            conflicts = [
                claim
                for claim in active
                if claim.path in wanted and (owner is None or claim.owner != owner)
            ]
            return ClaimResult(ok=not conflicts, claims=active, conflicts=conflicts)

    def _active_claims(self, now: float) -> list[Claim]:
        return [claim for claim in self._read() if claim.expires_at > now]

    def _read(self) -> list[Claim]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw_claims = payload.get("claims", []) if isinstance(payload, dict) else []
        claims: list[Claim] = []
        for raw in raw_claims:
            if not isinstance(raw, dict):
                continue
            claim = _claim_from_payload(raw)
            if claim is not None:
                claims.append(claim)
        return _sort_claims(claims)

    def _write(self, claims: list[Claim]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": LEDGER_VERSION,
            "claims": [asdict(claim) for claim in _sort_claims(claims)],
        }
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, self.path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o644,
                )
                break
            except FileExistsError:
                if _is_stale_lock(self.lock_path):
                    with suppress(FileNotFoundError):
                        self.lock_path.unlink()
                    continue
                sleep(0.05)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()}\n")
            yield
        finally:
            with suppress(FileNotFoundError):
                self.lock_path.unlink()


def _claim_from_payload(raw: dict[str, Any]) -> Claim | None:
    try:
        return Claim(
            owner=str(raw["owner"]),
            path=_normalize_path(str(raw["path"])),
            acquired_at=float(raw["acquired_at"]),
            expires_at=float(raw["expires_at"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    normalized = [_normalize_path(path) for path in paths]
    deduped = list(dict.fromkeys(normalized))
    if not deduped:
        raise ValueError("At least one path is required.")
    return deduped


def _normalize_path(path: str) -> str:
    normalized = Path(path).as_posix().strip()
    if normalized in {"", "."}:
        raise ValueError("Claim path must not be empty.")
    return normalized


def _sort_claims(claims: list[Claim]) -> list[Claim]:
    return sorted(claims, key=lambda claim: (claim.path, claim.owner))


def _is_stale_lock(path: Path) -> bool:
    try:
        return time() - path.stat().st_mtime > LOCK_STALE_SECONDS
    except FileNotFoundError:
        return False
