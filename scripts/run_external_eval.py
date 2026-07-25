#!/usr/bin/env python
"""Run the M6 external-proof portfolio against real repositories.

Design (blueprint truth rules):

* **Real external repos, pinned SHAs.** Each trial clones a fresh copy of the
  upstream repository at a pinned commit — no shared mutable state between
  trials or conditions.
* **Seeded regression, real verifier.** A single upstream function is reverted to
  a broken state. The task is adjudicated by the repository's OWN upstream test
  suite, which was confirmed passing at the pinned SHA (validity gate). So a
  pass means real upstream behaviour was restored, never the agent's own word
  (rule 8: grade repository outcome, not agent prose).
* **Real controls.** ``bare-agent`` invokes the same agent CLI directly with the
  same prompt, model, permissions and verifier — it is a real execution, never a
  simulated empty condition (rule 5).
* **Equivalence.** Both arms get the same task, repo revision, verifier argv and
  timeout (rule 6).
* **Uncertainty.** Multiple trials with randomized condition order; every
  infrastructure failure is recorded, never silently dropped (rule 13).

Usage::

    python scripts/run_external_eval.py --manifest datasets/experiment/portfolio_external_v1.json \
        --workdir /tmp/eval --out /tmp/eval/report.json [--trials 3] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from oh_no_my_claudecode.experiment.contracts import (  # noqa: E402
    Condition,
    MetricLabel,
)
from oh_no_my_claudecode.experiment.portfolio import (  # noqa: E402
    PortfolioManifest,
    TaskSpec,
)
from oh_no_my_claudecode.experiment.stats import (  # noqa: E402
    bootstrap_ci,
    derive_seed,
    mean,
    median,
    paired_deltas,
    variance,
)

#: Seeded regressions: task_id -> tuple of (relative file, exact old text, broken
#: text) hunks. Every hunk is applied; the repair is adjudicated by the
#: repository's own upstream tests.
#:
#: Single-hunk tasks are kept for continuity but are known NOT to discriminate:
#: both arms scored 9/9 on them (2026-07-25). Multi-hunk/multi-file entries exist
#: to break that ceiling.
REGRESSIONS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "six-bugfix-integer-types": (
        (
            "six.py",
            "    integer_types = int,",
            "    integer_types = (str,)  # REGRESSION",
        ),
    ),
    "tenacity-bugfix-find-ordinal": (
        (
            "tenacity/_utils.py",
            '    if pos_num == 1:\n        return "st"',
            '    if pos_num == 1:\n        return "th"  # REGRESSION',
        ),
    ),
    "attrs-bugfix-asdict-recurse": (
        (
            "src/attr/_funcs.py",
            "        if filter is not None and not filter(a, v):\n            continue",
            "        if False:  # REGRESSION\n            continue",
        ),
    ),
    # --- multi-site tasks (added 2026-07-25 to break the ceiling effect) ---
    # The prompt names the SYMPTOM, never the number of broken sites. A one-shot
    # agent that fixes the first failing assertion and stops will not pass; the
    # adjudicating suite only goes green when every site is repaired.
    "six-multisite-type-aliases": (
        (
            "six.py",
            "    string_types = str,\n    integer_types = int,\n    class_types = type,",
            "    string_types = (bytes,)  # REGRESSION\n"
            "    integer_types = (str,)  # REGRESSION\n"
            "    class_types = (object,)  # REGRESSION",
        ),
    ),
    "tenacity-multisite-ordinal-suffixes": (
        (
            "tenacity/_utils.py",
            '    if pos_num == 1:\n        return "st"\n'
            '    if pos_num == 2:\n        return "nd"\n'
            '    if pos_num == 3:\n        return "rd"',
            '    if pos_num == 1:\n        return "th"  # REGRESSION\n'
            '    if pos_num == 2:\n        return "th"  # REGRESSION\n'
            '    if pos_num == 3:\n        return "th"  # REGRESSION',
        ),
    ),
    # Two structurally identical sites in different functions (asdict, astuple).
    # Anchored on distinct trailing context so each hunk is unambiguous rather
    # than relying on replacement order.
    "attrs-multisite-filter-ignored": (
        (
            "src/attr/_funcs.py",
            "        if filter is not None and not filter(a, v):\n"
            "            continue\n\n"
            "        if value_serializer is not None:",
            "        if False:  # REGRESSION\n"
            "            continue\n\n"
            "        if value_serializer is not None:",
        ),
        (
            "src/attr/_funcs.py",
            "        if filter is not None and not filter(a, v):\n"
            "            continue\n"
            "        value_type = type(v)",
            "        if False:  # REGRESSION\n"
            "            continue\n"
            "        value_type = type(v)",
        ),
    ),
}


#: Extra test-time dependencies per upstream repo, discovered by actually running
#: each suite (itsdangerous collection fails without freezegun). Recorded here
#: rather than guessed, so a cell can never fail as "infra" for a missing dep.
REPO_TEST_DEPS: dict[str, tuple[str, ...]] = {
    "six": (),
    "tenacity": (),
    "attrs": ("hypothesis",),
    "jmespath.py": (),
    "itsdangerous": ("freezegun",),
    "python-slugify": ("text-unidecode",),
}

#: Function-body removals: task_id -> ((relative file, dotted function name), ...).
#: The body is replaced with `raise NotImplementedError`, so the task is "implement
#: this real upstream function" and the repository's OWN tests adjudicate it.
#:
#: This is AST-driven rather than text-anchored on purpose: hand-written text
#: anchors do not scale to the 20-50 audited tasks the claim protocol requires, and
#: every hand-written anchor is another chance to seed a silently-vacuous task.
REMOVALS: dict[str, tuple[tuple[str, str], ...]] = {
    # --- six (feature/implement: real upstream helpers) ---
    "six-impl-ensure-binary": (("six.py", "ensure_binary"),),
    "six-impl-ensure-str": (("six.py", "ensure_str"),),
    "six-impl-ensure-text": (("six.py", "ensure_text"),),
    "six-impl-with-metaclass": (("six.py", "with_metaclass"),),
    # Multi-function: the three ensure_* helpers are related and all tested.
    "six-impl-ensure-trio": (
        ("six.py", "ensure_binary"),
        ("six.py", "ensure_str"),
        ("six.py", "ensure_text"),
    ),
    # --- tenacity ---
    "tenacity-impl-to-ordinal": (("tenacity/_utils.py", "to_ordinal"),),
    "tenacity-impl-to-seconds": (("tenacity/_utils.py", "to_seconds"),),
    "tenacity-impl-ordinal-pair": (
        ("tenacity/_utils.py", "find_ordinal"),
        ("tenacity/_utils.py", "to_ordinal"),
    ),
    # --- attrs (src/ layout; asdict/astuple share a private helper) ---
    "attrs-impl-has": (("src/attr/_funcs.py", "has"),),
    "attrs-impl-assoc": (("src/attr/_funcs.py", "assoc"),),
    "attrs-impl-asdict": (("src/attr/_funcs.py", "asdict"),),
    "attrs-impl-serialisation-pair": (
        ("src/attr/_funcs.py", "asdict"),
        ("src/attr/_funcs.py", "astuple"),
    ),
    # --- jmespath (methods on a class; exercises dotted resolution) ---
    "jmespath-impl-to-number": (("jmespath/functions.py", "Functions._func_to_number"),),
    "jmespath-impl-starts-with": (("jmespath/functions.py", "Functions._func_starts_with"),),
    "jmespath-impl-merge": (("jmespath/functions.py", "Functions._func_merge"),),
    "jmespath-impl-sort-by": (("jmespath/functions.py", "Functions._func_sort_by"),),
    "jmespath-impl-by-pair": (
        ("jmespath/functions.py", "Functions._func_sort_by"),
        ("jmespath/functions.py", "Functions._func_max_by"),
    ),
    # --- itsdangerous ---
    "itsdangerous-impl-base64-encode": (("src/itsdangerous/encoding.py", "base64_encode"),),
    "itsdangerous-impl-base64-pair": (
        ("src/itsdangerous/encoding.py", "base64_encode"),
        ("src/itsdangerous/encoding.py", "base64_decode"),
    ),
    "itsdangerous-impl-int-bytes-pair": (
        ("src/itsdangerous/encoding.py", "int_to_bytes"),
        ("src/itsdangerous/encoding.py", "bytes_to_int"),
    ),
    "itsdangerous-impl-want-bytes": (("src/itsdangerous/encoding.py", "want_bytes"),),
    # --- python-slugify ---
    "slugify-impl-smart-truncate": (("slugify/slugify.py", "smart_truncate"),),
    "slugify-impl-slugify": (("slugify/slugify.py", "slugify"),),
}


def remove_function_body(source: str, dotted: str) -> tuple[str, str | None]:
    """Replace the body of *dotted* (``func`` or ``Class.method``) with a raise.

    Returns ``(new_source, None)`` or ``(source, error)``. Uses the AST so the
    exact line range is authoritative — a regex would mangle nested defs and
    decorators, which is precisely the kind of silent corpus corruption that
    produces a confidently wrong benchmark.
    """
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - corpus guard
        return source, f"unparseable source: {exc}"

    parts = dotted.split(".")
    node: ast.AST = tree
    target: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for depth, name in enumerate(parts):
        found = None
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
            ) and child.name == name:
                found = child
                break
        if found is None:
            return source, f"{dotted}: '{name}' not found"
        node = found
        if depth == len(parts) - 1:
            if not isinstance(found, ast.FunctionDef | ast.AsyncFunctionDef):
                return source, f"{dotted} is not a function"
            target = found

    if target is None:  # pragma: no cover - defensive
        return source, f"{dotted} not resolved"

    lines = source.splitlines(keepends=True)
    first = target.body[0]
    start = first.lineno - 1  # 0-based; keeps signature, decorators and docstring line
    end = target.end_lineno
    if end is None:  # pragma: no cover - defensive
        return source, f"{dotted}: missing end_lineno"
    indent = " " * first.col_offset
    replacement = f'{indent}raise NotImplementedError("REMOVED")\n'
    return "".join(lines[:start]) + replacement + "".join(lines[end:]), None


@dataclass
class TrialRecord:
    task_id: str
    condition: str
    trial: int
    passed: bool
    latency_ms: float
    infra_error: str | None = None
    notes: str = ""
    cost_usd: float | None = None
    diff_lines: int = 0
    tests_touched: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "condition": self.condition,
            "trial": self.trial,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 1),
            "infra_error": self.infra_error,
            "notes": self.notes,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "diff_lines": self.diff_lines,
            "tests_touched": self.tests_touched,
        }


@dataclass
class EvalConfig:
    workdir: Path
    trials: int
    dry_run: bool
    timeout_s: int = 900
    verifier_timeout_s: int = 300
    max_iterations: int = 4
    max_cost_usd: float = 1.0
    max_total_usd: float = 10.0
    onmc_bin: Path | None = None
    extra_env: dict[str, str] = field(default_factory=dict)


def _run(
    argv: list[str], cwd: Path, timeout: int, env: dict[str, str] | None = None
) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603
            argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env
        )
    except subprocess.TimeoutExpired:
        return 124, "[timeout]"
    except OSError as exc:
        return 127, f"[oserror] {exc}"
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


#: Directory (inside the cell checkout) holding that cell's verifier interpreter.
VENV_DIR = ".eval-venv"


def prepare_venv(
    repo: Path, extra_deps: tuple[str, ...] = ()
) -> tuple[Path | None, str | None]:
    """Build a venv, INSIDE the cell checkout, that can run the repo's own tests.

    Two separate failures forced this shape:

    1. The verifier's bare ``python`` resolved to whatever was on PATH — in
       practice ONMC's own uv venv, which cannot import the target repository's
       test dependencies. Every cell failed as ``verifier-unavailable`` while the
       agent's real fix was thrown away.
    2. Putting that venv *outside* the checkout then made ONMC's reference
       monitor correctly DENY the verifier capability (it is not repo-scoped), so
       ``onmc run`` aborted at the policy gate before executing while the bare arm
       ran unimpeded — a silent asymmetry that penalised the treatment arm. The
       interpreter therefore has to live under the repository root.

    ``attrs`` uses a ``src/`` layout, so its tests import the *installed*
    package; the checkout is editable-installed here so the adjudicator sees the
    agent's edit rather than a cached copy.

    Returns ``(python_path, None)`` or ``(None, error)``.
    """
    venv = repo / VENV_DIR
    python = venv / "bin" / "python"
    # Keep the interpreter out of git and out of ONMC's repository scan, so it can
    # never be mistaken for the agent's change nor bloat the context packet.
    exclude = repo / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"\n{VENV_DIR}/\n.onmc/\n.agent-memory/\n")
    gitignore = repo / ".gitignore"
    prior = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    gitignore.write_text(f"{prior}\n{VENV_DIR}/\n", encoding="utf-8")

    code, out = _run(["uv", "venv", str(venv)], repo, 300)
    if code != 0:
        return None, f"uv venv failed: {out[-300:]}"
    code, out = _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "-q",
            "pytest",
            *extra_deps,
        ],
        repo,
        900,
    )
    if code != 0:
        return None, f"test-dep install failed: {out[-300:]}"
    code, out = _run(
        ["uv", "pip", "install", "--python", str(python), "-e", str(repo), "--no-deps", "-q"],
        repo,
        600,
    )
    if code != 0:
        return None, f"editable install failed: {out[-300:]}"
    return python, None


def prepare_onmc_venv(workdir: Path) -> tuple[Path | None, str | None]:
    """Install ONMC into its own venv and return its ``onmc`` entry point.

    The treatment arm must NOT be launched through ``uv run --project``: uv
    prepends its own venv to PATH, so the verifier's ``python -m pytest`` would
    resolve back to ONMC's interpreter instead of the cell's — the original cause
    of the blanket ``verifier-unavailable`` failures. Calling the entry point
    directly leaves the cell's PATH (see :func:`cell_env`) intact.
    """
    venv = workdir / "onmc-venv"
    onmc = venv / "bin" / "onmc"
    if onmc.exists():
        return onmc, None
    code, out = _run(["uv", "venv", str(venv)], workdir, 300)
    if code != 0:
        return None, f"onmc venv failed: {out[-300:]}"
    # NON-editable, deliberately. An editable install would let any source edit
    # made while the portfolio is running change the code under later cells, so
    # `code_sha` would no longer describe the whole run — the pinned-code
    # requirement would be silently violated mid-experiment.
    code, out = _run(
        ["uv", "pip", "install", "--python", str(venv / "bin" / "python"), "-q", str(REPO_ROOT)],
        workdir,
        1800,
    )
    if code != 0:
        return None, f"onmc install failed: {out[-300:]}"
    return onmc, None


def code_sha() -> str:
    """The exact ONMC revision under test, recorded in the report."""
    code, out = _run(["git", "rev-parse", "HEAD"], REPO_ROOT, 60)
    sha = out.strip() if code == 0 else "unknown"
    dirty, dirty_out = _run(["git", "status", "--porcelain"], REPO_ROOT, 60)
    if dirty == 0 and dirty_out.strip():
        sha += "-dirty"
    return sha


def prepare_clone(task: TaskSpec, dest: Path, cache: Path) -> str | None:
    """Clone the pinned repo into *dest*, PRISTINE (no regression yet)."""
    if not cache.exists():
        code, out = _run(
            ["git", "clone", "--quiet", task.repo.url, str(cache)], cache.parent, 600
        )
        if code != 0:
            return f"clone failed: {out[-300:]}"
    code, out = _run(["git", "clone", "--quiet", str(cache), str(dest)], dest.parent, 600)
    if code != 0:
        return f"local clone failed: {out[-300:]}"
    code, out = _run(["git", "checkout", "--quiet", task.repo.pinned_sha], dest, 120)
    if code != 0:
        return f"checkout {task.repo.pinned_sha[:8]} failed: {out[-300:]}"
    return None


def inject_regression(task: TaskSpec, dest: Path) -> str | None:
    """Seed the regression (one or many hunks, across one or many files) and COMMIT it.

    Multi-hunk support exists because single-hunk reverts turned out to be
    *unable to discriminate*: in the 2026-07-25 run bare Claude Code and ONMC both
    scored 9/9, so the corpus had a ceiling effect and the measured delta was zero
    by construction. A task that requires finding every affected site is the kind
    of task where a retrieval-and-loop harness could plausibly differ from a
    one-shot agent — so the corpus has to be able to express it.
    """
    for rel, old, new in REGRESSIONS.get(task.task_id, ()):
        target = dest / rel
        if not target.exists():
            return f"regression target missing: {rel}"
        text = target.read_text(encoding="utf-8")
        if old not in text:
            return f"regression anchor not found in {rel}"
        target.write_text(text.replace(old, new, 1), encoding="utf-8")

    for rel, dotted in REMOVALS.get(task.task_id, ()):
        target = dest / rel
        if not target.exists():
            return f"removal target missing: {rel}"
        updated, err = remove_function_body(target.read_text(encoding="utf-8"), dotted)
        if err:
            return f"{rel}: {err}"
        target.write_text(updated, encoding="utf-8")

    if not (REGRESSIONS.get(task.task_id) or REMOVALS.get(task.task_id)):
        return f"no mutation defined for {task.task_id}"

    # COMMIT the seeded regression. Leaving it uncommitted made the broken state
    # itself the working diff, so an agent that correctly restored upstream
    # behaviour produced an EMPTY diff versus HEAD — which ONMC's vacuous-pass
    # ChangeProbe reads as "no meaningful change" and blocks. That penalised the
    # treatment arm for being right. With the regression committed, the repair is
    # a real diff in both arms and the arms stay equivalent (rule 6).
    _run(["git", "-c", "user.email=eval@onmc.local", "-c", "user.name=onmc-eval",
          "commit", "--quiet", "--all", "-m", f"seed regression: {task.task_id}"], dest, 120)
    code, out = _run(["git", "status", "--porcelain"], dest, 60)
    if code != 0 or out.strip():
        return f"regression commit left a dirty tree: {out[:200]}"
    return None


def _observed_change(repo: Path) -> tuple[int, bool]:
    """Changed-line count and whether any test file was touched, versus the
    seeded-regression commit. Used to detect a no-op arm and test tampering."""
    code, out = _run(["git", "diff", "--numstat", "HEAD"], repo, 60)
    if code != 0:
        return 0, False
    lines = 0
    touched_tests = False
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        lines += sum(int(v) for v in (added, removed) if v.isdigit())
        base = path.rsplit("/", 1)[-1]
        if base.startswith("test_") or base.endswith("_test.py") or "/tests/" in f"/{path}":
            touched_tests = True
    return lines, touched_tests


def _extract_cost(out: str) -> float | None:
    """Best-effort per-run USD cost from the agent/onmc JSON output.

    Never fabricated: returns ``None`` when the run did not report a cost, so the
    report can say ``n/a`` instead of inventing a number.
    """
    for key in ("total_cost_usd", "cost_usd", "total_cost"):
        marker = f'"{key}"'
        idx = out.rfind(marker)
        while idx != -1:
            tail = out[idx + len(marker) :].lstrip()
            if tail.startswith(":"):
                num = tail[1:].strip()
                buf = ""
                for ch in num:
                    if ch.isdigit() or ch in ".-e+":
                        buf += ch
                    else:
                        break
                try:
                    return float(buf)
                except ValueError:
                    pass
            idx = out.rfind(marker, 0, idx)
    return None


def verifier_argv(task: TaskSpec, python: Path) -> list[str]:
    """The task's verifier argv, bound to the repo's own venv interpreter.

    A bare ``python`` in the manifest resolves to whatever is on PATH, which is
    how the whole experiment previously collapsed to ``verifier-unavailable``.
    """
    # Deliberately UNCHANGED. ONMC's reference monitor allowlists verifier
    # commands by argv prefix (`pytest`, `python -m pytest`, `ruff`, `mypy`), so
    # rewriting argv[0] to an interpreter path makes the monitor correctly DENY
    # the verifier capability and `onmc run` aborts before executing — while the
    # bare arm, which has no monitor, runs unimpeded. That asymmetry silently
    # zeroed the treatment arm. The right fix is to leave the command literal and
    # bind the interpreter through PATH (see `cell_env`), not to weaken policy.
    del python
    return list(task.verifier_argv)


def cell_env(repo: Path) -> dict[str, str]:
    """Environment for every subprocess of a cell: the cell venv first on PATH.

    ``VIRTUAL_ENV``/``UV_*`` are cleared so an outer ``uv run`` cannot re-point
    ``python`` at ONMC's own interpreter, which is what made the verifier
    unrunnable in the first place.
    """
    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env["PATH"] = f"{repo / VENV_DIR / 'bin'}:{env.get('PATH', '')}"
    return env


def verify(task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path) -> tuple[bool, str]:
    """Adjudicate with the repository's own upstream test suite."""
    code, out = _run(
        verifier_argv(task, python), repo, cfg.verifier_timeout_s, env=cell_env(repo)
    )
    return code == 0, out


def guard_pristine_verifier(
    task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path
) -> str | None:
    """The verifier MUST pass on the PRISTINE checkout before any regression.

    This is the real validity gate. Without it, a verifier that simply cannot run
    looks identical to "the regression broke the tests", so every arm scored 0 and
    the experiment silently measured the harness instead of the agents.
    """
    passed, out = verify(task, repo, cfg, python)
    if not passed:
        return f"pristine verifier did not pass — cell unusable: {out[-300:]}"
    return None


def guard_regression_active(
    task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path
) -> str | None:
    """The verifier MUST fail after the regression, or the task proves nothing."""
    passed, out = verify(task, repo, cfg, python)
    if passed:
        return "regression did not break the verifier (task would be vacuous)"
    if "[timeout]" in out or "[oserror]" in out:
        return f"verifier infrastructure failure: {out[:200]}"
    return None


def run_bare_agent(
    task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path
) -> tuple[str | None, float | None]:
    """Control arm: the agent CLI directly, same prompt/permissions/verifier."""
    argv = [
        "claude",
        "-p",
        f"{task.prompt}\n\nThe adjudicating test command is: "
        f"{shlex.join(verifier_argv(task, python))}",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
    code, out = _run(argv, repo, cfg.timeout_s, env=cell_env(repo))
    cost = _extract_cost(out)
    if code == 127:
        return f"agent CLI unavailable: {out[:200]}", cost
    if "[timeout]" in out:
        return "agent timeout", cost
    return None, cost


def run_onmc(
    task: TaskSpec, repo: Path, cfg: EvalConfig, python: Path
) -> tuple[str | None, float | None]:
    """Treatment arm: the same task through the full `onmc run` vertical path."""
    if cfg.onmc_bin is None:
        return "onmc entry point not prepared", None
    onmc = str(cfg.onmc_bin)
    _run([onmc, "init"], repo, 300, env=cell_env(repo))
    argv = [
        onmc,
        "run",
        task.prompt,
        "--execute",
        "--agent",
        "claude",
        "--max-iterations",
        str(cfg.max_iterations),
        "--max-cost-usd",
        str(cfg.max_cost_usd),
        "--verifier",
        shlex.join(verifier_argv(task, python)),
        "--json",
    ]
    code, out = _run(argv, repo, cfg.timeout_s, env=cell_env(repo))
    cost = _extract_cost(out)
    if "[timeout]" in out:
        return "onmc run timeout", cost
    if code == 127:
        return f"onmc unavailable: {out[:200]}", cost
    # A denied capability or an unavailable verifier means ONMC never executed.
    # That is an instrument failure, not evidence about the agent — record it
    # loudly instead of banking a free loss for the treatment arm (rule 13).
    for marker in ("capability was denied", "verifier=deny", "verifier-unavailable"):
        if marker in out:
            return f"onmc did not execute ({marker})", cost
    return None, cost


RUNNERS = {
    Condition.BARE_AGENT: run_bare_agent,
    Condition.ONMC_CURRENT: run_onmc,
}


def run_cell(
    task: TaskSpec, condition: Condition, trial: int, cfg: EvalConfig, cache_root: Path
) -> TrialRecord:
    slug = f"{task.task_id}.{condition.value}.t{trial}"
    dest = cfg.workdir / "runs" / slug
    dest.parent.mkdir(parents=True, exist_ok=True)
    cache = cache_root / task.repo.name

    started = time.monotonic()

    def _infra(err: str) -> TrialRecord:
        return TrialRecord(task.task_id, condition.value, trial, False, 0.0, infra_error=err)

    err = prepare_clone(task, dest, cache)
    if err:
        return _infra(err)

    python, err = prepare_venv(dest, REPO_TEST_DEPS.get(task.repo.name, ()))
    if err or python is None:
        return _infra(err or "venv unavailable")

    # Validity gate 1: pristine tests PASS. Distinguishes "regression broke it"
    # from "the verifier cannot run at all".
    err = guard_pristine_verifier(task, dest, cfg, python)
    if err:
        return _infra(err)

    err = inject_regression(task, dest)
    if err:
        return _infra(err)

    # Validity gate 2: the regression actually breaks the verifier.
    err = guard_regression_active(task, dest, cfg, python)
    if err:
        return _infra(err)

    if cfg.dry_run:
        return TrialRecord(
            task.task_id, condition.value, trial, False, 0.0, notes="dry-run: agent not invoked"
        )

    infra, cost = RUNNERS[condition](task, dest, cfg, python)
    diff_lines, tests_touched = _observed_change(dest)
    passed, out = verify(task, dest, cfg, python)
    latency = (time.monotonic() - started) * 1000.0
    note = "" if passed else out.strip().splitlines()[-1][:160] if out.strip() else ""
    if passed and tests_touched:
        # The prompt forbids editing tests. A "pass" that edited a test is a
        # false green, not a repair — score it as a failure and say why.
        passed = False
        note = "false green: agent modified a test file"
    return TrialRecord(
        task.task_id,
        condition.value,
        trial,
        passed,
        latency,
        infra_error=infra,
        notes=note,
        cost_usd=cost,
        diff_lines=diff_lines,
        tests_touched=tests_touched,
    )


def summarize(
    records: list[TrialRecord], conditions: list[Condition], *, seed: int
) -> dict[str, object]:
    summary: dict[str, object] = {}
    for cond in conditions:
        rows = [r for r in records if r.condition == cond.value]
        usable = [r for r in rows if r.infra_error is None]
        outcomes = [1.0 if r.passed else 0.0 for r in usable]
        costs = [r.cost_usd for r in usable if r.cost_usd is not None]
        ci: tuple[float, float] | None = None
        if outcomes:
            ci = bootstrap_ci(outcomes, seed=derive_seed(seed, cond.value, "pass"))
        summary[cond.value] = {
            "cells": len(rows),
            "usable": len(usable),
            "infra_failures": len(rows) - len(usable),
            "passed": int(sum(outcomes)),
            "pass_at_1": round(mean(outcomes), 4) if outcomes else None,
            "pass_at_1_ci95": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
            "pass_hat_k": _pass_hat_k(usable),
            "mean_latency_ms": (
                round(mean([r.latency_ms for r in usable]), 1) if usable else None
            ),
            "median_latency_ms": round(median([r.latency_ms for r in usable]), 1)
            if usable
            else None,
            "latency_variance": round(variance([r.latency_ms for r in usable]), 1)
            if len(usable) > 1
            else None,
            "mean_cost_usd": round(mean(costs), 4) if costs else None,
            "cost_reported_cells": len(costs),
            "false_greens_blocked": sum(1 for r in rows if r.tests_touched),
            "failure_taxonomy": _taxonomy(rows),
        }
    return summary


def _taxonomy(rows: list[TrialRecord]) -> dict[str, int]:
    """Count failures by cause so a null result can be explained, not just stated.

    ``no_change`` separates "the agent did nothing" from "the agent tried and was
    wrong" — the two demand completely different fixes, and collapsing them into a
    single failure count is how a broken instrument hides.
    """
    counts: dict[str, int] = {}
    for row in rows:
        if row.infra_error is not None:
            key = "infra"
        elif row.passed:
            continue
        elif row.tests_touched:
            key = "false_green_test_edit"
        elif row.diff_lines == 0:
            key = "no_change"
        else:
            key = "wrong_change"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _pass_hat_k(rows: list[TrialRecord]) -> float | None:
    """Consistency: the fraction of tasks that passed on EVERY usable trial."""
    by_task: dict[str, list[bool]] = {}
    for row in rows:
        by_task.setdefault(row.task_id, []).append(row.passed)
    if not by_task:
        return None
    return round(mean([1.0 if all(v) else 0.0 for v in by_task.values()]), 4)


def paired_analysis(
    records: list[TrialRecord], baseline: Condition, treatment: Condition, *, seed: int
) -> dict[str, object]:
    """Per-task paired delta with a bootstrap CI over the per-task deltas.

    Pairing is per TASK (mean pass-rate across that task's usable trials), so a
    task that is easy or hard for both arms cannot drive the delta.
    """

    def rates(cond: Condition) -> dict[str, float]:
        buckets: dict[str, list[float]] = {}
        for row in records:
            if row.condition != cond.value or row.infra_error is not None:
                continue
            buckets.setdefault(row.task_id, []).append(1.0 if row.passed else 0.0)
        return {task: mean(vals) for task, vals in buckets.items() if vals}

    base_rates, treat_rates = rates(baseline), rates(treatment)
    deltas = paired_deltas(base_rates, treat_rates)
    if not deltas:
        return {"paired_tasks": 0, "mean_delta": None, "delta_ci95": None}
    values = [deltas[key] for key in sorted(deltas)]
    low, high = bootstrap_ci(values, seed=derive_seed(seed, "paired", "delta"))
    return {
        "baseline": baseline.value,
        "treatment": treatment.value,
        "paired_tasks": len(values),
        "per_task_delta": {key: round(deltas[key], 4) for key in sorted(deltas)},
        "mean_delta": round(mean(values), 4),
        "delta_ci95": [round(low, 4), round(high, 4)],
        "significant": bool(low > 0.0 or high < 0.0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--max-total-usd",
        type=float,
        default=10.0,
        help="Hard spend ceiling. Remaining cells are recorded as budget-stopped, never dropped.",
    )
    ap.add_argument("--max-cost-usd", type=float, default=1.0, help="Per-run agent cost cap.")
    args = ap.parse_args()

    manifest = PortfolioManifest.from_dict(json.loads(Path(args.manifest).read_text()))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    cache_root = workdir / "cache"
    cache_root.mkdir(parents=True, exist_ok=True)

    trials = args.trials or manifest.experiment.trials
    conditions = list(manifest.experiment.conditions)
    cfg = EvalConfig(
        workdir=workdir,
        trials=trials,
        dry_run=args.dry_run,
        max_cost_usd=args.max_cost_usd,
        max_total_usd=args.max_total_usd,
    )

    onmc_bin, onmc_err = prepare_onmc_venv(workdir)
    if onmc_err:
        print(f"FATAL: {onmc_err}", file=sys.stderr)
        return 1
    cfg.onmc_bin = onmc_bin

    cells: list[tuple[TaskSpec, Condition, int]] = [
        (task, cond, t)
        for task in manifest.tasks
        for cond in conditions
        for t in range(1, trials + 1)
    ]
    rng = random.Random(manifest.experiment.seed)  # noqa: S311 - shuffling trial order, not crypto
    rng.shuffle(cells)  # randomized condition order (rule 7)

    records: list[TrialRecord] = []
    spent = 0.0
    budget_stopped = 0
    for idx, (task, cond, trial) in enumerate(cells, start=1):
        if spent >= cfg.max_total_usd:
            budget_stopped += 1
            records.append(
                TrialRecord(
                    task.task_id,
                    cond.value,
                    trial,
                    False,
                    0.0,
                    infra_error=f"budget-stopped at ${spent:.2f} of ${cfg.max_total_usd:.2f}",
                )
            )
            continue
        rec = run_cell(task, cond, trial, cfg, cache_root)
        records.append(rec)
        spent += rec.cost_usd or 0.0
        print(
            f"[{idx}/{len(cells)}] {rec.task_id} {rec.condition} t{rec.trial}: "
            f"passed={rec.passed} cost=${rec.cost_usd or 0.0:.3f} spent=${spent:.2f} "
            f"infra={rec.infra_error or '-'}",
            flush=True,
        )

    seed = manifest.experiment.seed
    report = {
        "experiment_id": manifest.experiment.experiment_id.value,
        "task_set_revision": manifest.experiment.task_set_revision,
        "audit_status": manifest.audit_status.value,
        "code_sha": manifest.experiment.environment.code_sha,
        "code_sha_under_test": code_sha(),
        "trials_per_cell": trials,
        "conditions": [c.value for c in conditions],
        "repos": sorted({t.repo.name for t in manifest.tasks}),
        "metric_label": MetricLabel.MEASURED.value,
        "total_cost_usd": round(spent, 4),
        "budget_ceiling_usd": cfg.max_total_usd,
        "budget_stopped_cells": budget_stopped,
        "summary": summarize(records, conditions, seed=seed),
        "paired": (
            paired_analysis(records, conditions[0], conditions[1], seed=seed)
            if len(conditions) >= 2
            else {}
        ),
        "records": [r.to_dict() for r in records],
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    headline = {"summary": report["summary"], "paired": report["paired"]}
    print(json.dumps(headline, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
