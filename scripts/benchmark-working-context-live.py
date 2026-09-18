"""Paired Codex pilot with matched information access and external grading.

Explicit invocation makes real provider calls using the existing Codex login.
No model calls with --check-fixtures. See docs/benchmarks/working-context.md.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from working_context_pilot_fixtures import TASKS

from oh_no_my_claudecode.loop.adapters import CompletedProc, make_agent_runner
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.utils.time import utc_now
from oh_no_my_claudecode.working_context.engine import WorkingContext


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def grade(repo: Path, tests: str, destination: Path) -> dict[str, object]:
    # Materialize grader only after the agent exits. Never trust agent-written tests.
    checker = destination / "external_checks.py"
    checker.write_text(
        "import sys, unittest, copy\nsys.path.insert(0, sys.argv.pop(1))\n"
        + tests
        + "\nif __name__ == '__main__': unittest.main(verbosity=2)\n",
        encoding="utf-8",
    )
    source = repo / "solution.py"
    if not source.is_file():
        return {"passed": False, "tests_run": 0, "output": "Missing solution.py"}
    try:
        # Tasks explicitly require a single standard-library module. Do not let
        # candidate unittest.py/sitecustomize.py shadow the external grader.
        with tempfile.TemporaryDirectory(prefix="onmc-grade-") as directory:
            candidate = Path(directory)
            (candidate / "solution.py").write_bytes(source.read_bytes())
            proc = subprocess.run(
                [sys.executable, "-I", str(checker), str(candidate)],
                cwd=candidate,
                capture_output=True,
                text=True,
                timeout=20,
            )
        output = proc.stdout + proc.stderr
        count = re.search(r"Ran (\d+) tests?", output)
        return {
            "passed": proc.returncode == 0
            and count is not None
            and int(count.group(1)) == 6
            and re.search(r"^OK$", output, re.MULTILINE) is not None,
            "tests_run": int(count.group(1)) if count else 0,
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "tests_run": 0, "output": "Grader timed out after 20s"}


def check_fixtures() -> list[dict[str, object]]:
    results = []
    with tempfile.TemporaryDirectory(prefix="onmc-oracle-") as folder:
        base = Path(folder)
        for task in TASKS:
            repo = base / task["id"]
            repo.mkdir()
            (repo / "solution.py").write_text(task["reference"], encoding="utf-8")
            reference = grade(repo, task["tests"], base)
            (repo / "solution.py").write_text(task["stub"], encoding="utf-8")
            stub = grade(repo, task["tests"], base)
            results.append({"task": task["id"], "reference": reference, "stub": stub})
            if not reference["passed"] or stub["passed"]:
                raise ValueError(f"Invalid grading fixture: {task['id']}: {results[-1]}")
    return results


def prepare(repo: Path, task: dict[str, str]) -> tuple[str, dict[str, str]]:
    repo.mkdir()
    (repo / "solution.py").write_text(task["stub"], encoding="utf-8")
    (repo / "CONTRACT.md").write_text(task["contract"], encoding="utf-8")
    (repo / "AGENTS.md").write_text(
        "Work only in this repository. Implement solution.py.\n"
        "Preserve CONTRACT.md and HISTORY.json.\n"
        "Current contract is authoritative; historical notes can be stale.\n"
        "No network or external project files needed. Do not install packages.\n",
        encoding="utf-8",
    )
    history = [
        {"id": "current", "summary": task["contract"], "source_ref": "CONTRACT.md"},
        {"id": "old", "summary": task["stale"], "source_ref": "RETIRED.md"},
        *[
            {
                "id": f"noise-{n}",
                "summary": f"Unrelated inventory shard {n} uses warehouse {n * 7}.",
                "source_ref": "manual:archive",
            }
            for n in range(24)
        ],
    ]
    write_json(repo / "HISTORY.json", history)
    for args in (
        ["init", "-q"],
        ["config", "user.name", "ONMC Pilot"],
        ["config", "user.email", "pilot@example.invalid"],
        ["add", "."],
        ["commit", "-qm", "Frozen pilot fixture"],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    storage = SQLiteStorage(repo / ".onmc" / "memory.sqlite3")
    storage.initialize()
    now = utc_now()
    storage.upsert_memories(
        [
            MemoryEntry(
                id=item["id"],
                kind=MemoryKind.DOC_FACT,
                title=task["goal"] if item["id"] in {"current", "old"} else item["id"],
                summary=item["summary"],
                details="",
                source_type=SourceType.DOC,
                source_ref=item["source_ref"],
                confidence=0.9,
                created_at=now,
                updated_at=now,
            )
            for item in history
        ]
    )
    engine = WorkingContext(repo, storage)
    engine.configure(
        enabled=True,
        constraints=[
            "Preserve public signatures and use only Python standard library.",
            "Current CONTRACT.md is authoritative; historical notes may be stale.",
        ],
    )
    engine.start("pilot", task["goal"])
    packet = engine.context("pilot", files=["CONTRACT.md"])
    # Persist same ONMC state in both arms; only prompt attachment differs.
    immutable = {
        name: sha((repo / name).read_text(encoding="utf-8"))
        for name in ("CONTRACT.md", "HISTORY.json", "AGENTS.md")
    }
    return packet.markdown, immutable


class Recorder:
    """Use ONMC's real adapter with a controlled subprocess boundary and raw JSONL."""

    def __init__(self, destination: Path, effort: str) -> None:
        self.destination = destination
        self.effort = effort
        self.returncode: int | None = None
        self.timed_out = False
        self.usage: dict[str, object] | None = None

    def __call__(self, cmd: list[str], cwd: str, timeout: int) -> CompletedProc:
        provider = cmd[0] == "codex"
        if provider:
            cmd = [
                *cmd[:-1],
                "--json",
                "--ephemeral",
                "--ignore-user-config",
                "-c",
                f'model_reasoning_effort="{self.effort}"',
                cmd[-1],
            ]
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name == "posix",
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
            stderr += f"\n[timeout after {timeout}s]"
            if provider:
                self.timed_out = True
        if provider:
            self.returncode = proc.returncode
            (self.destination / "events.jsonl").write_text(stdout, encoding="utf-8")
            (self.destination / "stderr.txt").write_text(stderr, encoding="utf-8")
            for line in stdout.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == "turn.completed":
                    usage = event.get("usage")
                    if isinstance(usage, dict):
                        self.usage = usage
        return CompletedProc(proc.returncode, stdout, stderr)


def run(output: Path, model: str, effort: str, timeout: int, repeats: int) -> dict[str, object]:
    if repeats < 1 or timeout < 1:
        raise ValueError("Repeats and timeout must be positive")
    checks = check_fixtures()
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    os.environ["ONMC_LEARNING"] = "1"
    os.environ["ONMC_EMBEDDINGS"] = "0"
    sources = [Path(__file__), Path(__file__).with_name("working_context_pilot_fixtures.py")]
    sources += sorted((root / "src/oh_no_my_claudecode/working_context").glob("*.py"))
    manifest = {
        "kind": "synthetic_live_coding_pilot",
        "schema_version": 1,
        "model": model,
        "reasoning_effort": effort,
        "timeout_seconds": timeout,
        "repeats": repeats,
        "planned_attempts": len(TASKS) * repeats * 2,
        "agent_config": "ignore-user-config; ephemeral; workspace-write",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "codex_version": subprocess.check_output(["codex", "--version"], text=True).strip(),
        "git_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "input_sha256": {str(p.relative_to(root)): sha(p.read_text()) for p in sources},
        "fixture_checks": checks,
        "limitations": [
            "Three small synthetic tasks; no general accuracy claim or SWE-bench score.",
            "Both arms have all source facts; treatment also gets compiled context.",
            "No native Claude hooks exercised; one initial packet per fresh Codex run.",
            "Provider nondeterminism and cache effects remain; costs unknown.",
        ],
    }
    write_json(output / "manifest.json", manifest)
    rows = []
    for repeat in range(repeats):
        for index, task in enumerate(TASKS):
            arms = ["baseline", "adaptive"]
            if (index + repeat) % 2:
                arms.reverse()
            for arm in arms:
                destination = output / f"{task['id']}-{repeat}-{arm}"
                destination.mkdir()
                repo = destination / "repo"
                packet, immutable = prepare(repo, task)
                prompt = (
                    task["goal"] + "\nRead CONTRACT.md for all requirements. "
                    "HISTORY.json contains prior notes and may be stale. "
                    "Current contract is authoritative. Preserve public signatures; "
                    "use only standard library. Implement and test your change."
                )
                if arm == "adaptive":
                    prompt += "\n\n" + packet
                (destination / "prompt.txt").write_text(prompt, encoding="utf-8")
                recorder = Recorder(destination, effort)
                runner = make_agent_runner(
                    "codex", repo_root=repo, model=model, timeout=timeout, command_runner=recorder
                )
                pending = {
                    "task": task["id"],
                    "repeat": repeat,
                    "arm": arm,
                    "status": "started",
                    "passed": False,
                }
                rows.append(pending)
                write_json(output / "results.json", {"manifest": manifest, "rows": rows})
                started = time.perf_counter()
                agent_error = None
                try:
                    result = runner(prompt, escalation_level=0)
                    agent_error = result.error
                except Exception as exc:  # noqa: BLE001 -- retain failed attempts
                    agent_error = f"{type(exc).__name__}: {exc}"
                seconds = time.perf_counter() - started
                artifact_error = None
                final_source = ""
                try:
                    verdict = grade(repo, task["tests"], destination)
                    integrity = all(
                        (repo / name).is_file() and sha((repo / name).read_text()) == value
                        for name, value in immutable.items()
                    )
                    final_source = (
                        (repo / "solution.py").read_text(encoding="utf-8")
                        if (repo / "solution.py").is_file()
                        else ""
                    )
                except Exception as exc:  # noqa: BLE001 -- never drop an attempted run
                    artifact_error = f"{type(exc).__name__}: {exc}"
                    verdict = {"passed": False, "tests_run": 0, "output": artifact_error}
                    integrity = False
                (destination / "solution.py").write_text(final_source, encoding="utf-8")
                patch = "".join(
                    difflib.unified_diff(
                        task["stub"].splitlines(keepends=True),
                        final_source.splitlines(keepends=True),
                        fromfile="a/solution.py",
                        tofile="b/solution.py",
                    )
                )
                (destination / "patch.diff").write_text(patch, encoding="utf-8")
                row = {
                    "task": task["id"],
                    "repeat": repeat,
                    "arm": arm,
                    "provider_returncode": recorder.returncode,
                    "timeout": recorder.timed_out,
                    "agent_error": agent_error,
                    "artifact_error": artifact_error,
                    "status": "completed",
                    "usage": recorder.usage,
                    "cost_usd": None,
                    "wall_seconds": round(seconds, 3),
                    "prompt_chars": len(prompt),
                    "grader": verdict,
                    "fixture_intact": integrity,
                    "solution_sha256": sha(final_source),
                    "passed": recorder.returncode == 0
                    and verdict["passed"]
                    and integrity
                    and agent_error is None
                    and artifact_error is None,
                }
                rows[-1] = row
                write_json(destination / "result.json", row)
                write_json(output / "results.json", {"manifest": manifest, "rows": rows})
                print(
                    json.dumps(
                        {
                            k: row[k]
                            for k in ("task", "repeat", "arm", "passed", "wall_seconds", "usage")
                        }
                    ),
                    flush=True,
                )
    return {"manifest": manifest, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=["low", "medium", "high"], default="medium")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--check-fixtures", action="store_true")
    args = parser.parse_args()
    if args.check_fixtures:
        print(json.dumps(check_fixtures(), indent=2))
        return 0
    if not args.output or not args.model:
        parser.error("Live runs require explicit --output and --model")
    run(args.output.resolve(), args.model, args.effort, args.timeout, args.repeats)
    return 0  # Coding failures are observations, not a reason to discard the report.


if __name__ == "__main__":
    raise SystemExit(main())
