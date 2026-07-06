"""Auto-model routing for swarm planning — closes the flywheel self-improvement loop.

``onmc flywheel`` *learns* which model has historically produced verified
results per goal (see :mod:`oh_no_my_claudecode.flywheel.analyze`).  ``onmc
autoroute`` *applies* that learning to a single goal string (see
:mod:`oh_no_my_claudecode.autoroute.autoroute`).  This module is the last hop:
it applies autoroute's suggestion to every unit in a swarm plan, so ``onmc
swarm plan --auto-model`` can record a per-unit ``suggested_model`` alongside
the goal — purely advisory, never forcing execution to use a different model.

Pure and deterministic
-----------------------
:func:`annotate_units_with_models` takes an already-computed
:class:`~oh_no_my_claudecode.flywheel.analyze.FlywheelReport` and a list of
unit dicts, and returns a *new* list of unit dicts with two additional keys:
``suggested_model`` and ``suggested_model_confidence``.  It never mutates its
input, never touches disk, and never calls a model — the report is built once
by the caller (CLI) and threaded through.
"""

from __future__ import annotations

from typing import Any

from oh_no_my_claudecode.autoroute.autoroute import Suggestion, suggest_model
from oh_no_my_claudecode.flywheel.analyze import MIN_SAMPLES, FlywheelReport


def annotate_units_with_models(
    units: list[dict[str, Any]],
    report: FlywheelReport,
    *,
    default_model: str = "sonnet",
    min_samples: int = MIN_SAMPLES,
) -> list[dict[str, Any]]:
    """Return *units* copies annotated with a flywheel-learned model suggestion.

    Each input unit must have a ``"goal"`` key (matches
    :class:`~oh_no_my_claudecode.swarm.models.SwarmUnit` / the inline-swarm unit
    dict shape).  Every other key is passed through unchanged.  Two new keys
    are added:

    - ``suggested_model``: the recommended model name (never ``None`` — falls
      back to *default_model* when the flywheel has insufficient data).
    - ``suggested_model_confidence``: honest confidence in ``[0.0, 1.0]``;
      ``0.0`` when the suggestion is just the default (no evidence).

    Never raises: a unit with a missing/empty goal gets the insufficient-data
    default at confidence ``0.0``, same as :func:`suggest_model` would return
    for an empty-token goal.
    """
    annotated: list[dict[str, Any]] = []
    for unit in units:
        goal = str(unit.get("goal") or "")
        suggestion: Suggestion = suggest_model(
            report, goal, default_model=default_model, min_samples=min_samples
        )
        new_unit = dict(unit)
        new_unit["suggested_model"] = suggestion.model
        new_unit["suggested_model_confidence"] = suggestion.confidence
        annotated.append(new_unit)
    return annotated


def build_routing_summary_lines(units: list[dict[str, Any]]) -> list[str]:
    """Render one short human-readable line per annotated unit.

    Format: ``"unit <id>: <goal> -> suggested <model> (conf <confidence>)"``.
    Units missing ``suggested_model`` are skipped (defensive — should not
    happen for units produced by :func:`annotate_units_with_models`).
    """
    lines: list[str] = []
    for unit in units:
        model = unit.get("suggested_model")
        if model is None:
            continue
        confidence = unit.get("suggested_model_confidence", 0.0)
        goal = str(unit.get("goal") or "")
        unit_id = str(unit.get("id") or "?")
        lines.append(f"unit {unit_id}: {goal[:60]} -> suggested {model} (conf {confidence:.2f})")
    return lines
