"""Pre-recorded fixture results for the A/B eval harness.

These fixtures represent a realistic run of the built-in task suite.
They are NOT auto-generated failures — they were designed to reflect
plausible agent behaviour on these tasks:

- cc_alone: the cold agent sees only the task description.  On tasks
  with a plausible "wrong fix" dead-end it may apply the wrong patch.
- cc_onmc: the ONMC-grounded agent receives the dead-end hint and steers
  to the correct fix.

IMPORTANT: These results are PRE-RECORDED for CI reproducibility.  They
do NOT prove that ONMC always wins on these tasks in a live run.  Live
results vary by model, temperature, and prompt phrasing.  To collect live
results, run without --fixture.

How fixture results were designed
-----------------------------------
The fixture results model a scenario where an average coding agent (without
memory context) occasionally tries the wrong approach first.  The ONMC
condition is modelled as consistently applying the correct fix because the
dead-end hint rules out the wrong approaches.

In practice:
- list_slice_fix: a real Claude Sonnet run on this task sometimes produces
  n-1 on first attempt (plausible off-by-one intuition), sometimes n.
  Fixture: alone=fail, onmc=pass (ONMC hint eliminates n-1 dead-end).

- accumulator_init: agents reliably spot `total = 1` as wrong and fix it.
  Fixture: both pass (task too easy to differentiate on this model).

- word_reverse: the [:-1] replacement is a common first guess.  Agents
  without the hint sometimes produce it.
  Fixture: alone=fail, onmc=pass.
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.ab.models import ABTaskResult

# ---------------------------------------------------------------------------
# Fixture data — (task_id, condition) -> ABTaskResult
# ---------------------------------------------------------------------------

_RAW: list[dict[str, object]] = [
    # list_slice_fix — cc_alone tries n-1 (plausible dead-end), gate fails
    {
        "task_id": "list_slice_fix",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 512,
        "duration_s": 8.3,
        "agent_output": (
            "I see the bug: `[:n + 1]` returns one too many elements.  "
            "The fix should be `[:n - 1]` to get the correct count."
        ),
        "error": None,
        "fixture": True,
    },
    # list_slice_fix — cc_onmc uses hint, avoids n-1, applies n
    {
        "task_id": "list_slice_fix",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 498,
        "duration_s": 7.9,
        "agent_output": (
            "The ONMC context confirms n-1 is a dead-end.  The correct fix "
            "is simply removing the +1: `[:n]`."
        ),
        "error": None,
        "fixture": True,
    },
    # accumulator_init — both agents spot `total = 1` easily
    {
        "task_id": "accumulator_init",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 445,
        "duration_s": 6.1,
        "agent_output": (
            "The bug is `total = 1`.  Changing it to `total = 0` fixes all three tests."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "accumulator_init",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 461,
        "duration_s": 6.4,
        "agent_output": ("Initialising total = 0 as the ONMC context suggests.  All tests pass."),
        "error": None,
        "fixture": True,
    },
    # word_reverse — cc_alone tries [:-1] replacement (named dead-end in hint)
    {
        "task_id": "word_reverse",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 530,
        "duration_s": 9.2,
        "agent_output": (
            "The [1:] drops the first element after reversal.  "
            "Replacing it with [:-1] should drop the last instead."
        ),
        "error": None,
        "fixture": True,
    },
    # word_reverse — cc_onmc uses hint to remove [1:] entirely
    {
        "task_id": "word_reverse",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 510,
        "duration_s": 8.7,
        "agent_output": (
            "ONMC hints confirm [:-1] is also wrong.  Removing [1:] entirely: `s.split()[::-1]`."
        ),
        "error": None,
        "fixture": True,
    },
]


def load_fixture_results() -> dict[tuple[str, str], ABTaskResult]:
    """Load pre-recorded fixture results keyed by (task_id, condition)."""
    results: dict[tuple[str, str], ABTaskResult] = {}
    for raw in _RAW:
        result = ABTaskResult.from_dict(raw)
        results[(result.task_id, result.condition)] = result
    return results
