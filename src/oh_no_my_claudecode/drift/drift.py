"""Pure, offline heuristic for institutional-memory *enforcement*.

onmc already **stores** decisions, invariants, and conventions.  This module
turns that stored memory into a *guard*: :func:`check_drift` scans the current
code for textual evidence that a recorded decision/invariant/convention is being
**violated**, and surfaces those spots as candidates for human review.

Honesty is the whole point.  Drift is a *heuristic over text* — it never claims
certainty.  It flags a violation only when a memory carries a clear, checkable
directive ("never use X", "always use Y", "must Z", "prefer A over B", "decided
to adopt <thing>") and the current code contains a simple, deterministic
contradiction of it.  Every finding carries a ``confidence`` in ``[0, 1]`` that
reflects how strong the *textual* signal is — low confidence means "possible,
look here", not "definitely wrong".

Design constraints
------------------
- **Pure & deterministic**: given the same memories and the same
  ``(path, text)`` stream, the report is byte-identical.  No storage, network,
  or LLM access lives here — the CLI layer injects both inputs.
- **Injectable file provider**: the code scan is driven by a caller-supplied
  iterable of ``(path, text)`` pairs, so the heuristic is trivially unit-tested
  with in-memory fixtures and never needs a real filesystem.
- **No ReDoS, no host-substring checks**: signals are extracted with simple
  token / substring / set logic and short anchored patterns only.  There are no
  unbounded-backtracking regexes and no ``"host" in url`` style membership tests.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from oh_no_my_claudecode.models.memory import MemoryEntry, MemoryKind

__all__ = [
    "DriftFinding",
    "DriftReport",
    "FileTextProvider",
    "check_drift",
    "default_file_text_provider",
    "extract_signal",
    "DriftSignal",
]

# A provider yields ``(relative-path, source-text)`` pairs.  Kept as a plain
# callable alias so tests can inject a lambda returning an in-memory list.
FileTextProvider = Callable[[], Iterable[tuple[str, str]]]

# Kinds whose memories can carry an enforceable directive.
_CHECKABLE_KINDS = frozenset(
    {MemoryKind.DECISION, MemoryKind.INVARIANT, MemoryKind.VALIDATION_RULE, MemoryKind.DOC_FACT}
)

# Directive markers.  Matched as lowercase substrings on a normalised statement
# — no regex, so there is no backtracking risk on adversarial memory text.
_NEVER_MARKERS = (
    "never use",
    "never import",
    "do not use",
    "don't use",
    "must not use",
    "avoid using",
)
_ALWAYS_MARKERS = ("always use", "always import", "must use", "must always")
_ADOPT_MARKERS = ("adopt ", "decided to adopt", "switched to", "standardise on", "standardize on")
_PREFER_MARKERS = ("prefer ", "prefer using")

# Directories never worth scanning (mirrors reuse.radar._SKIP_DIRS).
_SKIP_DIRS = frozenset({".venv", "venv", ".git", "__pycache__", "tests", ".tox", ".mypy_cache"})

# Bound the scan so a huge repo can never blow up the check.
_MAX_FILES = 2000

# Confidence tiers.  Strong = an explicit "never/always <token>" directive with a
# concrete token found verbatim in code.  Moderate = an "adopt/prefer" style
# directive (softer intent).  These are intentionally conservative: drift is a
# review aid, not a proof.
_CONF_STRONG = 0.75
_CONF_MODERATE = 0.5


@dataclass(frozen=True)
class DriftSignal:
    """A checkable directive extracted from one memory.

    Attributes
    ----------
    polarity:
        ``"forbid"`` — the token must NOT appear in code (``never use X``).
        ``"require"`` — the token SHOULD appear somewhere in code (``always use
        Y`` / ``adopt Y``); its total absence is the (weaker) drift signal.
    token:
        The lowercase code token the directive is about (e.g. ``requests``).
    confidence:
        Base confidence for a finding derived from this signal.
    description:
        Short human phrase describing what the signal checks.
    """

    polarity: str
    token: str
    confidence: float
    description: str


@dataclass
class DriftFinding:
    """One candidate violation of a recorded memory, for human review."""

    memory_id: str
    kind: str
    statement: str
    signal: str
    confidence: float
    evidence: str


@dataclass
class DriftReport:
    """The outcome of a drift scan."""

    findings: list[DriftFinding] = field(default_factory=list)
    checked: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable view of the report (deterministic order)."""
        return {
            "checked": self.checked,
            "findings": [
                {
                    "memory_id": f.memory_id,
                    "kind": f.kind,
                    "statement": f.statement,
                    "signal": f.signal,
                    "confidence": round(f.confidence, 3),
                    "evidence": f.evidence,
                }
                for f in self.findings
            ],
            "notes": list(self.notes),
        }


def _statement_of(memory: MemoryEntry) -> str:
    """The human directive text of a memory (title + summary)."""
    parts = [memory.title.strip(), memory.summary.strip()]
    return " ".join(p for p in parts if p)


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    """Return the first marker (in *markers* order) that appears in *text*."""
    for marker in markers:
        if marker in text:
            return marker
    return None


def _token_after(text: str, marker: str) -> str | None:
    """Extract the first code-ish word following *marker* in *text*.

    Deterministic, no regex: split the tail on whitespace and take the first
    token, stripping surrounding punctuation/quotes.  A code token here means an
    identifier-like word (letters, digits, ``_``, ``.``, ``-``); anything else
    yields ``None`` so we never invent a spurious signal.
    """
    idx = text.find(marker)
    if idx < 0:
        return None
    tail = text[idx + len(marker) :].strip()
    if not tail:
        return None
    raw = tail.split()[0]
    token = raw.strip("`'\"()[]{}.,:;!?").lower()
    if not token:
        return None
    # Keep only identifier-ish tokens; reject prose words that slipped through by
    # requiring the token be a plausible module/symbol name.
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_.-")
    if not set(token) <= allowed:
        return None
    # A bare stopword ("the", "a") is not a code token worth checking.
    if token in {"the", "a", "an", "it", "this", "that", "them", "these"}:
        return None
    return token


def extract_signal(memory: MemoryEntry) -> DriftSignal | None:
    """Extract a single checkable directive from *memory*, or ``None``.

    Pure and deterministic.  Recognises four directive shapes on the memory's
    normalised statement:

    - ``never use X`` / ``do not use X`` → forbid ``X`` (strong).
    - ``always use Y`` / ``must use Y``   → require ``Y`` (strong).
    - ``adopt Z`` / ``switched to Z``     → require ``Z`` (moderate).
    - ``prefer A over B``                 → forbid ``B`` if present, else require
      ``A`` (moderate).

    Only memories of a checkable kind are considered; everything else returns
    ``None``.
    """
    if memory.kind not in _CHECKABLE_KINDS:
        return None

    statement = _statement_of(memory).lower()
    if not statement:
        return None

    # prefer A over B — check first so "prefer" isn't swallowed by other markers.
    prefer_marker = _first_marker(statement, _PREFER_MARKERS)
    if prefer_marker is not None and " over " in statement:
        after = statement.split(" over ", 1)[1].strip()
        losing = after.split()[0].strip("`'\"()[]{}.,:;!?").lower() if after else ""
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_.-")
        if losing and set(losing) <= allowed and losing not in {"the", "a", "an"}:
            return DriftSignal(
                polarity="forbid",
                token=losing,
                confidence=_CONF_MODERATE,
                description=f"prefer-over: code still uses '{losing}'",
            )

    never_marker = _first_marker(statement, _NEVER_MARKERS)
    if never_marker is not None:
        token = _token_after(statement, never_marker)
        if token is not None:
            return DriftSignal(
                polarity="forbid",
                token=token,
                confidence=_CONF_STRONG,
                description=f"forbidden: '{token}' should not appear",
            )

    always_marker = _first_marker(statement, _ALWAYS_MARKERS)
    if always_marker is not None:
        token = _token_after(statement, always_marker)
        if token is not None:
            return DriftSignal(
                polarity="require",
                token=token,
                confidence=_CONF_STRONG,
                description=f"required: '{token}' expected somewhere in code",
            )

    adopt_marker = _first_marker(statement, _ADOPT_MARKERS)
    if adopt_marker is not None:
        token = _token_after(statement, adopt_marker)
        if token is not None:
            return DriftSignal(
                polarity="require",
                token=token,
                confidence=_CONF_MODERATE,
                description=f"adopted: '{token}' expected somewhere in code",
            )

    return None


def _token_in_text(token: str, text: str) -> bool:
    """Return True if *token* appears in *text* as a whole word.

    Deterministic, no regex.  A code token like ``requests`` should match
    ``import requests`` but not ``requests_helper`` — so we require the
    surrounding characters not to be identifier characters.  This is a simple
    linear scan; there is no backtracking and no host-substring shortcut.
    """
    token = token.lower()
    if not token:
        return False
    hay = text.lower()
    ident = set("abcdefghijklmnopqrstuvwxyz0123456789_")
    start = 0
    n = len(token)
    while True:
        idx = hay.find(token, start)
        if idx < 0:
            return False
        before_ok = idx == 0 or hay[idx - 1] not in ident
        after_pos = idx + n
        after_ok = after_pos >= len(hay) or hay[after_pos] not in ident
        if before_ok and after_ok:
            return True
        start = idx + 1


def _first_evidence_line(token: str, text: str) -> str:
    """Return a short, trimmed line of *text* containing *token* (whole word)."""
    for lineno, line in enumerate(text.splitlines(), start=1):
        if _token_in_text(token, line):
            trimmed = line.strip()
            if len(trimmed) > 120:
                trimmed = trimmed[:117] + "..."
            return f"L{lineno}: {trimmed}"
    return ""


def check_drift(
    memories: list[MemoryEntry],
    file_text_provider: FileTextProvider,
    *,
    min_confidence: float = 0.0,
) -> DriftReport:
    """Scan code for candidate violations of recorded memories.

    Parameters
    ----------
    memories:
        The institutional memories to enforce.  Only ``decision`` /
        ``invariant`` / ``validation_rule`` / ``doc_fact`` kinds carry a
        checkable directive; others are ignored.
    file_text_provider:
        A zero-arg callable yielding ``(path, text)`` pairs to scan.  Injected so
        the heuristic is pure/testable; the CLI passes
        :func:`default_file_text_provider`.
    min_confidence:
        Findings below this confidence are dropped (still counts toward
        ``checked``).

    Returns
    -------
    DriftReport
        ``findings`` are sorted by descending confidence then memory id for a
        stable, review-friendly order.  ``notes`` explains graceful-degradation
        cases (no memories, no checkable directives, no files).
    """
    report = DriftReport()

    if not memories:
        report.notes.append("no memories in brain — nothing to check")
        return report

    signals: list[tuple[MemoryEntry, DriftSignal]] = []
    for memory in memories:
        signal = extract_signal(memory)
        if signal is not None:
            signals.append((memory, signal))
    report.checked = len(signals)

    if not signals:
        report.notes.append(
            "no checkable directives found in memory "
            "(looked for 'never/always use X', 'adopt Y', 'prefer A over B')"
        )
        return report

    # Materialise the file stream once (bounded) so every signal scans the same
    # deterministic snapshot.
    files = list(file_text_provider())
    if not files:
        report.notes.append("no source files to scan")
        return report

    findings: list[DriftFinding] = []
    for memory, signal in signals:
        statement = _statement_of(memory)
        if signal.polarity == "forbid":
            # Violation = the forbidden token DOES appear.  Report the first hit.
            for path, text in files:
                if _token_in_text(signal.token, text):
                    line = _first_evidence_line(signal.token, text)
                    evidence = f"{path} — {line}" if line else path
                    findings.append(
                        DriftFinding(
                            memory_id=memory.id,
                            kind=str(memory.kind.value),
                            statement=statement,
                            signal=signal.description,
                            confidence=signal.confidence,
                            evidence=evidence,
                        )
                    )
                    break
        else:  # require
            # Violation = the required token appears NOWHERE.  Softer signal, so
            # halve the confidence: absence is weaker evidence than presence.
            present = any(_token_in_text(signal.token, text) for _, text in files)
            if not present:
                findings.append(
                    DriftFinding(
                        memory_id=memory.id,
                        kind=str(memory.kind.value),
                        statement=statement,
                        signal=signal.description,
                        confidence=round(signal.confidence * 0.5, 3),
                        evidence=f"'{signal.token}' not found in any scanned file",
                    )
                )

    findings = [f for f in findings if f.confidence >= min_confidence]
    findings.sort(key=lambda f: (-f.confidence, f.memory_id))
    report.findings = findings

    if not findings:
        report.notes.append("no drift detected — code appears consistent with recorded memory")
    return report


def _iter_repo_python_files(repo_root: Path) -> Iterator[tuple[str, str]]:
    """Yield ``(relative-posix-path, text)`` for bounded tracked ``*.py`` files.

    Mirrors :func:`reuse.radar._iter_python_files`: deterministic sorted order,
    skips vendor/cache/test dirs, caps at ``_MAX_FILES``, and skips any file it
    cannot read as UTF-8 (never raising).
    """
    count = 0
    for path in sorted(repo_root.rglob("*.py")):
        rel_parts = path.relative_to(repo_root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        yield path.relative_to(repo_root).as_posix(), text
        count += 1
        if count >= _MAX_FILES:
            break


def default_file_text_provider(repo_root: Path) -> FileTextProvider:
    """Return a provider that walks *repo_root*'s bounded ``*.py`` files.

    The returned callable re-walks on each invocation; :func:`check_drift`
    materialises it once per run.
    """

    def _provider() -> Iterable[tuple[str, str]]:
        return list(_iter_repo_python_files(repo_root))

    return _provider
