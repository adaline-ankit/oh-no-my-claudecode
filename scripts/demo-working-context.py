"""Reproduce working-context behavior with real Git, files, SQLite, and hooks.

No model calls or provider credentials. This is a functional demonstration,
not evidence of improved agent task success. Run from an installed checkout:
    python scripts/demo-working-context.py --output /tmp/working-context-demo.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from oh_no_my_claudecode.core.service import OnmcService
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.working_context.engine import WorkingContext
from oh_no_my_claudecode.working_context.hooks import working_hook_output


def run_demo() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="onmc-working-demo-") as directory:
        repo = Path(directory).resolve()
        source = repo / "cache.py"
        source.write_text("TTL_SECONDS = 30\n", encoding="utf-8")
        for args in (
            ["init", "-q"],
            ["config", "user.name", "ONMC Demo"],
            ["config", "user.email", "demo@example.invalid"],
            ["add", "cache.py"],
            ["commit", "-qm", "Demo baseline"],
        ):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
        service = OnmcService(repo)
        service.init_project()
        _, _, storage = service._load_context()  # noqa: SLF001
        now = utc_now()
        storage.upsert_memories(
            [
                MemoryEntry(
                    id="cache-ttl",
                    kind=MemoryKind.DOC_FACT,
                    title="Cache expiration",
                    summary="Cache TTL is 30 seconds.",
                    details="",
                    source_type=SourceType.CODE,
                    source_ref="cache.py",
                    confidence=0.9,
                    created_at=now,
                    updated_at=now,
                )
            ]
        )
        engine = WorkingContext(repo, storage)
        engine.configure(enabled=True, constraints=["Preserve the public cache API."])
        payload: dict[str, object] = {
            "cwd": str(repo),
            "session_id": "demo-session",
            "prompt": "Fix cache expiration without changing its public API.",
        }
        started = time.perf_counter()
        handled, first = working_hook_output("UserPromptSubmit", payload)
        first_ms = round((time.perf_counter() - started) * 1000, 2)
        engine.note("demo-session", "next_step", "Run cache regression tests.")
        before = engine.context("demo-session", files=["cache.py"])
        duplicate = engine.context("demo-session")
        timestamp = source.stat()
        source.write_text("TTL_SECONDS = 60\n", encoding="utf-8")
        os.utime(source, ns=(timestamp.st_atime_ns, timestamp.st_mtime_ns))
        started = time.perf_counter()
        after = engine.context("demo-session")
        refresh_ms = round((time.perf_counter() - started) * 1000, 2)
        restored = WorkingContext(repo, storage).context("demo-session", force=True)
        engine.start("other-session", "Unrelated logging change", constraints=["Keep log schema."])
        other = engine.context("other-session")
        checks = {
            "real_prompt_hook_delivered_context": handled and "Cache TTL is 30 seconds." in first,
            "unchanged_context_suppressed": duplicate.injection == "",
            "dirty_source_with_same_mtime_withdrawn": after.withdrawn == ["cache-ttl"],
            "stale_claim_absent": "Cache TTL is 30 seconds." not in after.markdown,
            "constraints_restored": "Preserve the public cache API." in restored.injection,
            "next_step_restored": "Run cache regression tests." in restored.injection,
            "sessions_isolated": "Run cache regression tests." not in other.markdown,
            "budget_respected": all(
                p.used_chars <= p.budget_chars for p in [before, after, restored]
            ),
        }
        return {
            "schema_version": 1,
            "kind": "functional_demo_no_model_calls",
            "checks": checks,
            "passed": all(checks.values()),
            "observed_ms": {"first_prompt": first_ms, "dirty_refresh": refresh_ms},
            "injected_chars": {
                "before": before.used_chars,
                "repeat": len(duplicate.injection),
                "after": after.used_chars,
            },
            "before": before.markdown,
            "after": after.markdown,
            "excluded_after": [item.model_dump() for item in after.excluded],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_demo()
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
