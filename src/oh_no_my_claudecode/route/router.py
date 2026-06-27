"""Pure routing logic mapping a task description to a :class:`RouteDecision`.

The router is deterministic: it inspects the task text for keyword/intent
signals and returns a fixed decision. Rules are evaluated in priority order so
that higher-risk intents (security, migrations) win over cheaper ones even when
multiple signals are present. There is no LLM call and no I/O — this module is
trivially testable and reproducible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["RouteDecision", "route_task"]


@dataclass(frozen=True)
class RouteDecision:
    """A deterministic routing decision for a single task.

    Attributes
    ----------
    agent:
        The agent persona best suited to the task (e.g. ``"executor"``).
    model_tier:
        Relative model strength to allocate: ``"cheap"``, ``"balanced"`` or
        ``"strong"``.
    strategy:
        Execution strategy: ``"single"``, ``"loop"`` or ``"swarm"``.
    use_pack:
        Context pack to preload, or ``None`` when no pack helps.
    max_iterations:
        Upper bound on agent iterations the strategy should allow.
    gate:
        Quality gate to enforce before landing: ``"standard"`` or
        ``"nomistakes"``.
    rationale:
        Human-readable explanation of which rule matched and why.
    """

    agent: str
    model_tier: str
    strategy: str
    use_pack: str | None
    max_iterations: int
    gate: str
    rationale: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable mapping of this decision."""
        return asdict(self)


# Keyword signals per intent class. Matching is done on a lowercased,
# whitespace-normalised copy of the task with word-boundary awareness via simple
# substring containment of padded tokens (see :func:`_contains_any`).
_TRIVIAL_KEYWORDS = (
    "rename",
    "refactor",
    "search",
    "find",
    "grep",
    "typo",
    "trivial",
    "lint",
    "format",
)
_ARCHITECTURE_KEYWORDS = (
    "architecture",
    "architect",
    "design",
    "security",
    "secure",
    "auth",
    "threat",
    "vulnerability",
    "crypto",
)
_TESTFIX_KEYWORDS = (
    "test fix",
    "fix test",
    "fix the test",
    "failing test",
    "flaky",
    "broken test",
    "test failure",
)
_FEATURE_KEYWORDS = (
    "build",
    "feature",
    "implement",
    "end-to-end",
    "end to end",
    "scaffold",
    "rewrite",
)
_RISKY_KEYWORDS = (
    "migration",
    "migrate",
    "delete",
    "drop",
    "risky",
    "destructive",
    "production",
    "irreversible",
)


def _normalise(task: str) -> str:
    """Lowercase and collapse whitespace, padded with spaces for token matching."""
    collapsed = " ".join(task.lower().split())
    return f" {collapsed} "


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    """Return True if any needle appears in the padded, normalised haystack."""
    return any(needle in haystack for needle in needles)


def route_task(task: str) -> RouteDecision:
    """Map a free-text ``task`` to a deterministic :class:`RouteDecision`.

    Rules are checked in priority order; the first match wins:

    1. **risky / migration / delete** → ``nomistakes`` gate, strong model.
    2. **architecture / design / security** → strong model + ``nomistakes`` gate.
    3. **test fix / flaky** → ``loop`` strategy (iterate to green).
    4. **broad feature / build** → ``swarm`` strategy (fan out).
    5. **trivial / search / refactor / rename** → cheap + fast, codegraph pack,
       single iteration.
    6. **default** → balanced single-agent run.

    Parameters
    ----------
    task:
        The task description. May be empty; an empty/whitespace task routes to
        the safe default.

    Returns
    -------
    RouteDecision
        The deterministic decision for ``task``.
    """
    text = _normalise(task)

    if _contains_any(text, _RISKY_KEYWORDS):
        return RouteDecision(
            agent="careful-executor",
            model_tier="strong",
            strategy="single",
            use_pack="codegraph",
            max_iterations=2,
            gate="nomistakes",
            rationale=(
                "Matched risky/migration/delete keywords; routing to a careful "
                "single-agent run on a strong model behind the nomistakes gate "
                "to guard against irreversible damage."
            ),
        )

    if _contains_any(text, _ARCHITECTURE_KEYWORDS):
        return RouteDecision(
            agent="architect",
            model_tier="strong",
            strategy="single",
            use_pack="codegraph",
            max_iterations=3,
            gate="nomistakes",
            rationale=(
                "Matched architecture/design/security keywords; high-stakes "
                "reasoning warrants a strong model and the nomistakes gate."
            ),
        )

    if _contains_any(text, _TESTFIX_KEYWORDS):
        return RouteDecision(
            agent="test-engineer",
            model_tier="balanced",
            strategy="loop",
            use_pack="codegraph",
            max_iterations=5,
            gate="standard",
            rationale=(
                "Matched test-fix/flaky keywords; using a local loop strategy to "
                "iterate run-fix-rerun until the suite is green."
            ),
        )

    if _contains_any(text, _FEATURE_KEYWORDS):
        return RouteDecision(
            agent="executor",
            model_tier="balanced",
            strategy="swarm",
            use_pack="codegraph",
            max_iterations=4,
            gate="standard",
            rationale=(
                "Matched broad feature/build keywords; fanning out with a swarm "
                "strategy to parallelise the work."
            ),
        )

    if _contains_any(text, _TRIVIAL_KEYWORDS):
        return RouteDecision(
            agent="executor",
            model_tier="cheap",
            strategy="single",
            use_pack="codegraph",
            max_iterations=1,
            gate="standard",
            rationale=(
                "Matched trivial/search/refactor/rename keywords; a cheap, fast "
                "single pass with the codegraph pack is sufficient."
            ),
        )

    return RouteDecision(
        agent="executor",
        model_tier="balanced",
        strategy="single",
        use_pack=None,
        max_iterations=3,
        gate="standard",
        rationale=(
            "No specific intent keywords matched; falling back to a balanced "
            "single-agent run as the safe default."
        ),
    )
