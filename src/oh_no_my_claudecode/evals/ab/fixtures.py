"""Pre-recorded fixture results for the A/B eval harness.

These fixtures represent a realistic run of the built-in and private-knowledge
task suites.  They are NOT auto-generated failures — they were designed to
reflect plausible agent behaviour on these tasks:

- cc_alone: the cold agent sees only the task description.  On tasks
  with a plausible "wrong fix" dead-end it may apply the wrong patch.
- cc_onmc: the ONMC-grounded agent receives the hand-authored hint and steers
  to the correct fix.
- cc_onmc_auto: the ONMC-grounded agent receives recall compiled from the
  real ingest→recall pipeline over a grounding_doc artifact — no hand hint.
  This fixture models the honest auto-capture hypothesis: recall mostly
  surfaces the rule, but may be weaker than the hand hint for tasks requiring
  exact reproduction of arbitrary codes.

IMPORTANT: These results are PRE-RECORDED for CI reproducibility.  They
do NOT prove that ONMC always wins on these tasks in a live run.  Live
results vary by model, temperature, and prompt phrasing.  To collect live
results, run without --fixture.

Private-knowledge suite (``private_tasks.py``)
----------------------------------------------
All 10 private-knowledge tasks have cc_alone=fail / cc_onmc=pass in the
fixture.  This reflects the honest hypothesis: a cold agent cannot know
an arbitrary internal convention and applies a reasonable but wrong default.
The ONMC condition receives the memory hint and applies the correct fix.
The fixture represents the pre-recorded hypothesis; a live run is the real
test of it.

cc_onmc_auto fixture (auto-capture condition)
---------------------------------------------
8/10 private tasks have cc_onmc_auto=pass: the auto-captured recall surfaces
enough of the rule for the agent to apply the correct fix.  2/10 tasks have
cc_onmc_auto=fail:
- house_error_code_prefix: the exact ACME-4004 / ACME-4001 / ACME-4029
  mapping requires precise reproduction of three arbitrary code pairs, and
  recall may not surface all three with enough fidelity.
- audit_log_schema_version: the exact version string "audit.v2" (as opposed
  to "v2", "audit_v2", etc.) requires verbatim recall that auto-capture
  cannot always guarantee.
This is the honest answer to the product-loop question: auto-capture nearly
matches the hand-hint win but falls short on tasks requiring exact memorisation
of arbitrary string values.

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
    # =======================================================================
    # PRIVATE-KNOWLEDGE SUITE — all 5 tasks: cc_alone=fail, cc_onmc=pass
    # The hypothesis: arbitrary house conventions are unknowable without memory.
    # =======================================================================
    # -----------------------------------------------------------------------
    # house_error_code_prefix — ONMC-WIN: cc_alone uses generic string (NOT_FOUND)
    # -----------------------------------------------------------------------
    {
        "task_id": "house_error_code_prefix",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 521,
        "duration_s": 7.8,
        "agent_output": (
            "The function should return a standardised error code.  "
            "Using uppercased kind strings: not_found -> NOT_FOUND, "
            "unauthorized -> UNAUTHORIZED, rate_limited -> RATE_LIMITED.  "
            "No information in the task about a specific prefix format."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "house_error_code_prefix",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 489,
        "duration_s": 7.1,
        "agent_output": (
            "ONMC context provides the ACME-XXXX mapping: "
            "not_found -> ACME-4004, unauthorized -> ACME-4001, "
            "rate_limited -> ACME-4029.  Implemented as a dict lookup."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # tenant_header — ONMC-WIN: cc_alone uses X-Tenant-ID (plausible wrong name)
    # -----------------------------------------------------------------------
    {
        "task_id": "tenant_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 498,
        "duration_s": 7.4,
        "agent_output": (
            "Adding workspace routing header.  X-Tenant-ID is the standard "
            "convention for tenant identification in REST APIs.  "
            "Set Authorization: Bearer <token> and X-Tenant-ID: <workspace_id>."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "tenant_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 471,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC incident memory: X-Tenant-ID was the bug — gateway silently drops it.  "
            "Correct header is X-Acme-Workspace.  "
            "Setting Authorization and X-Acme-Workspace headers."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # retry_only_503_incident — ONMC-WIN: cc_alone retries all 5xx (standard practice)
    # -----------------------------------------------------------------------
    {
        "task_id": "retry_only_503_incident",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 511,
        "duration_s": 7.6,
        "agent_output": (
            "Retry on all 5xx server errors is standard practice for transient failures.  "
            "Keeping `500 <= status < 600` — this handles all server-side errors "
            "including 500, 502, 503, and 504."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "retry_only_503_incident",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 476,
        "duration_s": 7.0,
        "agent_output": (
            "ONMC incident memory: retrying all 5xx caused double charges.  "
            "Only 503 is safe to retry for this payment client.  "
            "Changing to: return status == 503"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # idempotency_key_format — ONMC-WIN: cc_alone uses dash separator
    # -----------------------------------------------------------------------
    {
        "task_id": "idempotency_key_format",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 487,
        "duration_s": 7.3,
        "agent_output": (
            "Building a deterministic idempotency key from the three parts.  "
            "Using dash-separated format: f'{tenant}-{op}-{uid}'.  "
            "This is deterministic and unique per operation."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "idempotency_key_format",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 458,
        "duration_s": 6.7,
        "agent_output": (
            "ONMC context: dedup service splits on ':' — colon is mandatory.  "
            "Format is tenant:op:uid.  "
            "Implementing: return f'{tenant}:{op}:{uid}'"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # money_minor_units — ONMC-WIN: cc_alone uses float (truncates 1.10 to 109)
    # -----------------------------------------------------------------------
    {
        "task_id": "money_minor_units",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 534,
        "duration_s": 8.0,
        "agent_output": (
            "Converting rupee string to paise by multiplying by 100.  "
            "Using int(float(rupees) * 100) — standard approach for "
            "string-to-minor-unit conversion.  "
            "float('2.30') * 100 gives 229.999... which int() truncates to 229."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "money_minor_units",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 503,
        "duration_s": 7.5,
        "agent_output": (
            "ONMC incident memory: float truncates 1.10*100 to 109.  "
            "Must use Decimal for monetary conversion: "
            "int(Decimal(rupees) * 100).  Importing from decimal module."
        ),
        "error": None,
        "fixture": True,
    },
    # =======================================================================
    # AUTO-CAPTURE SUITE — cc_onmc_auto results for private-knowledge tasks.
    # The auto condition seeds a temp ONMC brain by ingesting grounding_doc via
    # the real doc-ingest pipeline (no hand-written hint), then compiles recall.
    # 4/5 tasks: auto-recall surfaces enough of the rule to win.
    # 1/5 (house_error_code_prefix): recall surfaces the ACME prefix but the
    #   agent fails to reproduce all three exact code pairs (ACME-4004 /
    #   ACME-4001 / ACME-4029) precisely — arbitrary code memorisation is weaker
    #   than a hand hint that gives the exact mapping.
    # =======================================================================
    # -----------------------------------------------------------------------
    # house_error_code_prefix — AUTO FAIL: codes are too specific for auto recall
    # -----------------------------------------------------------------------
    {
        "task_id": "house_error_code_prefix",
        "condition": "cc_onmc_auto",
        "passed": False,
        "tokens": 508,
        "duration_s": 7.9,
        "agent_output": (
            "Auto recall surfaces the ACME- prefix convention from the doc.  "
            "Implemented a lookup dict with ACME- prefixed codes, but the exact "
            "numeric suffixes (4004, 4001, 4029) were not clearly recalled — "
            "used ACME-404, ACME-401, ACME-429 (guessed HTTP codes) instead.  "
            "Gate fails because the test expects the exact ACME-4004 / ACME-4001 "
            "/ ACME-4029 mapping."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # tenant_header — AUTO PASS: X-Acme-Workspace is explicitly named in doc
    # -----------------------------------------------------------------------
    {
        "task_id": "tenant_header",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 484,
        "duration_s": 7.2,
        "agent_output": (
            "Auto recall surfaces the gateway doc excerpt: X-Acme-Workspace is "
            "the correct header for workspace routing.  Replacing X-Tenant-ID "
            "with X-Acme-Workspace in build_headers()."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # retry_only_503_incident — AUTO PASS: 503-only rule explicitly stated
    # -----------------------------------------------------------------------
    {
        "task_id": "retry_only_503_incident",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 491,
        "duration_s": 7.3,
        "agent_output": (
            "Auto recall surfaces the incident postmortem: retry ONLY on 503, "
            "never on 500/502/504 (double-charge risk).  "
            "Implementing: return status == 503"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # idempotency_key_format — AUTO PASS: colon separator explicitly named in doc
    # -----------------------------------------------------------------------
    {
        "task_id": "idempotency_key_format",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 471,
        "duration_s": 7.0,
        "agent_output": (
            "Auto recall surfaces the DESIGN.md excerpt: dedup service splits on "
            "colon, required format is tenant:op:uid.  "
            "Implementing: return f'{tenant}:{op}:{uid}'"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # money_minor_units — AUTO PASS: Decimal pattern explicitly stated in doc
    # -----------------------------------------------------------------------
    {
        "task_id": "money_minor_units",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 496,
        "duration_s": 7.6,
        "agent_output": (
            "Auto recall surfaces the financial guidelines doc: float arithmetic "
            "is forbidden; use Decimal(rupees) * 100.  "
            "Implementing: from decimal import Decimal; return int(Decimal(rupees) * 100)"
        ),
        "error": None,
        "fixture": True,
    },
    # =======================================================================
    # NEW PRIVATE-KNOWLEDGE TASKS 6-10
    # =======================================================================
    # -----------------------------------------------------------------------
    # epoch_millis_timestamp — ONMC-WIN: cc_alone returns ISO 8601 string
    # -----------------------------------------------------------------------
    {
        "task_id": "epoch_millis_timestamp",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 498,
        "duration_s": 7.3,
        "agent_output": (
            "The function should return a datetime as a string.  "
            "Using ISO 8601 format: dt.isoformat().  "
            "This is the standard string representation for datetimes in APIs."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "epoch_millis_timestamp",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 471,
        "duration_s": 6.8,
        "agent_output": (
            "ONMC context: iOS client requires epoch-milliseconds-as-string, "
            "not ISO format.  Incident: ISO timestamps parsed as zero.  "
            "Implementing: return str(int(dt.timestamp() * 1000))"
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "epoch_millis_timestamp",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 483,
        "duration_s": 7.1,
        "agent_output": (
            "Auto recall surfaces the API timestamp doc: epoch-ms string required, "
            "ISO format causes iOS parse-zero bug.  "
            "Implementing: return str(int(dt.timestamp() * 1000))"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # pagination_cursor_scheme — ONMC-WIN: cc_alone returns str(page)
    # -----------------------------------------------------------------------
    {
        "task_id": "pagination_cursor_scheme",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 487,
        "duration_s": 7.2,
        "agent_output": (
            "The cursor should encode the page number for pagination.  "
            "Returning str(page) as an opaque cursor string.  "
            "This is deterministic and allows the service to reconstruct the page."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "pagination_cursor_scheme",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 459,
        "duration_s": 6.6,
        "agent_output": (
            "ONMC context: cursor parser splits on '~' (tilde separator).  "
            "Format must be '{page}~{watermark}'.  "
            "Implementing: return f'{page}~{watermark}'"
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "pagination_cursor_scheme",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 468,
        "duration_s": 6.9,
        "agent_output": (
            "Auto recall surfaces cursor format doc: tilde separator, format is "
            "'{page}~{watermark}'.  Dash/underscore/base64 rejected by decoder.  "
            "Implementing: return f'{page}~{watermark}'"
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # audit_log_schema_version — ONMC-WIN: cc_alone omits _schema field
    # -----------------------------------------------------------------------
    {
        "task_id": "audit_log_schema_version",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 503,
        "duration_s": 7.5,
        "agent_output": (
            "Building audit log payload with action, user_id, and timestamp.  "
            "Returning {'action': action, 'user_id': user_id, 'ts': int(time.time())}.  "
            "No information about a required schema version field."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "audit_log_schema_version",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 476,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC context: audit pipeline requires '_schema': 'audit.v2'.  "
            "Without this field, payloads are silently dropped by the validator.  "
            "Adding '_schema': 'audit.v2' to the payload dict."
        ),
        "error": None,
        "fixture": True,
    },
    # AUTO FAIL: exact version string "audit.v2" is hard to recall verbatim
    {
        "task_id": "audit_log_schema_version",
        "condition": "cc_onmc_auto",
        "passed": False,
        "tokens": 489,
        "duration_s": 7.2,
        "agent_output": (
            "Auto recall surfaces the audit pipeline doc: a '_schema' field is "
            "required.  Added '_schema': 'v2' to the payload.  "
            "Gate fails because the test expects the exact string 'audit.v2', not 'v2'."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # currency_allowlist — ONMC-WIN: cc_alone validates format only (accepts GBP)
    # -----------------------------------------------------------------------
    {
        "task_id": "currency_allowlist",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 511,
        "duration_s": 7.7,
        "agent_output": (
            "Validating currency code: must be a 3-letter uppercase ISO 4217 code.  "
            "Checking len==3 and code.isupper() and code.isalpha().  "
            "GBP, EUR, JPY all pass — no way to know which specific currencies are allowed."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "currency_allowlist",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 464,
        "duration_s": 6.7,
        "agent_output": (
            "ONMC context: hard allowlist is {INR, USD, SGD} only.  "
            "GBP caused a 72-hour reconciliation backlog in 2023.  "
            "Implementing: _ALLOWED = {'INR', 'USD', 'SGD'}; raise if code not in _ALLOWED."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "currency_allowlist",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 479,
        "duration_s": 7.0,
        "agent_output": (
            "Auto recall surfaces the currency allowlist doc: INR, USD, SGD are the "
            "only accepted codes.  GBP, EUR, JPY must raise ValueError.  "
            "Implementing the three-currency allowlist."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # webhook_signature_header — ONMC-WIN: cc_alone uses X-Signature, bare hex
    # -----------------------------------------------------------------------
    {
        "task_id": "webhook_signature_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 519,
        "duration_s": 7.8,
        "agent_output": (
            "Adding HMAC-SHA-256 signature to webhook delivery.  "
            "Using 'X-Signature' header with the raw hex digest.  "
            "Standard practice for signed webhook delivery."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "webhook_signature_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 482,
        "duration_s": 7.0,
        "agent_output": (
            "ONMC context: header must be 'X-Acme-Hook-Sig' with value 'sha256={hex}'.  "
            "X-Signature is rejected by the receiver's middleware.  "
            "Implementing with correct header name and sha256= prefix."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "webhook_signature_header",
        "condition": "cc_onmc_auto",
        "passed": True,
        "tokens": 493,
        "duration_s": 7.2,
        "agent_output": (
            "Auto recall surfaces webhook delivery doc: header is 'X-Acme-Hook-Sig', "
            "value format is 'sha256={hex_digest}'.  X-Signature is not recognised.  "
            "Implementing both the correct header name and the required value prefix."
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
