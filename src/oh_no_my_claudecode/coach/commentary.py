"""Pure, deterministic commentary engine for ``onmc coach``.

No LLM, no network, no new dependencies — pure stdlib template selection.

Design
------
*  ``quip(event, tone, *, seed)`` picks a line from a (event × tone) template
   bank using ``seed`` as the selection index.  The same (event, tone, seed)
   triple always produces the same line, making tests trivially assertable.

*  ``StreakState`` tracks the current streak length, best streak, combo meter
   (consecutive green events of any kind), and recent events (capped at 20).

*  ``advance(state, event)`` returns a *new* ``StreakState`` without mutating
   the original.  Green events extend the streak; red events break it.

*  ``GREEN_EVENTS`` and ``RED_EVENTS`` are the canonical event classifiers.
   Any event not in either set is treated as neutral (streak unchanged).

Tone vocabulary
---------------
``hype``  — celebratory, enthusiastic
``roast`` — sarcastic, gently mocking
``dry``   — deadpan, matter-of-fact
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------

GREEN_EVENTS: frozenset[str] = frozenset(
    {
        "test_pass",
        "pr_merged",
        "commit",
        "build_pass",
        "lint_pass",
        "deploy_pass",
        "review_approved",
    }
)

RED_EVENTS: frozenset[str] = frozenset(
    {
        "test_fail",
        "build_break",
        "revert",
        "lint_fail",
        "deploy_fail",
        "review_rejected",
    }
)


# ---------------------------------------------------------------------------
# Template banks  (event → tone → list[str])
# ---------------------------------------------------------------------------

_TEMPLATES: dict[str, dict[str, list[str]]] = {
    # --- green events ---
    "test_pass": {
        "hype": [
            "Tests green — you're cooking. Keep the heat on.",
            "All green, baby. The test suite nods in approval.",
            "Tests passed. The CI gods smile upon you.",
            "Green across the board. Momentum is a drug.",
            "Tests pass like they were born to. Poetry.",
        ],
        "roast": [
            "Tests passed. Probably just luck, but we'll take it.",
            "Green. Beginner's luck is still luck, I suppose.",
            "Tests passed. Surprised? Same.",
            "The tests passed. Even a broken clock, etc.",
            "They passed. Don't look so smug.",
        ],
        "dry": [
            "Tests: pass.",
            "All tests passed.",
            "Test suite: green.",
            "Tests executed successfully.",
            "Test run complete. Status: pass.",
        ],
    },
    "pr_merged": {
        "hype": [
            "PR merged! Ship it, ship it, SHIP IT.",
            "Merged. Another brick in the wall of progress.",
            "PR is in. You're basically a shipping machine now.",
            "Merged clean. The diff gods are pleased.",
            "PR merged. The main branch just got better.",
        ],
        "roast": [
            "PR merged. Someone reviewed it, apparently.",
            "Merged. The bar was low, but you cleared it.",
            "PR in. Reviewers probably just got tired of waiting.",
            "Merged. No rollback yet. Fingers crossed.",
            "PR landed. Check prod in 10 minutes.",
        ],
        "dry": [
            "PR merged.",
            "Pull request merged to main.",
            "Merge complete.",
            "PR status: merged.",
            "Merge recorded.",
        ],
    },
    "commit": {
        "hype": [
            "Commit landed. The history grows richer.",
            "Another commit, another step closer to greatness.",
            "Committed. Forward momentum is the only momentum.",
            "Git log gets better every time.",
            "Commit done. You're writing history. Literally.",
        ],
        "roast": [
            "Committed. At least someone around here makes decisions.",
            "A commit! Your git log is longer than your attention span.",
            "Committed. 'wip' is a valid message, I've decided.",
            "Commit in. Now write a useful commit message next time.",
            "Committed. The blame graph grows.",
        ],
        "dry": [
            "Commit recorded.",
            "New commit added.",
            "Commit: done.",
            "Git commit complete.",
            "Commit logged.",
        ],
    },
    "build_pass": {
        "hype": [
            "Build passes — you're not just writing code, you're crafting software.",
            "Clean build. The compiler is impressed (if compilers could be).",
            "Build green. Every type checks out. Glorious.",
            "Build passed. You have achieved correctness.",
            "Clean build. Put that in a frame.",
        ],
        "roast": [
            "Build passes. Eventually.",
            "Build green. It only took three tries.",
            "The build passed. Basic competence, confirmed.",
            "Clean build. Took you long enough.",
            "Build passes. I'll note the timestamp for posterity.",
        ],
        "dry": [
            "Build: pass.",
            "Build succeeded.",
            "Build clean.",
            "Build status: green.",
            "Build complete, no errors.",
        ],
    },
    "lint_pass": {
        "hype": [
            "Lint clean! Your code is as tidy as your commit history. Wait—",
            "Zero lint errors. A thing of beauty.",
            "Linter satisfied. Style is a form of respect.",
            "Lint: all clear. Elegance achieved.",
            "Clean lint run. Ruff is at peace.",
        ],
        "roast": [
            "Lint passes. Someone finally read the style guide.",
            "Zero lint errors? How unlike you.",
            "Lint clean. Only because the config ignores the hard stuff.",
            "Linter happy. Barely.",
            "Lint passes. Auto-fix is a wonderful thing.",
        ],
        "dry": [
            "Lint: pass.",
            "No lint violations found.",
            "Lint check complete.",
            "Lint: clean.",
            "Lint run: success.",
        ],
    },
    "deploy_pass": {
        "hype": [
            "Deployed! You just made the world slightly better.",
            "Deploy successful. Users rejoice (they just don't know it yet).",
            "It's live! The internet is now hosting your good decisions.",
            "Deploy done. Go watch the metrics spike.",
            "Deployed clean. You may now panic about production.",
        ],
        "roast": [
            "Deployed. Prod is now your problem.",
            "Deploy succeeded. Check the error dashboards.",
            "It's live. Good luck.",
            "Deployed. The on-call schedule awaits.",
            "Deploy passed. Set a rollback plan.",
        ],
        "dry": [
            "Deployment: success.",
            "Deploy complete.",
            "Service deployed.",
            "Deploy status: pass.",
            "Deployment recorded.",
        ],
    },
    "review_approved": {
        "hype": [
            "Review approved! Someone read your code and liked what they saw.",
            "Approved! Your PR passed the human test.",
            "Review: thumbs up. Merge with confidence.",
            "Approved. Your peers have spoken and they're impressed.",
            "Review approved. Now merge before they change their mind.",
        ],
        "roast": [
            "Review approved. They probably just wanted to clear their queue.",
            "Approved. The reviewer was clearly in a good mood.",
            "Review passed. One LGTM and off to the races.",
            "Approved with comments. Read them.",
            "Review done. Your PR survived the nit parade.",
        ],
        "dry": [
            "Review: approved.",
            "Code review approved.",
            "PR approved by reviewer.",
            "Review status: approved.",
            "Approval recorded.",
        ],
    },
    # --- red events ---
    "test_fail": {
        "hype": [
            "Tests failed — but every failure is data. Debug mode: on.",
            "Red build. The bounce-back starts now.",
            "Tests failed. Channel that frustration into a fix.",
            "Failing tests are just future passing tests in disguise.",
            "Red. Don't panic. Just read the stack trace.",
        ],
        "roast": [
            "Tests failed. The tests are trying to tell you something.",
            "Red again? The tests are more consistent than you are.",
            "Failing. The code disagreed with your assumptions. Shocking.",
            "Tests red. Have you tried writing them first?",
            "Tests fail. The test suite knows more than it lets on.",
        ],
        "dry": [
            "Tests: fail.",
            "Test failures detected.",
            "Test run: red.",
            "Tests failed.",
            "Test suite: failing.",
        ],
    },
    "build_break": {
        "hype": [
            "Build broke — happens to the best. Fix it and come back stronger.",
            "Build red. You've got this. One error at a time.",
            "Broken build. The compiler is just helping you write better code.",
            "Build break. An opportunity wearing a disguise.",
            "Red build. Read the error. Fix the error. Ship the fix.",
        ],
        "roast": [
            "Build broke. Again.",
            "The build is broken. The other engineers noticed.",
            "Build break. The CI log would like a word.",
            "Broken. At least it failed fast.",
            "Build red. The type checker was right all along.",
        ],
        "dry": [
            "Build: failed.",
            "Build error detected.",
            "Build status: broken.",
            "Build failed.",
            "Build: error.",
        ],
    },
    "revert": {
        "hype": [
            "Revert committed! Sometimes going back is the bravest move.",
            "Reverted. Knowing when to revert is a skill.",
            "Revert done. A clean main is worth a broken ego.",
            "You chose stability over sunk cost. Respect.",
            "Revert in. Now go figure out why.",
        ],
        "roast": [
            "Revert. At least you noticed before users did. Probably.",
            "Back to a known good state. Wisdom, or defeat?",
            "Reverted. The commit message 'revert: revert: revert' is coming.",
            "Revert committed. The git log tells the story.",
            "Reverted. The blame history grows in interesting ways.",
        ],
        "dry": [
            "Revert committed.",
            "Revert applied.",
            "Code reverted.",
            "Revert: done.",
            "Revert recorded.",
        ],
    },
    "lint_fail": {
        "hype": [
            "Lint errors found — quick fix, then back to shipping.",
            "Style check failed. Ten seconds with --fix and you're done.",
            "Lint red. Easily solved. Don't sweat it.",
            "Lint violations: finite and fixable.",
            "Lint fail. Run ruff --fix. Done.",
        ],
        "roast": [
            "Lint failed. The style guide is not optional.",
            "Lint errors. The auto-formatter exists for a reason.",
            "Lint fail. Did you even run it locally?",
            "Style violations. Ruff is judging you.",
            "Lint red. Your whitespace disagrees with the config.",
        ],
        "dry": [
            "Lint: fail.",
            "Lint violations found.",
            "Lint check: failed.",
            "Lint: errors.",
            "Lint run: failed.",
        ],
    },
    "deploy_fail": {
        "hype": [
            "Deploy failed — catch it in staging so prod stays clean.",
            "Deploy error. Roll back if needed; fix if not.",
            "Failed deploy is better than a silent bad deploy.",
            "Deploy fail. Check the logs. You'll find it.",
            "Deploy red. The pipeline saved you from a prod incident.",
        ],
        "roast": [
            "Deploy failed. Maybe test it next time?",
            "Deploy error. The environment had opinions.",
            "Failed deploy. The staging server was trying to warn you.",
            "Deploy: no. Fix: yes. Deploy again: maybe.",
            "Deploy failed. The infra team is not surprised.",
        ],
        "dry": [
            "Deployment: failed.",
            "Deploy error.",
            "Deploy status: failed.",
            "Deployment failed.",
            "Deploy: error.",
        ],
    },
    "review_rejected": {
        "hype": [
            "Changes requested — good reviewers make great code.",
            "Review feedback is just free senior-engineer advice.",
            "Requested changes. Address them and it'll be better.",
            "Reviewer pushed back — that's the process working.",
            "Changes requested. Iterate and resubmit.",
        ],
        "roast": [
            "Review rejected. They found the thing you were hoping they'd miss.",
            "Changes requested. All of them.",
            "Request for changes. The comments were… thorough.",
            "Reviewer said no. The PR needed more thought.",
            "Changes requested. Consider this a learning opportunity.",
        ],
        "dry": [
            "Review: changes requested.",
            "PR returned for revision.",
            "Review: rejected.",
            "Changes requested by reviewer.",
            "Review outcome: revise.",
        ],
    },
}

# Fallback templates for unknown events
_FALLBACK: dict[str, list[str]] = {
    "hype": [
        "Something happened — and you handled it.",
        "Event logged. Onward.",
        "Unknown event, but you showed up. That counts.",
        "Activity detected. You're doing things.",
        "Something moved. That's progress.",
    ],
    "roast": [
        "An event occurred. Unclear if you should be proud.",
        "Something happened. Hard to say what.",
        "Logged. Whatever it was.",
        "An event, apparently.",
        "Unclear event. Unclear response. Carry on.",
    ],
    "dry": [
        "Event recorded.",
        "Event logged.",
        "Unknown event.",
        "Event: unknown.",
        "Event processed.",
    ],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def quip(event: str, tone: str, *, seed: int) -> str:
    """Return a deterministic quip for the given (event, tone, seed).

    The same triple always produces the same string — ``seed`` drives the
    selection index, wrapping around the template list.  No ``random`` module
    is used; no wallclock is read.

    Parameters
    ----------
    event:
        One of the recognised event kinds (e.g. ``"test_pass"``).  Unknown
        events fall back to a generic template bank.
    tone:
        One of ``"hype"``, ``"roast"``, or ``"dry"``.  Unknown tones fall
        back to ``"dry"``.
    seed:
        Any integer (typically the current total event count).  Controls
        which line is selected from the bank.
    """
    bank = _TEMPLATES.get(event, {})
    lines = bank.get(tone) or bank.get("dry") or _FALLBACK.get(tone) or _FALLBACK["dry"]
    return lines[seed % len(lines)]


# ---------------------------------------------------------------------------
# Streak state
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StreakState:
    """Immutable snapshot of the live coding streak.

    Attributes
    ----------
    current_streak:
        Consecutive green events since the last red event (or session start).
    best_streak:
        Highest ``current_streak`` ever recorded in this session.
    combo:
        Cumulative count of green events (never reset by a red event).
    total_events:
        Total events processed (green + red + neutral).
    recent_events:
        Ordered list of the last ≤20 event kinds seen (oldest first).
    """

    current_streak: int = 0
    best_streak: int = 0
    combo: int = 0
    total_events: int = 0
    recent_events: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Clamp recent_events to last 20 entries.
        if len(self.recent_events) > 20:
            object.__setattr__(self, "recent_events", self.recent_events[-20:])

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dict of this state."""
        return {
            "current_streak": self.current_streak,
            "best_streak": self.best_streak,
            "combo": self.combo,
            "total_events": self.total_events,
            "recent_events": list(self.recent_events),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "StreakState":
        """Reconstruct a ``StreakState`` from a JSON-loaded dict."""

        def _int(key: str) -> int:
            v = data.get(key, 0)
            return int(v) if isinstance(v, (int, float, str)) else 0

        raw_events = data.get("recent_events", [])
        events: tuple[str, ...] = (
            tuple(str(e) for e in raw_events)
            if isinstance(raw_events, (list, tuple))
            else ()
        )
        return cls(
            current_streak=_int("current_streak"),
            best_streak=_int("best_streak"),
            combo=_int("combo"),
            total_events=_int("total_events"),
            recent_events=events,
        )


def advance(state: StreakState, event: str) -> StreakState:
    """Return a new :class:`StreakState` after recording *event*.

    Green events extend ``current_streak`` and ``combo``; red events reset
    ``current_streak`` to 0 (``combo`` is never reset, ``best_streak`` may
    update).  Neutral events only increment ``total_events``.
    """
    new_events = (*state.recent_events, event)[-20:]
    total = state.total_events + 1

    if event in GREEN_EVENTS:
        new_streak = state.current_streak + 1
        new_best = max(state.best_streak, new_streak)
        new_combo = state.combo + 1
    elif event in RED_EVENTS:
        new_streak = 0
        new_best = state.best_streak
        new_combo = state.combo
    else:
        # Neutral event — no streak change.
        return StreakState(
            current_streak=state.current_streak,
            best_streak=state.best_streak,
            combo=state.combo,
            total_events=total,
            recent_events=new_events,
        )

    return StreakState(
        current_streak=new_streak,
        best_streak=new_best,
        combo=new_combo,
        total_events=total,
        recent_events=new_events,
    )
