"""Synthetic and pinned-public-repository A/B eval task suites.

Synthetic tasks are self-contained: ``setup_script`` creates a minimal Python file
with a known bug and a pytest test that exposes it.  No network access, no
external repos cloned. Each task is runnable in any temporary directory with
only Python + pytest installed.

Design principles
-----------------
- The bug must be PLAUSIBLE — something a real developer might write.
- The ONMC hint must be SPECIFIC — it names the wrong approach that was
  previously tried, mirroring what compile_guard() would inject.
- The gate is OBJECTIVE — pytest exit code, no LLM judge.
- Both conditions start from the SAME buggy state — the harness resets the
  repo between conditions.

Why synthetic tasks are not product evidence
---------------------------------------------
Each task has a plausible "wrong fix" that an agent without memory might
attempt. They exercise harness behavior deterministically, but fixture outcomes
must not be used as evidence that ONMC improves a real agent. Public tasks pin
third-party pre-fix commits and apply only upstream regression tests.

Concretely:
  - list_slice_fix:       wrong fix = `n-1` or `n+2`; right fix = `n`
  - accumulator_init:     wrong fix = resetting `total=x` each iteration; right fix = `total=0`
  - word_reverse:         wrong fix = removing `[::-1]` entirely; right fix = remove the `[1:]`
  - dedup_preserve_order: wrong fix = `list(set(x))`; right fix = `dict.fromkeys`
  - null_coalesce_zero:   wrong fix = `x or default`; right fix = `default if x is None else x`
  - money_round_half_even: wrong fix = `round(x, 2)`; right fix = `Decimal.quantize(ROUND_HALF_UP)`
  - pagination_offset:    wrong fix = `page * size`; right fix = `(page - 1) * size`
  - retry_no_presleep:    wrong fix = `range(max_attempts + 1)`; right fix = `range(max_attempts)`
  - cache_key_kwargs_sorted: wrong fix = `str(kwargs)`; right fix = `str(sorted(kwargs.items()))`
  - utc_aware_parse:      wrong fix = bare `fromisoformat`; right fix = attach `timezone.utc`
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.ab.models import ABTask

# ---------------------------------------------------------------------------
# Task 1: off-by-one in list slice
# ---------------------------------------------------------------------------

_SETUP_LIST_SLICE = """\
# setup_list_slice_fix.py  (executed inside temp repo)
import pathlib

pathlib.Path("utils.py").write_text('''
def top_n(lst, n):
    \"\"\"Return the top n largest elements from lst, in descending order.\"\"\"
    return sorted(lst, reverse=True)[:n + 1]   # BUG: should be [:n]
''')

pathlib.Path("test_utils.py").write_text('''
from utils import top_n

def test_top_n_basic():
    assert top_n([3, 1, 4, 1, 5, 9, 2, 6], 3) == [9, 6, 5]

def test_top_n_single():
    assert top_n([7, 2, 4], 1) == [7]

def test_top_n_exact():
    # When n equals list length, return all elements sorted
    assert top_n([5, 3, 8], 3) == [8, 5, 3]
''')
"""

_ONMC_HINT_LIST_SLICE = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt at fixing top_n changed
  `[:n + 1]` to `[:n - 1]`.  This makes the slice too short, causing
  test_top_n_basic and test_top_n_exact to fail with wrong lengths.
  Do NOT use n-1.

CORRECT APPROACH: The bug is that `n + 1` returns one too many elements.
  Change `[:n + 1]` to `[:n]`.  No other changes needed.
[/ONMC Memory Context]

"""

TASK_LIST_SLICE_FIX = ABTask(
    id="list_slice_fix",
    description=(
        "The function `top_n(lst, n)` in utils.py is supposed to return the top n "
        "largest elements from lst in descending order.  It has a bug — the slice "
        "index is wrong.  Fix it so all tests in test_utils.py pass."
    ),
    setup_script=_SETUP_LIST_SLICE,
    gate_command="python -m pytest test_utils.py -x -q",
    onmc_hint=_ONMC_HINT_LIST_SLICE,
    note=(
        "Classic off-by-one.  Without the ONMC hint an agent might try n-1, "
        "which passes test_top_n_basic but fails test_top_n_exact.  The hint "
        "eliminates that dead-end."
    ),
    protected_paths=("test_utils.py",),
)


# ---------------------------------------------------------------------------
# Task 2: accumulator initialised wrong
# ---------------------------------------------------------------------------

_SETUP_ACCUMULATOR = """\
# setup_accumulator_init.py  (executed inside temp repo)
import pathlib

pathlib.Path("stats.py").write_text('''
def running_sum(lst):
    \"\"\"Return a list where each element is the cumulative sum up to that index.\"\"\"
    result = []
    total = 1          # BUG: should be 0
    for x in lst:
        total += x
        result.append(total)
    return result
''')

pathlib.Path("test_stats.py").write_text('''
from stats import running_sum

def test_running_sum_basic():
    assert running_sum([1, 2, 3]) == [1, 3, 6]

def test_running_sum_single():
    assert running_sum([5]) == [5]

def test_running_sum_zeros():
    assert running_sum([0, 0, 0]) == [0, 0, 0]
''')
"""

_ONMC_HINT_ACCUMULATOR = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt changed `total += x` to
  `total = x` (reset each iteration).  This breaks multi-element sums:
  running_sum([1, 2, 3]) returns [1, 2, 3] instead of [1, 3, 6].
  Do NOT reset total inside the loop.

CORRECT APPROACH: The bug is the initial value `total = 1` — it starts
  one off.  Change it to `total = 0` so the accumulation begins correctly.
[/ONMC Memory Context]

"""

TASK_ACCUMULATOR_INIT = ABTask(
    id="accumulator_init",
    description=(
        "The function `running_sum(lst)` in stats.py should return a list where "
        "each element is the cumulative sum up to that index.  It has a bug: the "
        "accumulator starts at the wrong value.  Fix it so all tests in test_stats.py pass."
    ),
    setup_script=_SETUP_ACCUMULATOR,
    gate_command="python -m pytest test_stats.py -x -q",
    onmc_hint=_ONMC_HINT_ACCUMULATOR,
    note=(
        "Initialisation bug.  Without the hint an agent might try resetting "
        "`total = x` inside the loop (plausible refactor), which makes single-"
        "element tests pass but breaks multi-element ones.  The hint steers "
        "directly to `total = 0`."
    ),
    protected_paths=("test_stats.py",),
)


# ---------------------------------------------------------------------------
# Task 3: slice drops last word in reverse
# ---------------------------------------------------------------------------

_SETUP_WORD_REVERSE = """\
# setup_word_reverse.py  (executed inside temp repo)
import pathlib

pathlib.Path("text_utils.py").write_text('''
def reverse_words(s):
    \"\"\"Reverse the order of words in a string.\"\"\"
    # BUG: the [1:] drops the last word after reversal
    return " ".join(s.split()[::-1][1:])
''')

pathlib.Path("test_text_utils.py").write_text('''
from text_utils import reverse_words

def test_two_words():
    assert reverse_words("hello world") == "world hello"

def test_three_words():
    assert reverse_words("the quick fox") == "fox quick the"

def test_single_word():
    assert reverse_words("python") == "python"
''')
"""

_ONMC_HINT_WORD_REVERSE = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt replaced `[1:]` with `[:-1]`
  to try to fix the off-by-one.  This still drops a word: "hello world"
  becomes "world" instead of "world hello".  Do NOT use [:-1].

PAST FAILURE (dead-end): Another attempt removed `[::-1]` entirely and
  relied on `reversed()`.  That broke test_three_words.

CORRECT APPROACH: Remove the trailing `[1:]` slice entirely.  The full
  expression should be `s.split()[::-1]` with no extra slice.
[/ONMC Memory Context]

"""

TASK_WORD_REVERSE = ABTask(
    id="word_reverse",
    description=(
        "The function `reverse_words(s)` in text_utils.py should reverse the order "
        "of words in a string (e.g. 'hello world' → 'world hello').  It has a bug "
        "that drops one word.  Fix it so all tests in test_text_utils.py pass."
    ),
    setup_script=_SETUP_WORD_REVERSE,
    gate_command="python -m pytest test_text_utils.py -x -q",
    onmc_hint=_ONMC_HINT_WORD_REVERSE,
    note=(
        "Slice-drop bug.  Without memory an agent might try [:-1] or remove "
        "[::-1] — both fail.  The ONMC hint names both dead-ends and points "
        "directly to removing [1:]."
    ),
    protected_paths=("test_text_utils.py",),
)


# ---------------------------------------------------------------------------
# Task 4: dedup preserving insertion order
# ---------------------------------------------------------------------------

_SETUP_DEDUP_PRESERVE_ORDER = """\
# setup_dedup_preserve_order.py  (executed inside temp repo)
import pathlib

pathlib.Path("dedup.py").write_text('''
def dedup(items):
    \"\"\"Return items with duplicates removed, preserving first-seen order.\"\"\"
    return list(set(items))  # BUG: set() does not preserve insertion order
''')

pathlib.Path("test_dedup.py").write_text('''
from dedup import dedup

def test_dedup_preserves_order():
    assert dedup([3, 1, 4, 1, 5, 3, 2]) == [3, 1, 4, 5, 2]

def test_dedup_single():
    assert dedup([1]) == [1]

def test_dedup_all_same():
    assert dedup([7, 7, 7]) == [7]
''')
"""

_ONMC_HINT_DEDUP_PRESERVE_ORDER = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt wrapped the list in set() and
  sorted it: `sorted(set(items))`.  This removes duplicates but imposes
  alphabetical/numeric order instead of preserving insertion order.
  test_dedup_preserves_order expects [3, 1, 4, 5, 2], not [1, 2, 3, 4, 5].

CORRECT APPROACH: Use dict.fromkeys(items) which preserves insertion order
  while discarding duplicates: `list(dict.fromkeys(items))`.  No sorting.
[/ONMC Memory Context]

"""

TASK_DEDUP_PRESERVE_ORDER = ABTask(
    id="dedup_preserve_order",
    description=(
        "The function `dedup(items)` in dedup.py should return the list with "
        "duplicate values removed while preserving the first-seen order of each "
        "element.  It currently uses `set()` which does not preserve order.  "
        "Fix it so all tests in test_dedup.py pass."
    ),
    setup_script=_SETUP_DEDUP_PRESERVE_ORDER,
    gate_command="python -m pytest test_dedup.py -x -q",
    onmc_hint=_ONMC_HINT_DEDUP_PRESERVE_ORDER,
    note=(
        "Order-preservation bug.  Without the hint an agent might try "
        "`sorted(set(items))` (a plausible 'deduplicate and clean up' reflex), "
        "which loses the original order.  The hint steers to dict.fromkeys."
    ),
    protected_paths=("test_dedup.py",),
)


# ---------------------------------------------------------------------------
# Task 5: null coalescing that correctly handles falsy non-None values
# ---------------------------------------------------------------------------

_SETUP_NULL_COALESCE_ZERO = """\
# setup_null_coalesce_zero.py  (executed inside temp repo)
import pathlib

pathlib.Path("coalesce.py").write_text('''
def coalesce(value, default):
    \"\"\"Return value if it is not None, otherwise return default.\"\"\"
    return value or default  # BUG: treats 0, \\"\\", False as missing
''')

pathlib.Path("test_coalesce.py").write_text('''
from coalesce import coalesce

def test_coalesce_none():
    assert coalesce(None, 42) == 42

def test_coalesce_zero():
    assert coalesce(0, 42) == 0

def test_coalesce_empty_string():
    assert coalesce("", "default") == ""

def test_coalesce_false():
    assert coalesce(False, True) is False
''')
"""

_ONMC_HINT_NULL_COALESCE_ZERO = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt changed `value or default` to
  `value if value else default`.  This still treats 0, "", and False as missing
  because they are all falsy.  test_coalesce_zero and test_coalesce_false
  continue to fail.  Do NOT use truthiness tests to decide between value and default.

CORRECT APPROACH: Only None should trigger the fallback.  Use an explicit
  None check: `default if value is None else value`.  This preserves 0,
  empty strings, and False as legitimate values.
[/ONMC Memory Context]

"""

TASK_NULL_COALESCE_ZERO = ABTask(
    id="null_coalesce_zero",
    description=(
        "The function `coalesce(value, default)` in coalesce.py should return "
        "`value` when it is not None, and `default` only when value is None.  "
        "It currently uses `value or default` which incorrectly treats 0, "
        'empty strings, and False as missing.  Fix it so all tests in '
        "test_coalesce.py pass."
    ),
    setup_script=_SETUP_NULL_COALESCE_ZERO,
    gate_command="python -m pytest test_coalesce.py -x -q",
    onmc_hint=_ONMC_HINT_NULL_COALESCE_ZERO,
    note=(
        "Falsy-vs-None bug.  Without the hint an agent might replace `or` with "
        "`if value else` (equally wrong) or add a `not value` guard.  The ONMC "
        "hint names the dead-end and points to the explicit `is None` check."
    ),
    protected_paths=("test_coalesce.py",),
)


# ---------------------------------------------------------------------------
# Task 6: monetary rounding half-up via Decimal
# ---------------------------------------------------------------------------

_SETUP_MONEY_ROUND_HALF_EVEN = """\
# setup_money_round_half_even.py  (executed inside temp repo)
import pathlib

pathlib.Path("money.py").write_text('''
def round_money(amount):
    \"\"\"Round a monetary amount to 2 decimal places using half-up rounding.\"\"\"
    return round(amount, 2)  # BUG: uses banker\\'s rounding + float imprecision
''')

pathlib.Path("test_money.py").write_text('''
from money import round_money

def test_round_half_up_2_675():
    # 2.675 stored as float is ~2.6749999... so round(2.675, 2) == 2.67
    # Half-up rounding requires Decimal arithmetic to correctly return 2.68
    assert round_money(2.675) == 2.68, (
        f"Expected 2.68 (half-up) but got {round_money(2.675)!r}"
    )

def test_round_normal():
    assert round_money(1.234) == 1.23

def test_round_already_2dp():
    assert round_money(3.50) == 3.50
''')
"""

_ONMC_HINT_MONEY_ROUND_HALF_EVEN = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A prior attempt added `+ 1e-9` to the amount before
  calling `round()` to nudge the float.  This creates a different class of
  imprecision and breaks test_round_normal (1.234 becomes 1.24).
  Do NOT patch floats with epsilon offsets.

CORRECT APPROACH: Use Python's decimal module.  Convert to Decimal via
  str() to avoid float representation issues, then call quantize with
  ROUND_HALF_UP:
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP))
[/ONMC Memory Context]

"""

TASK_MONEY_ROUND_HALF_EVEN = ABTask(
    id="money_round_half_even",
    description=(
        "The function `round_money(amount)` in money.py should round a monetary "
        "float to 2 decimal places using half-up rounding (0.5 rounds away from "
        "zero).  The current implementation uses Python's built-in `round()` "
        "which applies banker's rounding and has float representation issues "
        "(e.g. round(2.675, 2) == 2.67, not 2.68).  Fix it so all tests in "
        "test_money.py pass."
    ),
    setup_script=_SETUP_MONEY_ROUND_HALF_EVEN,
    gate_command="python -m pytest test_money.py -x -q",
    onmc_hint=_ONMC_HINT_MONEY_ROUND_HALF_EVEN,
    note=(
        "Fintech rounding trap.  Without the hint an agent might try an epsilon "
        "offset (+ 1e-9 before round()) — a common StackOverflow suggestion that "
        "introduces different imprecision.  The ONMC hint names that dead-end and "
        "points to Decimal.quantize(ROUND_HALF_UP)."
    ),
    protected_paths=("test_money.py",),
)


# ---------------------------------------------------------------------------
# Task 7: pagination offset for 1-based page numbers
# ---------------------------------------------------------------------------

_SETUP_PAGINATION_OFFSET = """\
# setup_pagination_offset.py  (executed inside temp repo)
import pathlib

pathlib.Path("pagination.py").write_text('''
def page_offset(page, page_size):
    \"\"\"Return the SQL OFFSET for a 1-based page number and page size.\"\"\"
    return page * page_size  # BUG: off-by-one; page 1 should give offset 0
''')

pathlib.Path("test_pagination.py").write_text('''
from pagination import page_offset

def test_first_page_offset_is_zero():
    assert page_offset(1, 10) == 0

def test_second_page_offset():
    assert page_offset(2, 10) == 10

def test_third_page_large_size():
    assert page_offset(3, 20) == 40
''')
"""

_ONMC_HINT_PAGINATION_OFFSET = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt changed `page * page_size` to
  `(page + 1) * page_size`.  This overcorrects: page 1 gives offset 20
  instead of 0, and page 2 gives offset 30 instead of 10.
  Do NOT add 1 to the page number.

CORRECT APPROACH: Subtract 1 from the page before multiplying:
  `(page - 1) * page_size`.  Page 1 → 0, page 2 → page_size, page 3 → 2*page_size.
[/ONMC Memory Context]

"""

TASK_PAGINATION_OFFSET = ABTask(
    id="pagination_offset",
    description=(
        "The function `page_offset(page, page_size)` in pagination.py computes "
        "the SQL OFFSET for a 1-based page number and page size.  It has an "
        "off-by-one bug: page 1 should return offset 0, but it currently returns "
        "page_size.  Fix it so all tests in test_pagination.py pass."
    ),
    setup_script=_SETUP_PAGINATION_OFFSET,
    gate_command="python -m pytest test_pagination.py -x -q",
    onmc_hint=_ONMC_HINT_PAGINATION_OFFSET,
    note=(
        "1-based indexing off-by-one.  Without the hint an agent might try "
        "`(page + 1) * page_size` (overcorrection) or subtract from page_size "
        "rather than from page.  The hint names the +1 dead-end and gives the "
        "direct fix."
    ),
    protected_paths=("test_pagination.py",),
)


# ---------------------------------------------------------------------------
# Task 8: retry helper — correct attempt count, no pre-sleep
# ---------------------------------------------------------------------------

_SETUP_RETRY_NO_PRESLEEP = """\
# setup_retry_no_presleep.py  (executed inside temp repo)
import pathlib

pathlib.Path("retry.py").write_text('''
import time

def retry(fn, max_attempts=3, delay=0.0):
    \"\"\"Retry fn up to max_attempts times; sleep delay seconds between retries.\"\"\"
    for attempt in range(max_attempts + 1):  # BUG: +1 runs one extra attempt
        time.sleep(delay)                    # BUG: sleeps before the first attempt too
        try:
            return fn()
        except Exception:
            if attempt >= max_attempts:
                raise
''')

pathlib.Path("test_retry.py").write_text('''
from retry import retry

def test_retry_exact_attempt_count():
    calls = []

    def always_fail():
        calls.append(1)
        raise ValueError("fail")

    try:
        retry(always_fail, max_attempts=2, delay=0)
    except ValueError:
        pass

    assert len(calls) == 2, f"Expected exactly 2 attempts but got {len(calls)}"

def test_retry_succeeds_on_first():
    calls = []

    def succeed():
        calls.append(1)
        return "ok"

    result = retry(succeed, max_attempts=3, delay=0)
    assert result == "ok"
    assert len(calls) == 1
''')
"""

_ONMC_HINT_RETRY_NO_PRESLEEP = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt changed `range(max_attempts + 1)`
  to `range(max_attempts - 1)`.  This makes retry() try one too FEW times:
  max_attempts=2 attempts only once, breaking test_retry_exact_attempt_count.
  Do NOT subtract from max_attempts.

CORRECT APPROACH: Two bugs need fixing together:
  1. Change `range(max_attempts + 1)` to `range(max_attempts)` so the loop
     runs exactly max_attempts iterations.
  2. Move `time.sleep(delay)` to AFTER the first attempt (inside the except
     block or after the try, before the next iteration).
  The raise condition becomes `if attempt >= max_attempts - 1`.
[/ONMC Memory Context]

"""

TASK_RETRY_NO_PRESLEEP = ABTask(
    id="retry_no_presleep",
    description=(
        "The function `retry(fn, max_attempts, delay)` in retry.py should call "
        "`fn` up to `max_attempts` times, sleeping `delay` seconds between "
        "retries (not before the first attempt).  It has two bugs: it runs "
        "max_attempts+1 times and sleeps before every attempt including the first.  "
        "Fix it so all tests in test_retry.py pass."
    ),
    setup_script=_SETUP_RETRY_NO_PRESLEEP,
    gate_command="python -m pytest test_retry.py -x -q",
    onmc_hint=_ONMC_HINT_RETRY_NO_PRESLEEP,
    note=(
        "Retry attempt-count and pre-sleep bugs.  Without the hint an agent "
        "might try max_attempts-1 (undercorrection, also wrong).  The ONMC hint "
        "names that dead-end and provides the correct two-part fix."
    ),
    protected_paths=("test_retry.py",),
)


# ---------------------------------------------------------------------------
# Task 9: cache key stable under keyword argument reordering
# ---------------------------------------------------------------------------

_SETUP_CACHE_KEY_KWARGS_SORTED = """\
# setup_cache_key_kwargs_sorted.py  (executed inside temp repo)
import pathlib

pathlib.Path("cache.py").write_text('''
def make_cache_key(**kwargs):
    \"\"\"Build a stable cache key from keyword arguments.\"\"\"
    return str(kwargs)  # BUG: dict str representation is insertion-order dependent
''')

pathlib.Path("test_cache.py").write_text('''
from cache import make_cache_key

def test_cache_key_order_independent():
    key1 = make_cache_key(a=1, b=2)
    key2 = make_cache_key(b=2, a=1)
    assert key1 == key2, f"Keys differ with same args in different order: {key1!r} != {key2!r}"

def test_cache_key_single_arg():
    key = make_cache_key(x=99)
    assert key == make_cache_key(x=99)

def test_cache_key_empty():
    assert make_cache_key() == make_cache_key()
''')
"""

_ONMC_HINT_CACHE_KEY_KWARGS_SORTED = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt changed `str(kwargs)` to
  `repr(kwargs)`.  repr() also preserves dict insertion order, so
  make_cache_key(a=1, b=2) and make_cache_key(b=2, a=1) still produce
  different strings.  Do NOT use repr() on the raw dict.

CORRECT APPROACH: Sort the items before stringifying so the key is
  independent of call-site argument order:
    return str(sorted(kwargs.items()))
  Sorted items produce a deterministic tuple regardless of kwargs order.
[/ONMC Memory Context]

"""

TASK_CACHE_KEY_KWARGS_SORTED = ABTask(
    id="cache_key_kwargs_sorted",
    description=(
        "The function `make_cache_key(**kwargs)` in cache.py should produce the "
        "same cache key regardless of the order keyword arguments are passed.  "
        "It currently uses `str(kwargs)` which depends on dict insertion order "
        "— so `make_cache_key(a=1, b=2)` and `make_cache_key(b=2, a=1)` produce "
        "different keys.  Fix it so all tests in test_cache.py pass."
    ),
    setup_script=_SETUP_CACHE_KEY_KWARGS_SORTED,
    gate_command="python -m pytest test_cache.py -x -q",
    onmc_hint=_ONMC_HINT_CACHE_KEY_KWARGS_SORTED,
    note=(
        "Dict-order cache bug.  Without the hint an agent might try `repr()` "
        "instead of `str()` — same problem.  The ONMC hint names that dead-end "
        "and points to `sorted(kwargs.items())`."
    ),
    protected_paths=("test_cache.py",),
)


# ---------------------------------------------------------------------------
# Task 10: parse ISO datetime as UTC-aware
# ---------------------------------------------------------------------------

_SETUP_UTC_AWARE_PARSE = """\
# setup_utc_aware_parse.py  (executed inside temp repo)
import pathlib

pathlib.Path("timeutil.py").write_text('''
from datetime import datetime

def parse_utc(iso_string):
    \"\"\"Parse an ISO 8601 string and return a UTC-aware datetime.\"\"\"
    return datetime.fromisoformat(iso_string)  # BUG: returns naive if no tz suffix
''')

pathlib.Path("test_timeutil.py").write_text('''
from datetime import timezone
from timeutil import parse_utc

def test_naive_input_becomes_utc():
    dt = parse_utc("2024-01-15T12:00:00")
    assert dt.tzinfo is not None, "parse_utc must return a tz-aware datetime"
    assert dt.utcoffset().total_seconds() == 0.0, "timezone must be UTC (offset=0)"

def test_utc_offset_input_stays_utc():
    dt = parse_utc("2024-01-15T12:00:00+00:00")
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0.0

def test_value_preserved():
    dt = parse_utc("2024-03-10T09:30:00")
    assert dt.year == 2024 and dt.hour == 9 and dt.minute == 30
''')
"""

_ONMC_HINT_UTC_AWARE_PARSE = """\
[ONMC Memory Context]
PAST FAILURE (dead-end): A previous attempt appended "Z" to the string before
  parsing: `datetime.fromisoformat(iso_string + "Z")`.  On Python < 3.11,
  fromisoformat does not support the "Z" suffix and raises ValueError.
  Do NOT append "Z" to the input string.

CORRECT APPROACH: After parsing, check if tzinfo is None and attach UTC:
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
  This handles both naive strings and explicit +00:00 offsets portably.
[/ONMC Memory Context]

"""

TASK_UTC_AWARE_PARSE = ABTask(
    id="utc_aware_parse",
    description=(
        "The function `parse_utc(iso_string)` in timeutil.py should parse an "
        "ISO 8601 date-time string and always return a UTC-aware datetime object.  "
        "When the input has no timezone suffix it currently returns a naive "
        "datetime (tzinfo is None).  Fix it so all tests in test_timeutil.py pass."
    ),
    setup_script=_SETUP_UTC_AWARE_PARSE,
    gate_command="python -m pytest test_timeutil.py -x -q",
    onmc_hint=_ONMC_HINT_UTC_AWARE_PARSE,
    note=(
        "Timezone-naive datetime bug.  Without the hint an agent might append "
        '"Z" to the string before fromisoformat — broken on Python < 3.11.  '
        "The ONMC hint names that dead-end and provides the portable fix using "
        "replace(tzinfo=timezone.utc)."
    ),
    protected_paths=("test_timeutil.py",),
)


# ---------------------------------------------------------------------------
# Full built-in task suite
# ---------------------------------------------------------------------------

BUILTIN_TASKS: list[ABTask] = [
    TASK_LIST_SLICE_FIX,
    TASK_ACCUMULATOR_INIT,
    TASK_WORD_REVERSE,
    TASK_DEDUP_PRESERVE_ORDER,
    TASK_NULL_COALESCE_ZERO,
    TASK_MONEY_ROUND_HALF_EVEN,
    TASK_PAGINATION_OFFSET,
    TASK_RETRY_NO_PRESLEEP,
    TASK_CACHE_KEY_KWARGS_SORTED,
    TASK_UTC_AWARE_PARSE,
]


# ---------------------------------------------------------------------------
# Public-repository task: encode/httpx timeout propagation
# ---------------------------------------------------------------------------

_HTTPX_TIMEOUT_TEST_PATCH = """\
diff --git a/tests/test_timeouts.py b/tests/test_timeouts.py
index 59f9af0..fa9c0ce 100644
--- a/tests/test_timeouts.py
+++ b/tests/test_timeouts.py
@@ -42,3 +42,14 @@ async def test_pool_timeout(server):
         with pytest.raises(httpx.PoolTimeout):
             async with client.stream("GET", server.url):
                 await client.get(server.url)
+
+
+@pytest.mark.anyio
+async def test_async_client_new_request_send_timeout(server):
+    timeout = httpx.Timeout(1e-6)
+
+    async with httpx.AsyncClient(timeout=timeout) as client:
+        with pytest.raises(httpx.TimeoutException):
+            await client.send(
+                httpx.Request("GET", server.url.copy_with(path="/slow_response"))
+            )
"""

TASK_HTTPX_DIRECT_REQUEST_TIMEOUT = ABTask(
    id="httpx_direct_request_timeout",
    description=(
        "Fix the regression demonstrated by "
        "tests/test_timeouts.py::test_async_client_new_request_send_timeout. "
        "A timeout configured on AsyncClient is ignored when send() receives a Request "
        "constructed directly. Preserve explicit request extensions and keep sync and async "
        "client behavior consistent. Do not modify the new regression test."
    ),
    setup_script="",
    gate_command=(
        "venv/bin/python -m pytest "
        "tests/test_timeouts.py::test_async_client_new_request_send_timeout -q"
    ),
    onmc_hint=(
        "A prior repository investigation found that requests created through client helpers "
        "inherit client defaults through request extensions, while directly constructed Request "
        "objects can bypass that lifecycle. Before changing transports, compare build_request, "
        "send, and the shared sync/async client path. Preserve caller-provided extensions."
    ),
    note=(
        "Real historical httpx regression. The task checks out the parent of upstream fix "
        "6d852d319acd and applies only its regression test; the production fix is absent."
    ),
    repo_url="https://github.com/encode/httpx.git",
    repo_commit="df5345140e09ac6c2de0d9589bcd6f3e31c6aa3f",
    setup_patch=_HTTPX_TIMEOUT_TEST_PATCH,
    setup_commands=(
        ("uv", "venv", "venv", "--seed"),
        (
            "uv",
            "pip",
            "install",
            "--python",
            "venv/bin/python",
            "-e",
            ".",
            "pytest",
            "trio",
            "trustme",
            "cryptography",
            "uvicorn",
        ),
    ),
    pass_to_pass_commands=(
        (
            "venv/bin/python",
            "-m",
            "pytest",
            "tests/test_timeouts.py::test_read_timeout",
            "tests/test_timeouts.py::test_connect_timeout",
            "tests/test_timeouts.py::test_pool_timeout",
            "-q",
        ),
    ),
    protected_paths=("tests/test_timeouts.py",),
)

PUBLIC_REPO_TASKS: list[ABTask] = [TASK_HTTPX_DIRECT_REQUEST_TIMEOUT]
