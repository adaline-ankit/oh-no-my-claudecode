"""Pure, deterministic core for the ``leash`` guardrails-as-game feature.

Defines the ``Rule`` dataclass, violation detection, and compliance scoring.
All functions are pure over in-memory data, with injectable ``leash_dir``
and ``history_path`` arguments so tests run without touching the real
filesystem or real clock.

Pattern matching
----------------
Each rule carries a ``pattern`` string.  Matching is deterministic and
offline — no LLM.  The engine tries to compile the pattern as a regex;
if ``re.compile`` raises :class:`re.error` the pattern is treated as a
literal substring (case-insensitive) instead.  The final compiled
strategy is recorded in :attr:`Rule.match_strategy`:

- ``"regex"``    — the pattern compiled cleanly and is used via ``re.search``.
- ``"literal"``  — the pattern is used via substring containment
  (``pattern.lower() in text.lower()``).

Separateness from related features
-----------------------------------
- ``drift``  — enforces *memory-directives* against *source code* files.
- ``wrap``   — installs Claude Code hooks that intercept tool calls at
  runtime.
- ``leash``  — lets the user define *ad-hoc session rules* and score
  compliance against event text.  Lightweight, gamified, no code analysis.
"""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Sub-directory under the repo root where leash state is persisted.
LEASH_SUBDIR = Path(".onmc") / "leash"

#: JSON file holding the rule list.
RULES_FILE = "rules.json"

#: JSONL file holding the check history for scoring.
HISTORY_FILE = "history.jsonl"

#: Valid severity levels.
SEVERITY_SOFT = "soft"
SEVERITY_HARD = "hard"
_VALID_SEVERITIES = {SEVERITY_SOFT, SEVERITY_HARD}

#: Grade thresholds (compliance_pct → letter).
_GRADE_THRESHOLDS: list[tuple[float, str]] = [
    (0.95, "A"),
    (0.80, "B"),
    (0.60, "C"),
    (0.40, "D"),
    (0.0, "F"),
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Rule:
    """A single user-defined guardrail rule.

    Attributes
    ----------
    id:
        Stable identifier (UUID4 hex without dashes, prefixed ``rule_``).
    text:
        Human-readable description of the rule (as the user typed it).
    pattern:
        The matching pattern: tried as a regex first, falls back to literal
        substring if compilation fails.
    severity:
        ``"soft"`` (advisory) or ``"hard"`` (violation triggers a "buzz").
    match_strategy:
        ``"regex"`` or ``"literal"`` — resolved at creation time.
    _compiled:
        Internal compiled regex or ``None`` when the strategy is ``"literal"``.
    """

    id: str
    text: str
    pattern: str
    severity: str
    match_strategy: str
    _compiled: re.Pattern[str] | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict (excludes the compiled pattern)."""
        return {
            "id": self.id,
            "text": self.text,
            "pattern": self.pattern,
            "severity": self.severity,
            "match_strategy": self.match_strategy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        """Deserialise from a JSON dict and re-compile the pattern."""
        pattern = str(data.get("pattern", ""))
        strategy, compiled = _compile_pattern(pattern)
        return cls(
            id=str(data.get("id", "")),
            text=str(data.get("text", "")),
            pattern=pattern,
            severity=str(data.get("severity", SEVERITY_SOFT)),
            match_strategy=strategy,
            _compiled=compiled,
        )


@dataclass
class Violation:
    """A single rule violation for a checked event.

    Attributes
    ----------
    rule_id:
        The ``id`` of the matching rule.
    rule_text:
        Human-readable description of the violated rule.
    severity:
        ``"soft"`` or ``"hard"``.
    matched:
        The portion of the input text that triggered the match (first
        ``re.Match.group()`` for regex rules; the full pattern string for
        literal matches).
    buzz:
        ``True`` only for ``"hard"`` violations.
    """

    rule_id: str
    rule_text: str
    severity: str
    matched: str
    buzz: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_text": self.rule_text,
            "severity": self.severity,
            "matched": self.matched,
            "buzz": self.buzz,
        }


@dataclass
class ScoreCard:
    """Compliance score computed from check history.

    Attributes
    ----------
    total_checks:
        Total number of ``check`` events recorded.
    passed:
        Events with zero violations.
    violated:
        Events with at least one violation.
    compliance_pct:
        ``passed / total_checks * 100`` (0.0 when no history).
    streak:
        Consecutive clean checks from the END of history (0 when last event
        was a violation or no history exists).
    grade:
        Letter grade: A (≥95%), B (≥80%), C (≥60%), D (≥40%), F (<40%).
        ``"N/A"`` when there is no history.
    """

    total_checks: int
    passed: int
    violated: int
    compliance_pct: float
    streak: int
    grade: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_checks": self.total_checks,
            "passed": self.passed,
            "violated": self.violated,
            "compliance_pct": round(self.compliance_pct, 2),
            "streak": self.streak,
            "grade": self.grade,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compile_pattern(pattern: str) -> tuple[str, re.Pattern[str] | None]:
    """Try to compile *pattern* as a regex.

    Returns
    -------
    tuple[str, re.Pattern | None]
        ``("regex", compiled)`` on success or ``("literal", None)`` on failure.
    """
    if not pattern:
        return "literal", None
    try:
        compiled = re.compile(pattern, re.IGNORECASE)
        return "regex", compiled
    except re.error:
        return "literal", None


def _make_rule_id() -> str:
    """Generate a unique rule identifier."""
    return "rule_" + uuid.uuid4().hex[:12]


def _read_json(path: Path) -> Any:
    """Read JSON from *path*; return ``None`` when absent or malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON to *path*, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read JSONL, skipping malformed lines. Returns [] when absent."""
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if isinstance(entry, dict):
                out.append(entry)
        except json.JSONDecodeError:
            pass
    return out


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """Append one JSON line to *path*, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Rule store
# ---------------------------------------------------------------------------


def load_rules(*, leash_dir: Path) -> list[Rule]:
    """Load all rules from *leash_dir*/rules.json."""
    data = _read_json(leash_dir / RULES_FILE)
    if not isinstance(data, list):
        return []
    rules: list[Rule] = []
    for item in data:
        if isinstance(item, dict):
            with contextlib.suppress(Exception):
                rules.append(Rule.from_dict(item))
    return rules


def save_rules(rules: list[Rule], *, leash_dir: Path) -> None:
    """Persist *rules* to *leash_dir*/rules.json."""
    _write_json(leash_dir / RULES_FILE, [r.to_dict() for r in rules])


def add_rule(text: str, *, severity: str = SEVERITY_SOFT, leash_dir: Path) -> Rule:
    """Append a new rule and persist it.

    The ``pattern`` defaults to *text* (the user's rule description).  This
    means substring / regex matching is applied directly to the rule text —
    simple and predictable.

    Parameters
    ----------
    text:
        Human-readable rule description *and* default match pattern.
    severity:
        ``"soft"`` (advisory) or ``"hard"`` (triggers a buzz).
    leash_dir:
        Injectable directory for the rule store.

    Returns
    -------
    Rule
        The newly created rule.

    Raises
    ------
    ValueError
        When *severity* is not ``"soft"`` or ``"hard"``.
    """
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"severity must be 'soft' or 'hard', got {severity!r}")
    strategy, compiled = _compile_pattern(text)
    rule = Rule(
        id=_make_rule_id(),
        text=text,
        pattern=text,
        severity=severity,
        match_strategy=strategy,
        _compiled=compiled,
    )
    rules = load_rules(leash_dir=leash_dir)
    rules.append(rule)
    save_rules(rules, leash_dir=leash_dir)
    return rule


def remove_rule(rule_id: str, *, leash_dir: Path) -> bool:
    """Remove the rule with *rule_id*.

    Returns
    -------
    bool
        ``True`` if the rule was found and removed; ``False`` if not found.
    """
    rules = load_rules(leash_dir=leash_dir)
    new_rules = [r for r in rules if r.id != rule_id]
    if len(new_rules) == len(rules):
        return False
    save_rules(new_rules, leash_dir=leash_dir)
    return True


# ---------------------------------------------------------------------------
# Check engine
# ---------------------------------------------------------------------------


def check(text: str, rules: list[Rule]) -> list[Violation]:
    """Evaluate *text* against *rules* and return all violations.

    Matching is case-insensitive.  For regex rules, the matched string is
    ``m.group()`` (the first match).  For literal rules, the matched string is
    the pattern itself.

    Parameters
    ----------
    text:
        The event text or action description to evaluate.
    rules:
        The set of rules to evaluate against.

    Returns
    -------
    list[Violation]
        All violated rules; empty when the text is compliant.
    """
    violations: list[Violation] = []
    for rule in rules:
        matched: str | None = None
        if rule.match_strategy == "regex" and rule._compiled is not None:
            m = rule._compiled.search(text)
            if m:
                matched = m.group()
        else:
            # literal substring (case-insensitive)
            if rule.pattern.lower() in text.lower():
                matched = rule.pattern
        if matched is not None:
            violations.append(
                Violation(
                    rule_id=rule.id,
                    rule_text=rule.text,
                    severity=rule.severity,
                    matched=matched,
                    buzz=(rule.severity == SEVERITY_HARD),
                )
            )
    return violations


def record_check(
    text: str,
    violations: list[Violation],
    *,
    leash_dir: Path,
    ts: str,
) -> None:
    """Append a check event to the history JSONL for scoring.

    Parameters
    ----------
    text:
        The event text that was checked (stored truncated to 200 chars).
    violations:
        The violations returned by :func:`check`.
    leash_dir:
        Injectable directory for the history file.
    ts:
        ISO-8601 timestamp (caller-supplied for determinism).
    """
    record: dict[str, Any] = {
        "ts": ts,
        "text_preview": text[:200],
        "violation_count": len(violations),
        "has_hard": any(v.severity == SEVERITY_HARD for v in violations),
    }
    _append_jsonl(leash_dir / HISTORY_FILE, record)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score(history: list[dict[str, Any]]) -> ScoreCard:
    """Compute a :class:`ScoreCard` from raw history records.

    Parameters
    ----------
    history:
        List of dicts as written by :func:`record_check` — each must have
        ``"violation_count"`` as an int.  Malformed records are skipped.

    Returns
    -------
    ScoreCard
        Deterministic compliance score; no I/O, no randomness, no clock.
    """
    valid: list[bool] = []  # True = passed (no violations)
    for rec in history:
        vc = rec.get("violation_count")
        if not isinstance(vc, int):
            continue
        valid.append(vc == 0)

    total = len(valid)
    if total == 0:
        return ScoreCard(
            total_checks=0,
            passed=0,
            violated=0,
            compliance_pct=0.0,
            streak=0,
            grade="N/A",
        )

    passed = sum(1 for v in valid if v)
    violated = total - passed
    pct = passed / total * 100.0

    # streak: consecutive clean checks from the end
    streak = 0
    for is_pass in reversed(valid):
        if is_pass:
            streak += 1
        else:
            break

    # grade
    grade = "F"
    for threshold, letter in _GRADE_THRESHOLDS:
        if pct >= threshold * 100:
            grade = letter
            break

    return ScoreCard(
        total_checks=total,
        passed=passed,
        violated=violated,
        compliance_pct=pct,
        streak=streak,
        grade=grade,
    )


def load_score(*, leash_dir: Path) -> ScoreCard:
    """Load history from *leash_dir* and compute a :class:`ScoreCard`."""
    history = _read_jsonl(leash_dir / HISTORY_FILE)
    return score(history)
