"""Deterministic, model-free working-context benchmark; see docs/benchmarks/working-context.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import tempfile
import time
from pathlib import Path

from oh_no_my_claudecode.experiment.stats import percentile
from oh_no_my_claudecode.hooks.prompt_recall import compile_prompt_recall
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.models.memory import PromotionState
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.working_context.engine import WorkingContext

GOAL = "Fix cache expiration"
CONSTRAINTS = ["Preserve the public API.", "Use the existing dependencies."]
CLAIM = "Cache TTL is 30 seconds."
ARMS = ("legacy_pinned", "adaptive", "adaptive_always")
# Independent oracle: these expectations describe fixture changes, not engine decisions.
EVENTS = (
    ("initial", True),
    *((f"repeat_{i}", True) for i in range(1, 6)),
    ("edit_same_mtime", False),
    ("restore", True),
    ("delete", False),
    ("recreate", True),
    ("quarantine", False),
    ("promote", True),
    ("compact", True),
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def prepare(repo: Path, size: int, seed: int) -> tuple[WorkingContext, MemoryEntry, str]:
    repo.mkdir()
    (repo / "cache.py").write_text("TTL = 30\n", encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "ONMC Benchmark")
    git(repo, "config", "user.email", "benchmark@example.invalid")
    git(repo, "add", "cache.py")
    git(repo, "commit", "-qm", "Synthetic fixture")
    storage = SQLiteStorage(repo / ".onmc" / "memory.sqlite3")
    storage.initialize()
    now = utc_now()
    relevant = MemoryEntry(
        id="cache-ttl",
        kind=MemoryKind.DOC_FACT,
        title="Cache expiration",
        summary=CLAIM,
        details="",
        source_type=SourceType.CODE,
        source_ref="cache.py",
        confidence=0.9,
        created_at=now,
        updated_at=now,
    )
    rng = random.Random(seed)  # noqa: S311 -- reproducible synthetic data
    entries = [relevant]
    for index in range(size - 1):
        entries.append(
            relevant.model_copy(
                update={
                    "id": f"noise-{index}",
                    "title": f"Catalog shard {rng.randrange(1000000)}",
                    "summary": f"Inventory partition {index} uses warehouse {rng.randrange(1000)}.",
                    "source_ref": "manual:benchmark",
                    "confidence": 0.5,
                }
            )
        )
    rng.shuffle(entries)
    storage.upsert_memories(entries)
    # Timestamps are fixture setup metadata, excluded from the reproducible corpus digest.
    corpus = [
        entry.model_dump(mode="json", exclude={"created_at", "updated_at"}) for entry in entries
    ]
    corpus_sha = digest(json.dumps(corpus, sort_keys=True).encode())
    engine = WorkingContext(repo, storage)
    engine.configure(enabled=True, budget_chars=6000, constraints=CONSTRAINTS)
    engine.start("benchmark", GOAL)
    return engine, relevant, corpus_sha


def run_stream(repo: Path, size: int, seed: int, arm: str) -> list[dict[str, object]]:
    engine, entry, corpus_sha = prepare(repo, size, seed)
    source = repo / "cache.py"
    rows: list[dict[str, object]] = []
    prefix = GOAL + "\n" + "\n".join(CONSTRAINTS) + "\n"
    for event, expected_present in EVENTS:
        if event == "edit_same_mtime":
            stat = source.stat()
            source.write_text("TTL = 60\n", encoding="utf-8")
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        elif event in {"restore", "recreate"}:
            source.write_text("TTL = 30\n", encoding="utf-8")
        elif event == "delete":
            source.unlink()
        elif event == "quarantine":
            values = entry.model_dump()
            values["promotion_state"] = PromotionState.QUARANTINED
            engine.storage.upsert_memories([MemoryEntry.model_validate(values)])
        elif event == "promote":
            engine.storage.upsert_memories([entry])
        started = time.perf_counter_ns()
        if arm == "legacy_pinned":
            text, _ = compile_prompt_recall(
                engine.storage,
                GOAL,
                limit=5,
                budget_tokens=1200,
                terse=False,
                min_score=1.5,
                max_chars=6000 - len(prefix),
            )
            packet = prefix + text
            injection = packet
        else:
            result = engine.context(
                "benchmark",
                files=["cache.py"],
                force=arm == "adaptive_always" or event == "compact",
            )
            packet, injection = result.markdown, result.injection
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        observed = CLAIM in packet
        delivery_expected = arm != "adaptive" or not event.startswith("repeat_")
        delivery_ok = injection == (packet if delivery_expected else "")
        rows.append(
            {
                "arm": arm,
                "size": size,
                "seed": seed,
                "event": event,
                "corpus_sha256": corpus_sha,
                "expected_claim": expected_present,
                "observed_claim": observed,
                "correct": observed == expected_present,
                "unsafe_claim": observed and not expected_present,
                "missing_valid_claim": expected_present and not observed,
                "constraints_retained": all(c in packet for c in CONSTRAINTS),
                "delivery_expected": delivery_expected,
                "delivery_ok": delivery_ok,
                "packet_chars": len(packet),
                "injected_chars": len(injection),
                "budget_ok": len(packet) <= 6000,
                "latency_ms": round(elapsed_ms, 4),
            }
        )
    return rows


def summarize(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summary = []
    for size in sorted({int(str(row["size"])) for row in rows}):
        for arm in ARMS:
            group = [r for r in rows if r["size"] == size and r["arm"] == arm]
            if not group:
                continue
            latencies = sorted(float(str(r["latency_ms"])) for r in group)
            warm = sorted(float(str(r["latency_ms"])) for r in group if r["event"] != "initial")
            summary.append(
                {
                    "size": size,
                    "arm": arm,
                    "events": len(group),
                    "correct": sum(bool(r["correct"]) for r in group),
                    "unsafe_claims": sum(bool(r["unsafe_claim"]) for r in group),
                    "missing_valid_claims": sum(bool(r["missing_valid_claim"]) for r in group),
                    "constraint_failures": sum(not r["constraints_retained"] for r in group),
                    "budget_failures": sum(not r["budget_ok"] for r in group),
                    "delivery_failures": sum(not r["delivery_ok"] for r in group),
                    "injected_chars": sum(int(str(r["injected_chars"])) for r in group),
                    "latency_p50_ms": round(percentile(latencies, 50), 3),
                    "latency_p95_ms": round(percentile(latencies, 95), 3),
                    "warm_p95_ms": round(percentile(warm, 95), 3),
                }
            )
    return summary


def run(sizes: list[int], seeds: list[int]) -> dict[str, object]:
    if not sizes or not seeds or any(size < 1 for size in sizes):
        raise ValueError("Provide positive corpus sizes and at least one seed")
    if len(set(sizes)) != len(sizes) or len(set(seeds)) != len(seeds):
        raise ValueError("Duplicate sizes/seeds would overweight a stream")
    os.environ["ONMC_LEARNING"] = "1"
    os.environ["ONMC_EMBEDDINGS"] = "0"
    os.environ["ONMC_FIREWALL"] = "0"
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="onmc-context-bench-") as directory:
        for size in sizes:
            for seed in seeds:
                arms = list(ARMS)
                random.Random(seed).shuffle(arms)  # noqa: S311
                for arm in arms:
                    rows.extend(
                        run_stream(Path(directory) / f"{size}-{seed}-{arm}", size, seed, arm)
                    )
    root = Path(__file__).resolve().parents[1]
    inputs = [
        Path(__file__).resolve(),
        *sorted((root / "src/oh_no_my_claudecode/working_context").glob("*.py")),
        root / "src/oh_no_my_claudecode/hooks/prompt_recall.py",
    ]
    return {
        "schema_version": 1,
        "kind": "synthetic_component_benchmark_no_model_calls",
        "sizes": sizes,
        "seeds": seeds,
        "budget_chars": 6000,
        "git_head": git(root, "rev-parse", "HEAD"),
        "tracked_tree_dirty": bool(git(root, "status", "--porcelain", "--untracked-files=no")),
        "input_sha256": {str(p.relative_to(root)): digest(p.read_bytes()) for p in inputs},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "limitations": [
            "Synthetic state transitions; does not measure agent coding success or token cost.",
            "Latency excludes fixture setup and hook process startup; includes SQLite/Git reads.",
            "Noise memories are unrelated; this is not a hard semantic retrieval benchmark.",
            "Legacy: same goal/constraints, no freshness/dedup policy, embeddings disabled.",
            "Checks inspect current packet; cannot erase model history; withdrawals are advisory.",
            "Seeds vary corpus order/content, not independent real-world tasks.",
        ],
        "summary": summarize(rows),
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 10000])
    parser.add_argument("--seeds", type=int, nargs="+", default=[7, 19, 41])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.sizes, args.seeds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    # Baseline failures are legitimate observations. Adaptive regressions fail the run.
    rows = report["rows"]
    return int(
        any(
            not r["correct"]
            or not r["constraints_retained"]
            or not r["budget_ok"]
            or not r["delivery_ok"]
            for r in rows
            if r["arm"] != "legacy_pinned"
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
