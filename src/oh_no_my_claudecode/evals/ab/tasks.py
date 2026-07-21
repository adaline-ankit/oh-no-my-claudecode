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
  - list_slice_fix:    wrong fix = `n-1` or `n+2`; right fix = `n`
  - accumulator_init:  wrong fix = resetting `total=x` each iteration; right fix = `total=0`
  - word_reverse:      wrong fix = removing `[::-1]` entirely; right fix = remove the `[1:]`
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
# Full built-in task suite
# ---------------------------------------------------------------------------

BUILTIN_TASKS: list[ABTask] = [
    TASK_LIST_SLICE_FIX,
    TASK_ACCUMULATOR_INIT,
    TASK_WORD_REVERSE,
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
