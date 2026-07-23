"""Private-knowledge A/B eval task suite.

Honest premise (read carefully — an interviewer WILL read this)
---------------------------------------------------------------
These tasks test ONE specific, fair claim: a memory layer injects
repo-specific knowledge the base model genuinely cannot infer.

Each task is solvable ONLY if you know an ARBITRARY private house rule
or a past-incident lesson — not something any competent model would
naturally apply.

Design rules
------------
- The private rule must be genuinely UN-INFERRABLE (an arbitrary internal
  convention or an incident learning).
- ``cc_alone`` must fail because it picks a *reasonable but wrong default*
  (the rule is unknowable), NOT because the task is broken or ambiguous.
  The prompt is clear and solvable — the ONLY missing piece is the private
  fact.
- The ``onmc_hint`` reads like a REAL memory entry (a past DECISION /
  CONVENTION / a FAILED_APPROACH incident dead-end).  It states the rule
  plus the reason, as compile_guard/compile_recall would inject it.  It is
  NOT a tautological restatement of the test.
- ``setup_script`` writes ONLY the stub (raising NotImplementedError or a
  plausible-wrong default).  The gate test is kept in ``hidden_gate_test``
  and is withheld from the agent during setup — written only after the agent
  finishes.  This preserves info-asymmetry: the agent cannot read the private
  rule off the test file.

Tasks in this suite
-------------------
1. house_error_code_prefix  — arbitrary ACME-XXXX error codes (un-inferrable)
2. tenant_header             — arbitrary header name X-Acme-Workspace (incident)
3. retry_only_503_incident   — payment double-charge incident dead-end
4. idempotency_key_format    — colon-separated key the dedup layer parses
5. money_minor_units         — Decimal-only paise conversion (float-rounding incident)
"""

from __future__ import annotations

from oh_no_my_claudecode.evals.ab.models import ABTask

# ---------------------------------------------------------------------------
# Task 1: house_error_code_prefix — arbitrary ACME-XXXX error codes
# ---------------------------------------------------------------------------

_SETUP_HOUSE_ERROR_CODE = """\
# setup_house_error_code_prefix.py  (executed inside temp repo)
import pathlib

pathlib.Path("errors.py").write_text('''
def format_error(kind: str) -> str:
    \"\"\"Return the internal error code for the given error kind.\"\"\"
    # BUG: uses generic uppercase — correct codes are arbitrary ACME-XXXX strings
    return kind.upper()
''')
"""

_HIDDEN_GATE_HOUSE_ERROR_CODE = """\
from errors import format_error

def test_not_found():
    assert format_error("not_found") == "ACME-4004"

def test_unauthorized():
    assert format_error("unauthorized") == "ACME-4001"

def test_rate_limited():
    assert format_error("rate_limited") == "ACME-4029"
"""

_ONMC_HINT_HOUSE_ERROR_CODE = """\
[ONMC Memory Context]
CONVENTION (house rule — do not infer from HTTP status codes):
  Internal error codes follow the format ACME-XXXX where XXXX is the
  numeric code assigned at project inception.  The mapping is:
    not_found    -> ACME-4004
    unauthorized -> ACME-4001
    rate_limited -> ACME-4029
  These are NOT the same as HTTP status codes (e.g. 404, 401, 429).
  They were assigned in 2021 when ACME prefix was chosen to avoid
  collisions with third-party error namespaces.  All API clients
  pattern-match on the ACME- prefix, so any other format is rejected.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_HOUSE_ERROR_CODE = """\
# API Error Code Conventions

All internal error responses use the ACME-XXXX prefix format.  The ACME prefix
was adopted at project inception to avoid namespace collisions with third-party
error codes.  The four-digit numeric suffix is assigned per error kind and does
NOT correspond to HTTP status codes.

Current error code registry:

  not_found    -> ACME-4004
  unauthorized -> ACME-4001
  rate_limited -> ACME-4029

Do not use HTTP status codes (404, 401, 429) directly as error code strings.
All API clients pattern-match on the ACME- prefix and reject any other format.
The mapping was established in 2021 and must not be changed without migrating
all downstream clients.
"""

TASK_HOUSE_ERROR_CODE_PREFIX = ABTask(
    id="house_error_code_prefix",
    description=(
        "The function `format_error(kind: str) -> str` in errors.py should return "
        "the internal error code for the given error kind.  Fix it so that "
        "`format_error('not_found')` returns the correct code for 'not_found', "
        "`format_error('unauthorized')` returns the correct code for 'unauthorized', "
        "and `format_error('rate_limited')` returns the correct code for 'rate_limited'.  "
        "All tests must pass."
    ),
    setup_script=_SETUP_HOUSE_ERROR_CODE,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_HOUSE_ERROR_CODE,
    onmc_hint=_ONMC_HINT_HOUSE_ERROR_CODE,
    grounding_doc=_GROUNDING_DOC_HOUSE_ERROR_CODE,
    note=(
        "The correct codes (ACME-4004, ACME-4001, ACME-4029) are arbitrary house "
        "conventions with no relationship to standard HTTP status codes.  A cold "
        "agent naturally produces 'NOT_FOUND', '404', or similar generic strings.  "
        "The ONMC hint provides the exact mapping — the ONLY way to know it."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 2: tenant_header — arbitrary X-Acme-Workspace header name
# ---------------------------------------------------------------------------

_SETUP_TENANT_HEADER = """\
# setup_tenant_header.py  (executed inside temp repo)
import pathlib

pathlib.Path("headers.py").write_text('''
def build_headers(token: str, workspace_id: str) -> dict[str, str]:
    \"\"\"Build auth + routing headers for internal API calls.\"\"\"
    return {
        "Authorization": f"Bearer {token}",
        "X-Tenant-ID": workspace_id,  # BUG: gateway only reads X-Acme-Workspace
    }
''')
"""

_HIDDEN_GATE_TENANT_HEADER = """\
from headers import build_headers

def test_acme_workspace_header_present():
    h = build_headers("tok123", "ws-456")
    assert "X-Acme-Workspace" in h, (
        f"Expected X-Acme-Workspace header but got keys: {list(h.keys())}"
    )

def test_acme_workspace_header_value():
    h = build_headers("tok123", "ws-456")
    assert h["X-Acme-Workspace"] == "ws-456"

def test_authorization_header_preserved():
    h = build_headers("tok123", "ws-456")
    assert h["Authorization"] == "Bearer tok123"
"""

_ONMC_HINT_TENANT_HEADER = """\
[ONMC Memory Context]
PAST BUG (incident 2023-Q2): An API integration used X-Tenant-ID to pass
  the workspace identifier.  The internal gateway reads ONLY X-Acme-Workspace
  and silently drops any other header name.  X-Tenant-ID requests reached the
  gateway but were routed to the default workspace, causing data mixing across
  customers for two hours before discovery.

CONVENTION (post-incident — do not use any other header name):
  The correct header is X-Acme-Workspace.  This is not inferrable from HTTP
  conventions — it is an arbitrary internal name chosen to match the gateway's
  hard-coded key.  Always use X-Acme-Workspace, never X-Tenant-ID,
  X-Workspace-Id, X-Workspace, or a query parameter.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_TENANT_HEADER = """\
# Internal Gateway: Authentication and Request Routing

The internal API gateway authenticates tenants from the `X-Acme-Workspace`
header.  This header name was chosen at project inception to match the
gateway's hard-coded routing key.

Requests using any other header — `X-Tenant-ID`, `X-Workspace-Id`,
`X-Workspace`, or a query parameter — are treated as tenant-less and silently
routed to the default workspace.  During the 2023-Q2 incident, a service used
`X-Tenant-ID` instead of `X-Acme-Workspace`.  Requests reached the gateway but
were routed to the default workspace, causing data mixing across customers for
two hours before the bug was found.

Always set `X-Acme-Workspace: <workspace_id>` on all internal API requests.
Never substitute any other header name for workspace routing.
"""

TASK_TENANT_HEADER = ABTask(
    id="tenant_header",
    description=(
        "The function `build_headers(token, workspace_id)` in headers.py should "
        "return a dict with the `Authorization` header and the correct workspace "
        "routing header.  Fix the workspace header name so all tests pass."
    ),
    setup_script=_SETUP_TENANT_HEADER,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_TENANT_HEADER,
    onmc_hint=_ONMC_HINT_TENANT_HEADER,
    grounding_doc=_GROUNDING_DOC_TENANT_HEADER,
    note=(
        "The correct header name (X-Acme-Workspace) is an arbitrary internal "
        "convention — a cold agent naturally picks X-Tenant-ID, X-Workspace-Id, "
        "or a query parameter, all of which the gateway silently drops.  The ONMC "
        "hint names the incident and states the exact header."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 3: retry_only_503_incident — payment client, retry ONLY on 503
# ---------------------------------------------------------------------------

_SETUP_RETRY_ONLY_503 = """\
# setup_retry_only_503_incident.py  (executed inside temp repo)
import pathlib

pathlib.Path("payment.py").write_text('''
def should_retry(status: int) -> bool:
    \"\"\"Return True if the payment client should retry after this HTTP status.\"\"\"
    return 500 <= status < 600  # BUG: retrying all 5xx caused double charges
''')
"""

_HIDDEN_GATE_RETRY_ONLY_503 = """\
from payment import should_retry

def test_503_is_retried():
    assert should_retry(503) is True

def test_500_not_retried():
    # 500 = server error with unknown effect; retrying may double-charge
    assert should_retry(500) is False

def test_502_not_retried():
    assert should_retry(502) is False

def test_504_not_retried():
    assert should_retry(504) is False

def test_200_not_retried():
    assert should_retry(200) is False
"""

_ONMC_HINT_RETRY_ONLY_503 = """\
[ONMC Memory Context]
FAILED_APPROACH (incident 2024-Q1 — do not revert to retrying all 5xx):
  A previous version of the payment client retried all 5xx status codes.
  A 500 response from the payments gateway can mean the charge was applied
  but confirmation was lost in transit.  Retrying caused double charges
  for 3% of failed transactions over 48 hours before rollback.

DECISION (post-incident — enforcement via code review):
  The payment client MUST retry ONLY on status 503 (Service Unavailable).
  503 is the only status the gateway guarantees is idempotent: it fires
  before the charge attempt is initiated.  500, 502, and 504 must NOT be
  retried.  This is an arbitrary hard rule for this payment integration —
  standard retry libraries that retry all 5xx are incorrect here.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_RETRY_ONLY_503 = """\
# Incident Postmortem — 2024-Q1: Payment Double Charges

## Root Cause

The payment client retried all 5xx HTTP status codes.  A 500 response from the
payments gateway can be emitted AFTER the charge has already been applied but
before a confirmation is returned to the caller.  Retrying on 500 caused the
charge to be applied twice, affecting 3% of transactions over a 48-hour window.

## Resolution

The payment client must retry ONLY on HTTP 503 (Service Unavailable).  The
payments gateway guarantees that a 503 fires BEFORE any charge attempt is
initiated, making it the only status code that is safe to retry.

Status codes 500, 502, and 504 must NOT be retried for payment operations.
The charge state after a non-503 5xx is unknown — retrying may double-charge.

This rule is enforced in code review.  Do not revert to retrying all 5xx.
"""

TASK_RETRY_ONLY_503_INCIDENT = ABTask(
    id="retry_only_503_incident",
    description=(
        "The function `should_retry(status: int) -> bool` in payment.py decides "
        "whether the payment client should retry after an HTTP error response.  "
        "Fix it so it passes all tests.  The test expectations "
        "reflect a strict business rule about which status codes are safe to retry."
    ),
    setup_script=_SETUP_RETRY_ONLY_503,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_RETRY_ONLY_503,
    onmc_hint=_ONMC_HINT_RETRY_ONLY_503,
    grounding_doc=_GROUNDING_DOC_RETRY_ONLY_503,
    note=(
        "A cold agent naturally retries all 5xx (the standard practice) — "
        "that is the WRONG answer for this payment client.  Only 503 is safe "
        "to retry; 500/502/504 may have already applied the charge.  This is "
        "an incident-derived rule, not inferrable from conventions."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 4: idempotency_key_format — colon-separated key
# ---------------------------------------------------------------------------

_SETUP_IDEMPOTENCY_KEY = """\
# setup_idempotency_key_format.py  (executed inside temp repo)
import pathlib

pathlib.Path("idem.py").write_text('''
def idempotency_key(tenant: str, op: str, uid: str) -> str:
    \"\"\"Return the idempotency key for a deduplication-protected operation.\"\"\"
    # BUG: uses dash separator; dedup layer splits on colon
    return f"{tenant}-{op}-{uid}"
''')
"""

_HIDDEN_GATE_IDEMPOTENCY_KEY = """\
from idem import idempotency_key

def test_colon_separated_format():
    k = idempotency_key("acme", "charge", "u-123")
    assert k == "acme:charge:u-123", (
        f"Expected colon-separated key but got: {k!r}"
    )

def test_deterministic():
    k1 = idempotency_key("acme", "charge", "u-123")
    k2 = idempotency_key("acme", "charge", "u-123")
    assert k1 == k2

def test_all_three_parts_colon_joined():
    k = idempotency_key("tenant", "op", "id-42")
    parts = k.split(":")
    assert parts == ["tenant", "op", "id-42"], (
        f"Expected exactly three colon-separated parts but got: {parts!r}"
    )
"""

_ONMC_HINT_IDEMPOTENCY_KEY = """\
[ONMC Memory Context]
CONVENTION (dedup service contract — do not use any other separator):
  The internal dedup service parses idempotency keys by splitting on ':'.
  The required format is exactly:  tenant:op:uid
  Any other separator (dash, slash, underscore, hash) is treated as a
  single opaque string — the dedup layer sees it as a unique key on every
  call and provides no deduplication protection.

  This was discovered when a load test used dash-separated keys and every
  request was processed as unique, generating duplicate records.  The
  colon format is not a REST or HTTP convention — it is an internal contract
  with the dedup service documented only in the service's DESIGN.md.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_IDEMPOTENCY_KEY = """\
# Dedup Service — DESIGN.md

## Idempotency Key Format

The deduplication service parses idempotency keys by splitting on the colon
character (`:`) to extract three components: tenant, operation type, and uid.

Required format:  `tenant:op:uid`

Any other separator — dash, slash, underscore, hash — is treated as an opaque
string by the dedup layer.  The service then sees a unique key on every call
and provides no deduplication protection.  A load test discovered this when
dash-separated keys caused every request to be processed as unique, generating
duplicate records in production.

Always construct keys as: `f"{tenant}:{op}:{uid}"`

This format is an internal contract with the dedup service, not a REST or HTTP
convention.  It must not be changed without updating the dedup service parser.
"""

TASK_IDEMPOTENCY_KEY_FORMAT = ABTask(
    id="idempotency_key_format",
    description=(
        "The function `idempotency_key(tenant, op, uid)` in idem.py should return "
        "a string that uniquely identifies an operation for deduplication.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_IDEMPOTENCY_KEY,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_IDEMPOTENCY_KEY,
    onmc_hint=_ONMC_HINT_IDEMPOTENCY_KEY,
    grounding_doc=_GROUNDING_DOC_IDEMPOTENCY_KEY,
    note=(
        "The required separator (':') is an arbitrary dedup-service contract.  "
        "A cold agent naturally picks a dash (f-string with '-'), or a UUID, "
        "or a hash.  The colon format is knowable only from the service's "
        "DESIGN.md or a past incident — the ONMC hint provides it."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 5: money_minor_units — Decimal paise conversion, never float
# ---------------------------------------------------------------------------

_SETUP_MONEY_MINOR_UNITS = """\
# setup_money_minor_units.py  (executed inside temp repo)
import pathlib

pathlib.Path("money.py").write_text('''
def to_paise(rupees: str) -> int:
    \"\"\"Convert a rupee decimal string to integer paise (1 INR = 100 paise).\"\"\"
    # BUG: float arithmetic rounds incorrectly
    # e.g. int(float("2.30") * 100) == 229 due to IEEE 754 representation
    return int(float(rupees) * 100)
''')
"""

_HIDDEN_GATE_MONEY_MINOR_UNITS = """\
from decimal import Decimal
from money import to_paise

def test_basic():
    assert to_paise("10.00") == 1000

def test_one_ten():
    assert to_paise("1.10") == 110

def test_float_trap():
    # float("2.30") * 100 == 229.99999... -> int gives 229, NOT 230
    assert to_paise("2.30") == 230, (
        f"Expected 230 but got {to_paise('2.30')} — "
        "float arithmetic truncates 2.30*100 to 229"
    )

def test_returns_int():
    result = to_paise("10.00")
    assert isinstance(result, int), (
        f"to_paise must return int, got {type(result).__name__}"
    )

def test_not_float_type():
    result = to_paise("10.00")
    assert not isinstance(result, float), "to_paise must not return a float"
"""

_ONMC_HINT_MONEY_MINOR_UNITS = """\
[ONMC Memory Context]
DECISION (post-incident, 2023-Q3 — enforced by code review):
  All money amounts in this codebase MUST be converted to integer minor units
  (paise for INR, cents for USD) via the decimal module.  Float arithmetic
  is forbidden for monetary values.

  Incident: a float-based conversion silently truncated 2.30 rupees to
  229 paise (int(float("2.30") * 100) evaluates to 229 due to IEEE 754
  representation of 2.3).  Similar truncation affects 0.57, 19.99, and
  other common amounts.  This caused underpayments for months before detection.

CORRECT PATTERN:
    from decimal import Decimal
    return int(Decimal(rupees) * 100)
  Pass the raw string directly to Decimal (do NOT convert to float first).
  Decimal("2.30") * 100 == Decimal("230.00") -> int gives 230.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_MONEY_MINOR_UNITS = """\
# Financial Arithmetic Guidelines

## Minor Unit Conversion

All monetary amounts must be converted to integer minor units (paise for INR,
cents for USD) using Python's `decimal` module.  Float arithmetic is forbidden
for any monetary conversion in this codebase.

Background: the float-based pattern `int(float(rupees) * 100)` silently
truncates certain amounts.  For example, `float("2.30") * 100` evaluates to
`229.9999999999999...` due to IEEE 754 binary representation, so `int()` gives
229 instead of 230.  The same truncation affects 0.57, 19.99, and many other
common amounts.  This caused systematic underpayments over several months
before the 2023-Q3 incident was detected.

Correct conversion pattern:

    from decimal import Decimal
    return int(Decimal(rupees) * 100)

Always pass the raw string directly to `Decimal`.  Never convert to float
first.  `Decimal("2.30") * 100` evaluates exactly to `Decimal("230.00")`,
which `int()` gives as 230.
"""

TASK_MONEY_MINOR_UNITS = ABTask(
    id="money_minor_units",
    description=(
        "The function `to_paise(rupees: str) -> int` in money.py converts a rupee "
        "decimal string to integer paise (100 paise = 1 rupee).  It currently uses "
        "float arithmetic which produces wrong results for certain inputs.  "
        "Fix it so all tests pass and the function returns an int."
    ),
    setup_script=_SETUP_MONEY_MINOR_UNITS,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_MONEY_MINOR_UNITS,
    onmc_hint=_ONMC_HINT_MONEY_MINOR_UNITS,
    grounding_doc=_GROUNDING_DOC_MONEY_MINOR_UNITS,
    note=(
        "Float-to-paise rounding trap.  A cold agent's natural fix "
        "(int(float(rupees) * 100)) silently truncates 2.30*100 to 229.  "
        "The ONMC hint names the incident and mandates Decimal(rupees) * 100, "
        "the ONLY portable correct approach for this codebase."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Full private-knowledge task suite
# ---------------------------------------------------------------------------

PRIVATE_KNOWLEDGE_TASKS: list[ABTask] = [
    TASK_HOUSE_ERROR_CODE_PREFIX,
    TASK_TENANT_HEADER,
    TASK_RETRY_ONLY_503_INCIDENT,
    TASK_IDEMPOTENCY_KEY_FORMAT,
    TASK_MONEY_MINOR_UNITS,
]
