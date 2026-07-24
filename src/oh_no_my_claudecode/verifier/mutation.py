"""Deterministic mutation / fault-injection harness — do the tests bite?

A suite that stays green when the code under test is deliberately broken is a
weak suite: it "verifies" nothing. This harness generates a fixed, deterministic
set of source mutants for a function under test and asks an injected runner
whether the suite still passes against each one. A mutant the suite fails to
catch (tests still pass) has **survived** — a false-green signature.

Purity contract, matching :mod:`oh_no_my_claudecode.verifydiff.checker`:

- Mutant *generation* is pure text transformation over the supplied source. No
  ``import`` hacking, no ``exec``, no AST execution.
- Mutant *evaluation* is delegated to an injected
  :data:`MutantTestRunner` seam: ``Callable[[Mutant], Outcome]``. The real CLI
  wires a runner that writes the mutated source and shells the test command;
  unit tests inject a fake that decides survival from the mutant alone. The
  harness itself never runs a subprocess.

Determinism: with no ``limit`` the full mutant set is emitted in a stable order.
With a ``limit`` the subset is chosen reproducibly from a ``seed`` so the same
``(source, seed, limit)`` always yields the same battery.

Outcomes reuse :class:`oh_no_my_claudecode.proof_graph.models.Outcome` so a
surviving mutant slots into the same evidence vocabulary the proof graph uses.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from oh_no_my_claudecode.proof_graph.models import Outcome


class MutationOperator(StrEnum):
    """The fixed operator battery. Small, language-agnostic, and deterministic."""

    FLIP_COMPARISON = "flip-comparison"
    OFF_BY_ONE = "off-by-one"
    NEGATE_BOOLEAN = "negate-boolean"
    DROP_STATEMENT = "drop-statement"


@dataclass(frozen=True, slots=True)
class FunctionUnderTest:
    """The source of the function a suite claims to verify."""

    qualname: str
    source: str

    def __post_init__(self) -> None:
        if not self.qualname.strip():
            raise ValueError("FunctionUnderTest.qualname must not be empty")


@dataclass(frozen=True, slots=True)
class Mutant:
    """One fault injected at one location, carrying the mutated source.

    The injected runner receives this and decides survival; ``mutated`` is the
    full mutated source so the runner can apply it without re-deriving anything.
    """

    mutant_id: str
    operator: MutationOperator
    qualname: str
    lineno: int
    original: str
    mutated: str


@dataclass(frozen=True, slots=True)
class MutationReport:
    """Aggregate outcome of a mutation campaign."""

    total: int
    killed: tuple[str, ...]
    survived: tuple[Mutant, ...]
    errored: tuple[str, ...]

    @property
    def survivors(self) -> int:
        return len(self.survived)

    @property
    def mutation_score(self) -> float:
        """Fraction of graded mutants the suite killed (survivors = weak tests).

        Errored mutants are excluded from the denominator — they were never
        graded. Returns ``1.0`` when there is nothing to grade.
        """
        graded = len(self.killed) + len(self.survived)
        if graded == 0:
            return 1.0
        return len(self.killed) / graded

    @property
    def weak_tests(self) -> bool:
        """``True`` when at least one mutant survived — the suite has a hole."""
        return bool(self.survived)


#: A runner applies one mutant and reports the suite outcome against it.
#: ``PASSED`` means the suite did NOT notice the fault (the mutant survived);
#: ``FAILED`` means the suite caught it (killed); ``ERROR``/``SKIPPED`` are
#: recorded as ungraded.
MutantTestRunner = Callable[[Mutant], Outcome]

# Comparison operators are flipped to their logical opposite. Order matters:
# multi-char operators are tried before their single-char prefixes so ``<=``
# is never mis-read as ``<``.
_COMPARISON_FLIP: tuple[tuple[str, str], ...] = (
    ("==", "!="),
    ("!=", "=="),
    ("<=", ">"),
    (">=", "<"),
    ("<", ">="),
    (">", "<="),
)

# Boolean / logical tokens are negated. Word tokens use boundary matching so
# ``android`` is never mutated on account of the ``and`` inside it.
_BOOLEAN_FLIP: tuple[tuple[str, str], ...] = (
    ("True", "False"),
    ("False", "True"),
    ("and", "or"),
    ("or", "and"),
)

_INT_LITERAL_RE = re.compile(r"(?<![\w.])(\d+)(?![\w.])")
_WORD_TOKEN_RE = re.compile(r"[A-Za-z]+")
# A statement worth dropping: an assignment or a ``return``. We never drop
# structural lines (def/if/for/while/comment/blank) because replacing them with
# ``pass`` would not compile.
_DROPPABLE_RE = re.compile(r"^(\s*)(return\b|[A-Za-z_][\w.\[\]]*\s*(?:[-+*/]?=)[^=])")


def _iter_comparison_lines(line: str) -> list[tuple[int, str]]:
    """Yield ``(column, mutated_line)`` for each comparison flip in *line*."""
    out: list[tuple[int, str]] = []
    for src, dst in _COMPARISON_FLIP:
        start = 0
        while True:
            idx = line.find(src, start)
            if idx == -1:
                break
            # Skip ``==``-family matches that are actually part of a longer op
            # already handled (e.g. ``<=`` when scanning ``<``).
            nxt = line[idx + len(src) : idx + len(src) + 1]
            prv = line[idx - 1 : idx] if idx else ""
            if src in {"<", ">"} and nxt == "=":
                start = idx + len(src)
                continue
            if src in {"<", ">"} and prv in {"<", ">"}:
                start = idx + len(src)
                continue
            mutated = line[:idx] + dst + line[idx + len(src) :]
            out.append((idx, mutated))
            start = idx + len(src)
    return out


def _iter_boolean_lines(line: str) -> list[tuple[int, str]]:
    """Yield ``(column, mutated_line)`` for each boolean/logical flip."""
    out: list[tuple[int, str]] = []
    for match in _WORD_TOKEN_RE.finditer(line):
        token = match.group(0)
        for src, dst in _BOOLEAN_FLIP:
            if token == src:
                mutated = line[: match.start()] + dst + line[match.end() :]
                out.append((match.start(), mutated))
    return out


def _iter_off_by_one_lines(line: str) -> list[tuple[int, str]]:
    """Yield ``(column, mutated_line)`` for each integer-literal +1 mutation."""
    out: list[tuple[int, str]] = []
    for match in _INT_LITERAL_RE.finditer(line):
        value = int(match.group(1))
        mutated = line[: match.start()] + str(value + 1) + line[match.end() :]
        out.append((match.start(), mutated))
    return out


def _drop_statement_line(line: str) -> str | None:
    """Return *line* replaced by an indentation-preserving ``pass``, or ``None``."""
    match = _DROPPABLE_RE.match(line)
    if not match:
        return None
    indent = match.group(1)
    return f"{indent}pass"


def _replace_line(lines: list[str], index: int, new_line: str) -> str:
    """Rebuild the full source with ``lines[index]`` swapped for *new_line*."""
    rebuilt = list(lines)
    rebuilt[index] = new_line
    return "\n".join(rebuilt)


def generate_mutants(fn: FunctionUnderTest) -> tuple[Mutant, ...]:
    """Generate the deterministic mutant battery for *fn*.

    Pure. Mutants are emitted in ``(line, operator, column)`` order so the
    sequence is stable across runs and platforms.
    """
    lines = fn.source.split("\n")
    mutants: list[Mutant] = []
    counters: dict[MutationOperator, int] = dict.fromkeys(MutationOperator, 0)

    def _emit(operator: MutationOperator, index: int, mutated_line: str) -> None:
        counters[operator] += 1
        mutants.append(
            Mutant(
                mutant_id=f"{operator.value}-{index + 1}-{counters[operator]}",
                operator=operator,
                qualname=fn.qualname,
                lineno=index + 1,
                original=lines[index],
                mutated=_replace_line(lines, index, mutated_line),
            )
        )

    for index, line in enumerate(lines):
        for _column, mutated_line in _iter_comparison_lines(line):
            _emit(MutationOperator.FLIP_COMPARISON, index, mutated_line)
        for _column, mutated_line in _iter_off_by_one_lines(line):
            _emit(MutationOperator.OFF_BY_ONE, index, mutated_line)
        for _column, mutated_line in _iter_boolean_lines(line):
            _emit(MutationOperator.NEGATE_BOOLEAN, index, mutated_line)
        dropped = _drop_statement_line(line)
        if dropped is not None and dropped != line:
            _emit(MutationOperator.DROP_STATEMENT, index, dropped)

    return tuple(mutants)


def _select(mutants: tuple[Mutant, ...], limit: int | None, seed: int) -> tuple[Mutant, ...]:
    """Reproducibly pick at most *limit* mutants, ordered by ``mutant_id``."""
    if limit is None or limit >= len(mutants):
        return mutants
    if limit <= 0:
        return ()
    ordered = sorted(mutants, key=lambda m: m.mutant_id)
    # Reproducible subset selection, not a security context: a fixed seed over a
    # sorted list is exactly the determinism we want (S311 is a false positive).
    chosen = random.Random(seed).sample(ordered, limit)  # noqa: S311
    chosen_ids = {m.mutant_id for m in chosen}
    # Preserve canonical generation order among the chosen subset.
    return tuple(m for m in mutants if m.mutant_id in chosen_ids)


def run_mutation_campaign(
    fn: FunctionUnderTest,
    runner: MutantTestRunner,
    *,
    limit: int | None = None,
    seed: int = 0,
) -> MutationReport:
    """Grade *fn*'s suite by running *runner* against each generated mutant.

    Deterministic over the injected *runner*: the harness generates mutants
    purely, selects a reproducible subset when *limit* is set, and calls the
    runner once per mutant. A mutant whose runner returns :attr:`Outcome.PASSED`
    has survived (the suite is blind to that fault); :attr:`Outcome.FAILED`
    means it was killed; other outcomes are recorded as ungraded errors.
    """
    mutants = _select(generate_mutants(fn), limit, seed)
    killed: list[str] = []
    survived: list[Mutant] = []
    errored: list[str] = []

    for mutant in mutants:
        outcome = runner(mutant)
        if outcome is Outcome.FAILED:
            killed.append(mutant.mutant_id)
        elif outcome is Outcome.PASSED:
            survived.append(mutant)
        else:
            errored.append(mutant.mutant_id)

    return MutationReport(
        total=len(mutants),
        killed=tuple(killed),
        survived=tuple(survived),
        errored=tuple(errored),
    )
