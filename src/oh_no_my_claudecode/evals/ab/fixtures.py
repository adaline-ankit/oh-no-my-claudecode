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

Extended tasks (7 added, 4 ONMC-wins + 3 ties):
- dedup_preserve_order: tie — dict.fromkeys is discoverable without memory.
- null_coalesce_zero: ONMC-win — `x or default` dead-end is seductive; hint
  steers to explicit `is None` check.
- money_round_half_even: ONMC-win — epsilon-offset dead-end is common;
  hint steers to Decimal.quantize.
- pagination_offset: ONMC-win — (page+1)*size overcorrection dead-end named.
- retry_no_presleep: tie — both agents count the range correctly in practice.
- cache_key_kwargs_sorted: ONMC-win — repr() dead-end named; hint gives sorted.
- utc_aware_parse: tie — append-Z dead-end is named but both agents find the
  replace(tzinfo=utc) fix independently.

Honesty note: tie-pass tasks carry no signal about ONMC value (any competent
agent solves them). They confirm ONMC does not regress. The diagnostic signal
comes from the 4 ONMC-win tasks where cc_alone applies the named wrong fix.
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
    # -----------------------------------------------------------------------
    # dedup_preserve_order — TIE: both agents discover dict.fromkeys
    # -----------------------------------------------------------------------
    {
        "task_id": "dedup_preserve_order",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 478,
        "duration_s": 6.9,
        "agent_output": (
            "The bug is using set() which loses insertion order.  "
            "Using dict.fromkeys(items) preserves first-seen order: "
            "`return list(dict.fromkeys(items))`."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "dedup_preserve_order",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 461,
        "duration_s": 6.5,
        "agent_output": (
            "ONMC confirms sorted(set()) is the dead-end.  "
            "Applying dict.fromkeys to preserve order: `list(dict.fromkeys(items))`."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # null_coalesce_zero — ONMC-WIN: cc_alone tries `if value else`, hits 0 edge case
    # -----------------------------------------------------------------------
    {
        "task_id": "null_coalesce_zero",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 534,
        "duration_s": 8.1,
        "agent_output": (
            "The bug is `value or default` — replacing with `value if value else default`.  "
            "This handles None but still fails for 0 and False since they are falsy."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "null_coalesce_zero",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 498,
        "duration_s": 7.4,
        "agent_output": (
            "ONMC context flags `if value else` as the dead-end.  "
            "Using explicit None check: `return default if value is None else value`."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # money_round_half_even — ONMC-WIN: cc_alone tries epsilon-offset dead-end
    # -----------------------------------------------------------------------
    {
        "task_id": "money_round_half_even",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 612,
        "duration_s": 9.3,
        "agent_output": (
            "Float imprecision causes round(2.675, 2) == 2.67.  "
            "Adding a small epsilon before rounding: `round(amount + 1e-9, 2)`.  "
            "This fixes 2.675 but breaks test_round_normal (1.234 becomes 1.24)."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "money_round_half_even",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 571,
        "duration_s": 8.4,
        "agent_output": (
            "ONMC context names epsilon-offset as the dead-end.  "
            "Using Decimal: `float(Decimal(str(amount)).quantize(Decimal('0.01'), ROUND_HALF_UP))`."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # pagination_offset — ONMC-WIN: cc_alone tries (page+1)*size overcorrection
    # -----------------------------------------------------------------------
    {
        "task_id": "pagination_offset",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 488,
        "duration_s": 7.2,
        "agent_output": (
            "The offset is too large by one page.  Trying `(page + 1) * page_size` "
            "to shift by one extra.  Page 1 still wrong: gives 20 instead of 0."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "pagination_offset",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 453,
        "duration_s": 6.8,
        "agent_output": (
            "ONMC context names the (page+1) overcorrection.  "
            "Correct fix: `return (page - 1) * page_size`.  Page 1 → 0, page 2 → size."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # retry_no_presleep — TIE: both agents find the range(max_attempts) fix
    # -----------------------------------------------------------------------
    {
        "task_id": "retry_no_presleep",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 556,
        "duration_s": 8.8,
        "agent_output": (
            "Two bugs: `range(max_attempts + 1)` adds one extra attempt, "
            "and `time.sleep(delay)` fires before the first try.  "
            "Fixed to `range(max_attempts)` with sleep inside the except block."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "retry_no_presleep",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 531,
        "duration_s": 8.2,
        "agent_output": (
            "ONMC notes max_attempts-1 is the named dead-end.  "
            "Applied correct fix: `range(max_attempts)` with sleep between retries only."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # cache_key_kwargs_sorted — ONMC-WIN: cc_alone switches to repr() (same problem)
    # -----------------------------------------------------------------------
    {
        "task_id": "cache_key_kwargs_sorted",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 502,
        "duration_s": 7.6,
        "agent_output": (
            "str(kwargs) gives a dict that depends on repr, not insertion order.  "
            "Switching to repr(kwargs) to get a more canonical representation.  "
            "repr() still preserves dict order — keys differ when called in different order."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "cache_key_kwargs_sorted",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 469,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC context flags repr() as the dead-end.  "
            "Sorting the items for a stable key: `return str(sorted(kwargs.items()))`."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # utc_aware_parse — TIE: both agents use replace(tzinfo=timezone.utc)
    # -----------------------------------------------------------------------
    {
        "task_id": "utc_aware_parse",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 491,
        "duration_s": 7.3,
        "agent_output": (
            "fromisoformat returns a naive datetime for strings without tz suffix.  "
            "Replacing Z with +00:00 and attaching UTC if tzinfo is None: "
            "`dt.replace(tzinfo=timezone.utc)`."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "utc_aware_parse",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 467,
        "duration_s": 6.8,
        "agent_output": (
            "ONMC context names appending 'Z' as the dead-end.  "
            "Using portable fix: replace Z with +00:00 then "
            "`replace(tzinfo=timezone.utc)` for naive datetimes."
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
