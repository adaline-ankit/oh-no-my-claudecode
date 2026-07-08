"""Pure analysis core for ``onmc explain``.

:func:`explain_receipt` is a pure function — it takes a receipt dict (as loaded
from a ``.agent-memory/receipts/run-*.json`` file) and returns a structured
:class:`ExplainResult`.  No I/O, no Rich, no sys.exit.

``stop_reason`` values (from the engine docstring)::

    converged | max-iterations | budget | no-progress | cost | wall-time |
    duplicate-action | repeated-error | no-changes | aborted | agent-error

The special case ``no-changes`` receives an extended explanation because it is
the most confusing: the verify command exits 0 but the agent changed nothing,
which is a "vacuous pass" — nothing was actually accomplished.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Human-readable explanations per stop_reason
# ---------------------------------------------------------------------------

#: One-line plain-English explanation for every known stop_reason.
#: Keys are exact stop_reason strings; the fallback is used for unknown values.
_STOP_REASON_BLURB: dict[str, str] = {
    "converged": "The agent converged: the verify command passed after making changes.",
    "no-changes": (
        "The verify command passed, but the agent made NO changes to the working tree"
        " — a vacuous pass (often blocked/permission-pending edits). Nothing was"
        " actually done, so the run is not verified."
    ),
    "max-iterations": (
        "The run hit the maximum iteration limit before the verify command passed."
        " The agent ran out of attempts."
    ),
    "budget": (
        "The run was stopped because it exhausted the token budget before converging."
    ),
    "cost": (
        "The run was stopped because it hit the maximum cost (USD) limit before converging."
    ),
    "wall-time": (
        "The run was stopped because it exceeded the maximum allowed wall-clock time."
    ),
    "duplicate-action": (
        "The agent repeated the same action twice in a row — a sign it was stuck in"
        " a loop. The run was stopped to prevent wasted effort."
    ),
    "repeated-error": (
        "The verify command produced the same error output repeatedly — the agent"
        " was unable to make progress. The run was stopped."
    ),
    "aborted": (
        "The run was manually aborted (e.g. Ctrl-C or an external signal) before it"
        " could converge."
    ),
    "agent-error": (
        "The agent adapter encountered an unrecoverable error (e.g. an API failure"
        " or authentication problem). No further iterations were attempted."
    ),
    "no-progress": (
        "The agent made no measurable progress for several consecutive iterations"
        " (no-progress window exceeded). The run was stopped early."
    ),
}

_UNKNOWN_BLURB = (
    "The run stopped for an unrecognised reason. Check the receipt for details."
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExplainResult:
    """Structured verdict produced by :func:`explain_receipt`.

    Fields
    ------
    verified:
        Whether the run is considered verified (converged AND verify passed AND
        at least one iteration made changes).
    stop_reason:
        The raw stop_reason string from the receipt (empty string when absent).
    verdict:
        Short headline: ``"VERIFIED"`` or ``"NOT VERIFIED"``.
    explanation:
        Plain-English explanation of why the run did or did not verify.
    goal:
        The run's goal (truncated to 200 chars; empty string when absent).
    iterations:
        Number of completed iterations.
    cost_usd:
        Total USD cost, or ``None`` when not reported.
    tokens:
        Total tokens consumed.
    agent:
        Agent selector string (e.g. ``"claude"``).
    ended_at:
        ISO-8601 UTC timestamp when the run ended; empty string when absent.
    receipt_hash:
        Full receipt hash (64-char hex); empty string when absent.
    receipt_hash_short:
        First 8 characters of ``receipt_hash`` for display; empty string when absent.
    """

    verified: bool
    stop_reason: str
    verdict: str
    explanation: str
    goal: str
    iterations: int
    cost_usd: float | None
    tokens: int
    agent: str
    ended_at: str
    receipt_hash: str
    receipt_hash_short: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict for ``--json`` output."""
        return {
            "kind": "explain",
            "verified": self.verified,
            "stop_reason": self.stop_reason,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "goal": self.goal,
            "iterations": self.iterations,
            "cost_usd": self.cost_usd,
            "tokens": self.tokens,
            "agent": self.agent,
            "ended_at": self.ended_at,
            "receipt": self.receipt_hash,
        }


# ---------------------------------------------------------------------------
# Pure analysis function
# ---------------------------------------------------------------------------


def explain_receipt(receipt: dict[str, object]) -> ExplainResult:
    """Analyse a receipt dict and return a structured verdict.

    This function is **pure**: it performs no I/O, no Rich calls, no sys.exit.
    All fields default sensibly when absent so it never raises on a partial receipt.

    Parameters
    ----------
    receipt:
        A dict loaded from a ``run-*.json`` receipt file.  Extra keys are ignored;
        missing keys are treated as absent with safe defaults.

    Returns
    -------
    ExplainResult
        Human-readable verdict plus structured accounting fields.
    """
    # --- Defensive field extraction (never crash on missing/wrong-type keys) ---

    def _str(key: str, default: str = "") -> str:
        v = receipt.get(key, default)
        return str(v) if v is not None else default

    def _int(key: str, default: int = 0) -> int:
        v = receipt.get(key, default)
        if isinstance(v, int):
            return v
        try:
            return int(str(v))
        except (TypeError, ValueError):
            return default

    def _float_or_none(key: str) -> float | None:
        v = receipt.get(key)
        if v is None:
            return None
        if isinstance(v, float):
            return v
        try:
            return float(str(v))
        except (TypeError, ValueError):
            return None

    def _bool(key: str, default: bool = False) -> bool:
        v = receipt.get(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return bool(v)
        if isinstance(v, str):
            return v.lower() in {"true", "1", "yes"}
        return default

    raw_verified = _bool("verified")
    stop_reason = _str("stop_reason")
    goal_raw = _str("goal")
    goal = goal_raw[:200] if goal_raw else ""
    iterations = _int("iterations")
    tokens = _int("tokens_used")
    cost_usd = _float_or_none("cost_usd")
    agent = _str("agent", "unknown")
    ended_at = _str("ended_at")
    receipt_hash = _str("receipt_hash")
    receipt_hash_short = receipt_hash[:8] if receipt_hash else ""

    # --- Determine actual verified status ---
    # ``no-changes`` is special: the receipt may claim verified=True (verifier
    # exited 0) but the agent made no changes — a vacuous pass.
    is_no_changes = stop_reason == "no-changes"
    verified = raw_verified and not is_no_changes

    # --- Build verdict and explanation ---
    if verified:
        verdict = "VERIFIED"
        explanation = (
            f"Converged in {iterations} iteration(s)."
            f" Cost: {_format_cost(cost_usd)},"
            f" {tokens:,} tokens."
        )
    else:
        verdict = "NOT VERIFIED"
        explanation = _STOP_REASON_BLURB.get(stop_reason, _UNKNOWN_BLURB)

    return ExplainResult(
        verified=verified,
        stop_reason=stop_reason,
        verdict=verdict,
        explanation=explanation,
        goal=goal,
        iterations=iterations,
        cost_usd=cost_usd,
        tokens=tokens,
        agent=agent,
        ended_at=ended_at,
        receipt_hash=receipt_hash,
        receipt_hash_short=receipt_hash_short,
    )


# ---------------------------------------------------------------------------
# Formatting helpers (pure)
# ---------------------------------------------------------------------------


def _format_cost(cost_usd: float | None) -> str:
    """Format a cost value for display: ``"$0.0042"`` or ``"n/a"``."""
    if cost_usd is None:
        return "n/a"
    return f"${cost_usd:.4f}"
