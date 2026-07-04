"""Autoroute — apply the flywheel's verified-outcome learning to model selection.

The self-improvement loop, closed
---------------------------------
``onmc flywheel`` *learns* which model has historically produced verified
results, broken down per goal keyword and overall (see
:mod:`oh_no_my_claudecode.flywheel.analyze`).  ``onmc autoroute`` *applies* that
learning: given a fresh goal string, it recommends the model a swarm / loop
should reach for — so the system can auto-select the historically-best model
instead of a fixed default.

This module is **pure, deterministic, and offline** (stdlib only, plus a read of
the already-computed :class:`~oh_no_my_claudecode.flywheel.analyze.FlywheelReport`).
It never trains, never calls an LLM, and never fabricates a recommendation:

- A goal keyword must have at least ``min_samples`` verified-labeled runs before
  its winning model is trusted; confidence is that keyword's verified rate.
- Otherwise, if the overall corpus has enough samples, the overall best model is
  offered at a deliberately *moderate* (rate-derived, capped) confidence.
- Otherwise the caller's ``default_model`` is returned with confidence ``0.0``
  and an explicit "insufficient data" basis — stated, never smoothed over.

The only reused analysis is the flywheel's own aggregation; this module imports
it and never modifies it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oh_no_my_claudecode.flywheel.analyze import (
    MIN_SAMPLES,
    FlywheelReport,
    KeywordStat,
    load_trajectories,
    summarize,
)

#: Ceiling on confidence for an "overall best" (non-keyword) recommendation.
#: A goal that does not match any learned keyword is a weaker signal than one
#: that does, so even a high overall verified rate is capped here to keep the
#: keyword path strictly more confident when both would otherwise tie.
_OVERALL_CONFIDENCE_CAP = 0.6

#: Stopwords stripped when tokenizing a goal for keyword matching.  Kept in
#: sync with the flywheel's own goal-keyword derivation so a goal tokenizes to
#: the same meaningful terms the report was keyed on.
_GOAL_STOPWORDS = frozenset(
    {
        "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
        "add", "fix", "make", "do", "run", "this", "that", "it", "is", "be",
        "into", "from", "by", "at", "as", "so", "we", "i",
    }
)


@dataclass(frozen=True)
class Suggestion:
    """A deterministic model recommendation for a goal.

    Fields
    ------
    goal:
        The goal string the suggestion was computed for (as given).
    model:
        The recommended model name, or ``None`` only if a caller passes an
        explicitly empty default (normally the default_model string).
    rationale:
        Human-readable one-line explanation of *why* this model.
    confidence:
        Honest confidence in ``[0.0, 1.0]``.  ``0.0`` means "no evidence —
        this is just the default".
    basis:
        Short machine-friendly tag for the decision path, e.g.
        ``"goal-keyword 'parser' (3/3 verified)"``, ``"overall best"``, or
        ``"insufficient data"``.
    """

    goal: str
    model: str | None
    rationale: str
    confidence: float
    basis: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of the suggestion."""
        return {
            "goal": self.goal,
            "model": self.model,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "basis": self.basis,
        }


def _tokenize_goal(goal: str) -> list[str]:
    """Tokenize a goal into meaningful lowercase keywords.

    Simple, ReDoS-free tokenizer: split on non-word characters via a
    linear-time character-class scan (no backtracking), lowercase, then drop
    short tokens and stopwords.  Order-preserving and de-duplicated so keyword
    matching is deterministic.
    """
    out: list[str] = []
    for word in re.findall(r"[a-z0-9]+", goal.lower()):
        if len(word) < 3 or word in _GOAL_STOPWORDS:
            continue
        if word not in out:
            out.append(word)
    return out


def _match_keyword(
    report: FlywheelReport, goal_tokens: list[str], min_samples: int
) -> KeywordStat | None:
    """Return the strongest learned keyword stat matching the goal, or ``None``.

    A keyword qualifies only when it appears in the goal, has ``>= min_samples``
    runs, and has a verified winning model.  Among qualifiers the strongest is
    the one whose winning model verified most often (tie-break: higher verified
    rate, then more runs, then keyword name) — deterministic regardless of the
    report's own ordering.
    """
    goal_set = set(goal_tokens)
    candidates = [
        kw
        for kw in report.by_goal_keyword
        if kw.keyword in goal_set
        and kw.runs >= min_samples
        and kw.best_model is not None
        and kw.best_model_verified > 0
    ]
    if not candidates:
        return None

    def _key(kw: KeywordStat) -> tuple[int, float, int, str]:
        rate = kw.best_model_verified / kw.best_model_runs if kw.best_model_runs else 0.0
        # Negative keyword so ascending sort keeps name as a stable final tie-break.
        return (kw.best_model_verified, rate, kw.best_model_runs, kw.keyword)

    return max(candidates, key=_key)


def suggest_model(
    report: FlywheelReport,
    goal: str,
    *,
    default_model: str = "sonnet",
    min_samples: int = MIN_SAMPLES,
) -> Suggestion:
    """Recommend a model for *goal* from a learned :class:`FlywheelReport`.

    Deterministic and side-effect free.  Decision order:

    1. **Goal-keyword match** — if a keyword in the goal has ``>= min_samples``
       verified-labeled runs and a verified winning model, recommend that
       model; confidence is that keyword's winning-model verified rate.
    2. **Overall best** — else if a model in the overall corpus has
       ``>= min_samples`` runs (``report.best`` is set), recommend it at a
       *moderate* confidence (its verified rate, capped at
       :data:`_OVERALL_CONFIDENCE_CAP`).
    3. **Default** — else return ``default_model`` with confidence ``0.0`` and
       an "insufficient data" basis.

    Never fabricates: confidences are real verified rates, never invented.
    """
    goal_tokens = _tokenize_goal(goal)

    # 1. Goal-keyword match — the strongest, most specific signal.
    kw = _match_keyword(report, goal_tokens, min_samples)
    if kw is not None and kw.best_model is not None:
        rate = (
            kw.best_model_verified / kw.best_model_runs if kw.best_model_runs else 0.0
        )
        confidence = round(min(max(rate, 0.0), 1.0), 4)
        basis = (
            f"goal-keyword '{kw.keyword}' "
            f"({kw.best_model_verified}/{kw.best_model_runs} verified)"
        )
        rationale = (
            f"goals like '{kw.keyword}' were most reliably solved by "
            f"{kw.best_model} — verified {kw.best_model_verified}/"
            f"{kw.best_model_runs} ({rate:.0%})"
        )
        return Suggestion(
            goal=goal,
            model=kw.best_model,
            rationale=rationale,
            confidence=confidence,
            basis=basis,
        )

    # 2. Overall best model with enough samples.
    if report.best is not None and report.best.runs >= min_samples:
        b = report.best
        confidence = round(min(max(b.verified_rate, 0.0), _OVERALL_CONFIDENCE_CAP), 4)
        basis = f"overall best ({b.verified}/{b.runs} verified)"
        rationale = (
            f"no learned keyword matched this goal; overall {b.model} has the "
            f"best verified track record — {b.verified}/{b.runs} "
            f"({b.verified_rate:.0%})"
        )
        return Suggestion(
            goal=goal,
            model=b.model,
            rationale=rationale,
            confidence=confidence,
            basis=basis,
        )

    # 3. Insufficient data — honest default.
    return Suggestion(
        goal=goal,
        model=default_model,
        rationale=(
            f"insufficient verified history ({report.total} runs, "
            f"need >= {min_samples}) — falling back to default {default_model}"
        ),
        confidence=0.0,
        basis="insufficient data",
    )


def suggest_from_repo(
    repo_root: Path,
    goal: str,
    *,
    default_model: str = "sonnet",
    min_samples: int = MIN_SAMPLES,
) -> Suggestion:
    """Load trajectories under *repo_root*, summarize, then :func:`suggest_model`.

    Thin impure convenience wrapper for the CLI: reuses the flywheel's own
    :func:`~oh_no_my_claudecode.flywheel.analyze.load_trajectories` and
    :func:`~oh_no_my_claudecode.flywheel.analyze.summarize` so there is a single
    source of truth for receipt I/O and aggregation.  With no receipts the
    resulting report has ``total == 0`` and this returns the insufficient-data
    default — never raises.
    """
    trajectories = load_trajectories(repo_root)
    report = summarize(trajectories)
    return suggest_model(
        report, goal, default_model=default_model, min_samples=min_samples
    )
