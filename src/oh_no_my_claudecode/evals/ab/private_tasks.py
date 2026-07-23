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
- CRITICAL: setup_script and description must contain ZERO clue to the
  correct answer.  Comments naming the correct value, docstrings stating the
  rule, or hint-y variable names are forbidden.

Tasks in this suite
-------------------
 1. house_error_code_prefix    — arbitrary ACME-XXXX error codes (un-inferrable)
 2. tenant_header               — arbitrary header name X-Acme-Workspace (incident)
 3. retry_only_503_incident     — payment double-charge incident dead-end
 4. idempotency_key_format      — colon-separated key the dedup layer parses
 5. money_minor_units           — Decimal-only paise conversion (float-rounding incident)
 6. epoch_millis_timestamp      — timestamps must be epoch-millisecond strings
 7. pagination_cursor_scheme    — cursor uses tilde separator, not plain page number
 8. audit_log_schema_version    — every audit payload requires a _schema field
 9. currency_allowlist          — hard three-currency allowlist rejects others
10. webhook_signature_header    — specific header name and value format for signed webhooks
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
        "`format_error('not_found')`, `format_error('unauthorized')`, and "
        "`format_error('rate_limited')` each return the correct internal code.  "
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
        "X-Tenant-ID": workspace_id,
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
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("payment.py").write_text('''
def should_retry(status: int) -> bool:
    \"\"\"Return True if the payment client should retry after this HTTP status.\"\"\"
    return 500 <= status < 600
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
        "decimal string to integer paise (100 paise = 1 rupee).  "
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
# Task 6: epoch_millis_timestamp — timestamps must be epoch-millisecond strings
# ---------------------------------------------------------------------------

_SETUP_EPOCH_MILLIS = """\
# setup_epoch_millis_timestamp.py  (executed inside temp repo)
import pathlib

pathlib.Path("timestamps.py").write_text('''
import datetime

def format_timestamp(dt: datetime.datetime) -> str:
    \"\"\"Return a string representation of the datetime for use in API payloads.\"\"\"
    return dt.isoformat()
''')
"""

_HIDDEN_GATE_EPOCH_MILLIS = """\
import datetime
from timestamps import format_timestamp

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

def _dt(year: int, month: int, day: int) -> datetime.datetime:
    return datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc)

def test_returns_string():
    result = format_timestamp(_dt(2024, 1, 1))
    assert isinstance(result, str), f"Expected str, got {type(result).__name__}"

def test_epoch_millis_2024_01_01():
    dt = _dt(2024, 1, 1)
    expected = str(int(dt.timestamp() * 1000))
    assert format_timestamp(dt) == expected, (
        f"Expected epoch-ms string {expected!r} but got {format_timestamp(dt)!r}"
    )

def test_epoch_millis_1970_01_01():
    dt = _EPOCH
    assert format_timestamp(dt) == "0", (
        f"Unix epoch should format to '0' but got {format_timestamp(dt)!r}"
    )

def test_not_iso_format():
    dt = _dt(2024, 6, 15)
    result = format_timestamp(dt)
    assert "T" not in result and "-" not in result[1:], (
        f"Result looks like ISO format rather than epoch ms: {result!r}"
    )
"""

_ONMC_HINT_EPOCH_MILLIS = """\
[ONMC Memory Context]
CONVENTION (API timestamp contract — do not use ISO 8601 strings):
  All timestamps in API payloads MUST be formatted as epoch milliseconds
  expressed as a plain string (i.e. str(int(dt.timestamp() * 1000))).
  ISO 8601 strings (e.g. "2024-01-01T00:00:00") are forbidden in API
  responses — the mobile client's date parser expects the numeric-string
  format and fails silently on ISO strings.

  This was discovered in a 2023-Q4 incident when a new endpoint returned
  ISO timestamps.  The iOS client parsed them as zero and displayed
  "Jan 1, 1970" for all event dates for two days before rollback.

CORRECT PATTERN:
    return str(int(dt.timestamp() * 1000))
  Pass a timezone-aware datetime to avoid platform-dependent local-time
  offsets.  The result is always a numeric string — no letters, no hyphens.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_EPOCH_MILLIS = """\
# API Timestamp Format Convention

All timestamps returned by internal APIs must be formatted as epoch
milliseconds expressed as a plain string.

Required format:  `str(int(dt.timestamp() * 1000))`

Example: `datetime(2024, 1, 1, tzinfo=timezone.utc)` formats to `"1704067200000"`.

ISO 8601 strings are forbidden in API payloads.  The mobile client's date
parser expects a numeric string and fails silently when it receives an ISO
format — it parses the value as zero and displays "Jan 1, 1970".  This caused
a 2023-Q4 incident lasting two days before rollback.

Always use a timezone-aware datetime to avoid local-time offset bugs.
The Unix epoch (1970-01-01T00:00:00Z) must format to the string `"0"`.
"""

TASK_EPOCH_MILLIS_TIMESTAMP = ABTask(
    id="epoch_millis_timestamp",
    description=(
        "The function `format_timestamp(dt: datetime.datetime) -> str` in timestamps.py "
        "returns a string representation of a datetime for use in API payloads.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_EPOCH_MILLIS,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_EPOCH_MILLIS,
    onmc_hint=_ONMC_HINT_EPOCH_MILLIS,
    grounding_doc=_GROUNDING_DOC_EPOCH_MILLIS,
    note=(
        "ISO 8601 is the obvious, sensible default for any competent developer.  "
        "The internal mobile client's parser requires epoch-milliseconds-as-string "
        "— an arbitrary format with no standard library analog.  The ONMC hint "
        "names the incident and gives the exact pattern."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 7: pagination_cursor_scheme — tilde-separated cursor (page~watermark)
# ---------------------------------------------------------------------------

_SETUP_PAGINATION_CURSOR = """\
# setup_pagination_cursor_scheme.py  (executed inside temp repo)
import pathlib

pathlib.Path("pagination.py").write_text('''
def make_cursor(page: int, watermark: int) -> str:
    \"\"\"Return the opaque pagination cursor for the next page of results.\"\"\"
    return str(page)
''')
"""

_HIDDEN_GATE_PAGINATION_CURSOR = """\
from pagination import make_cursor

def test_cursor_contains_both_parts():
    cursor = make_cursor(3, 1700000000)
    assert "3" in cursor and "1700000000" in cursor, (
        f"Cursor must encode both page and watermark but got: {cursor!r}"
    )

def test_tilde_separator():
    cursor = make_cursor(2, 9999)
    assert cursor == "2~9999", (
        f"Expected tilde-separated cursor '2~9999' but got: {cursor!r}"
    )

def test_page_one():
    cursor = make_cursor(1, 0)
    assert cursor == "1~0", f"Expected '1~0' but got {cursor!r}"

def test_deterministic():
    assert make_cursor(5, 12345) == make_cursor(5, 12345)
"""

_ONMC_HINT_PAGINATION_CURSOR = """\
[ONMC Memory Context]
CONVENTION (cursor service contract — internal format, not a standard):
  The internal pagination cursor parser splits on '~' (tilde) to extract
  the page number and the watermark timestamp.  The required format is:
    "{page}~{watermark}"
  Any other format — a plain page number, a dash-separated pair, a
  base64 blob — is rejected by the cursor decoder with a 400 error.

  This was chosen in 2022 to avoid ambiguity: dashes appear in UUIDs
  used as watermarks, underscores appear in field names, and colons are
  reserved for the idempotency key format.  Tilde was the only safe
  single-character separator not otherwise used in our data.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_PAGINATION_CURSOR = """\
# Pagination Service — Cursor Format

## Cursor Encoding

The internal pagination cursor must encode two integers: the page number and
the watermark (a Unix timestamp or record ID).  The required format is:

    "{page}~{watermark}"

The cursor parser splits on the tilde character (`~`).  Any other format —
a plain integer, a dash-separated pair, a base64 blob — causes a 400 error
from the cursor decoder.

The tilde separator was chosen in 2022 to avoid ambiguity: dashes appear in
UUIDs used as watermarks, underscores appear in field names, and colons are
reserved for the idempotency key format elsewhere in the system.  Tilde is the
only safe single-character separator not otherwise used in our data.

Always construct cursors as: `f"{page}~{watermark}"`
"""

TASK_PAGINATION_CURSOR_SCHEME = ABTask(
    id="pagination_cursor_scheme",
    description=(
        "The function `make_cursor(page, watermark)` in pagination.py should return "
        "an opaque string cursor encoding both the page number and the watermark "
        "for use by the pagination service.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_PAGINATION_CURSOR,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_PAGINATION_CURSOR,
    onmc_hint=_ONMC_HINT_PAGINATION_CURSOR,
    grounding_doc=_GROUNDING_DOC_PAGINATION_CURSOR,
    note=(
        "A cold agent returns `str(page)` or uses a dash or underscore separator, "
        "all of which the cursor parser rejects.  The tilde format is an arbitrary "
        "internal contract — no convention suggests it.  The ONMC hint names the "
        "format and the reason it was chosen."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 8: audit_log_schema_version — every audit payload requires _schema field
# ---------------------------------------------------------------------------

_SETUP_AUDIT_LOG = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("audit.py").write_text('''
import time

def build_audit_payload(action: str, user_id: str) -> dict:
    \"\"\"Return the audit log payload for a user action.\"\"\"
    return {
        "action": action,
        "user_id": user_id,
        "ts": int(time.time()),
    }
''')
"""

_HIDDEN_GATE_AUDIT_LOG = """\
from audit import build_audit_payload

def test_schema_field_present():
    payload = build_audit_payload("login", "u-001")
    assert "_schema" in payload, (
        f"Payload missing required '_schema' field.  Got keys: {list(payload.keys())}"
    )

def test_schema_field_value():
    payload = build_audit_payload("login", "u-001")
    assert payload["_schema"] == "audit.v2", (
        f"Expected '_schema' == 'audit.v2' but got: {payload['_schema']!r}"
    )

def test_action_and_user_preserved():
    payload = build_audit_payload("logout", "u-999")
    assert payload["action"] == "logout"
    assert payload["user_id"] == "u-999"

def test_ts_is_integer():
    payload = build_audit_payload("login", "u-001")
    assert "ts" in payload
    assert isinstance(payload["ts"], int)
"""

_ONMC_HINT_AUDIT_LOG = """\
[ONMC Memory Context]
CONVENTION (audit pipeline contract — do not omit this field):
  Every audit log payload MUST include the field:
    "_schema": "audit.v2"
  The audit pipeline's schema validator rejects payloads without this field
  or with any other value (e.g. "v2", "audit.v1", "audit_v2").  Rejected
  payloads are silently dropped — they never reach the compliance store.

  The underscore-prefixed key was chosen to avoid collision with
  domain-specific "schema" fields.  The version string "audit.v2" was
  frozen after a 2022 migration; "audit.v1" payloads are no longer accepted.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_AUDIT_LOG = """\
# Audit Pipeline — Payload Schema

## Required Field: _schema

Every audit log payload submitted to the audit pipeline must include the
field `"_schema": "audit.v2"`.

The pipeline's schema validator checks for this field before writing to the
compliance store.  Payloads missing the field, or with any other value
(e.g. `"v2"`, `"audit.v1"`, `"audit_v2"`), are silently rejected and never
reach the compliance store.

The underscore-prefixed key avoids collision with domain-specific `"schema"`
fields that some services already use.  The version string `"audit.v2"` was
frozen after a 2022 schema migration.  Do not use `"audit.v1"` — the pipeline
no longer accepts it.

Minimum valid payload structure:

    {
      "_schema": "audit.v2",
      "action": "<action>",
      "user_id": "<user_id>",
      "ts": <unix_timestamp_int>
    }
"""

TASK_AUDIT_LOG_SCHEMA_VERSION = ABTask(
    id="audit_log_schema_version",
    description=(
        "The function `build_audit_payload(action, user_id)` in audit.py should return "
        "a dict representing an audit log event.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_AUDIT_LOG,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_AUDIT_LOG,
    onmc_hint=_ONMC_HINT_AUDIT_LOG,
    grounding_doc=_GROUNDING_DOC_AUDIT_LOG,
    note=(
        "A cold agent writes a plausible payload with action/user_id/ts but omits "
        "the required '_schema' field — it has no way to know the exact key and "
        "value 'audit.v2'.  The ONMC hint names the contract and the frozen version "
        "string.  Without the hint, even the correct field name is un-inferrable."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 9: currency_allowlist — hard three-currency allowlist
# ---------------------------------------------------------------------------

_SETUP_CURRENCY_ALLOWLIST = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("currency.py").write_text('''
def validate_currency(code: str) -> str:
    \"\"\"Validate and return a currency code for payment processing.\"\"\"
    if not (len(code) == 3 and code.isalpha() and code.isupper()):
        raise ValueError(f"Invalid currency format: {code!r}")
    return code
''')
"""

_HIDDEN_GATE_CURRENCY_ALLOWLIST = """\
import pytest
from currency import validate_currency

def test_inr_accepted():
    assert validate_currency("INR") == "INR"

def test_usd_accepted():
    assert validate_currency("USD") == "USD"

def test_sgd_accepted():
    assert validate_currency("SGD") == "SGD"

def test_gbp_rejected():
    with pytest.raises(ValueError):
        validate_currency("GBP")

def test_eur_rejected():
    with pytest.raises(ValueError):
        validate_currency("EUR")

def test_jpy_rejected():
    with pytest.raises(ValueError):
        validate_currency("JPY")

def test_lowercase_rejected():
    with pytest.raises(ValueError):
        validate_currency("usd")
"""

_ONMC_HINT_CURRENCY_ALLOWLIST = """\
[ONMC Memory Context]
CONVENTION (payment service hard allowlist — do not add currencies without ops sign-off):
  The payment service supports ONLY three currency codes: INR, USD, SGD.
  Any other ISO 4217 code — including GBP, EUR, JPY, AUD — must raise
  ValueError("unsupported_currency").  This is NOT a format check; it is a
  hard operational allowlist.

  The allowlist is frozen at INR/USD/SGD because the payment gateway has
  licensed settlement accounts only for these three currencies.  A 2023
  incident attempted to process GBP transactions; they cleared locally but
  failed at settlement, causing a 72-hour reconciliation backlog.

CORRECT PATTERN:
    _ALLOWED = {"INR", "USD", "SGD"}
    if code not in _ALLOWED:
        raise ValueError(f"unsupported_currency: {code!r}")
    return code
[/ONMC Memory Context]

"""

_GROUNDING_DOC_CURRENCY_ALLOWLIST = """\
# Payment Service — Currency Allowlist

## Supported Currencies

The payment service accepts ONLY the following three currency codes:

    INR   (Indian Rupee)
    USD   (US Dollar)
    SGD   (Singapore Dollar)

Any other ISO 4217 code — including GBP, EUR, JPY, AUD — must be rejected
with `ValueError`.  This is a hard operational allowlist, not a format
validation rule.

Background: the payment gateway has licensed settlement accounts only for
INR, USD, and SGD.  A 2023 incident passed GBP transactions through local
validation.  The transactions cleared locally but failed at the gateway's
settlement step, causing a 72-hour reconciliation backlog.

After the incident, the allowlist was encoded in the validation layer so that
unsupported currencies are rejected before they reach the gateway.

Do not add currencies to the allowlist without explicit ops sign-off and a
gateway settlement account for that currency.
"""

TASK_CURRENCY_ALLOWLIST = ABTask(
    id="currency_allowlist",
    description=(
        "The function `validate_currency(code: str) -> str` in currency.py validates "
        "a currency code for payment processing and returns it if valid, or raises "
        "`ValueError` if not.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_CURRENCY_ALLOWLIST,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_CURRENCY_ALLOWLIST,
    onmc_hint=_ONMC_HINT_CURRENCY_ALLOWLIST,
    grounding_doc=_GROUNDING_DOC_CURRENCY_ALLOWLIST,
    note=(
        "A cold agent writes a format validator (3-letter uppercase) that passes "
        "GBP, EUR, JPY, etc. — all of which the hidden gate rejects.  The allowlist "
        "{INR, USD, SGD} is an arbitrary operational constraint the agent cannot "
        "infer.  SGD's inclusion alongside GBP's exclusion is especially "
        "un-inferrable without the incident context."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 10: webhook_signature_header — specific header name and value format
# ---------------------------------------------------------------------------

_SETUP_WEBHOOK_SIGNATURE = """\
# setup_webhook_signature_header.py  (executed inside temp repo)
import pathlib

pathlib.Path("webhook.py").write_text('''
import hashlib
import hmac

def build_webhook_headers(payload: bytes, secret: str) -> dict[str, str]:
    \"\"\"Return the headers for a signed outbound webhook delivery.\"\"\"
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Signature": sig,
    }
''')
"""

_HIDDEN_GATE_WEBHOOK_SIGNATURE = """\
import hashlib
import hmac
from webhook import build_webhook_headers

_SECRET = "s3cr3t"
_BODY = b'{"event": "payment.completed"}'
_EXPECTED_HEX = hmac.new(_SECRET.encode(), _BODY, hashlib.sha256).hexdigest()

def test_correct_header_name_present():
    headers = build_webhook_headers(_BODY, _SECRET)
    assert "X-Acme-Hook-Sig" in headers, (
        f"Expected header 'X-Acme-Hook-Sig' but got keys: {list(headers.keys())}"
    )

def test_wrong_header_absent():
    headers = build_webhook_headers(_BODY, _SECRET)
    assert "X-Signature" not in headers, (
        "Found disallowed 'X-Signature' header — must use 'X-Acme-Hook-Sig'"
    )

def test_value_has_sha256_prefix():
    headers = build_webhook_headers(_BODY, _SECRET)
    val = headers["X-Acme-Hook-Sig"]
    assert val.startswith("sha256="), (
        f"Header value must start with 'sha256=' but got: {val!r}"
    )

def test_value_contains_correct_hex():
    headers = build_webhook_headers(_BODY, _SECRET)
    val = headers["X-Acme-Hook-Sig"]
    assert val == f"sha256={_EXPECTED_HEX}", (
        f"Expected 'sha256={_EXPECTED_HEX}' but got {val!r}"
    )

def test_content_type_preserved():
    headers = build_webhook_headers(_BODY, _SECRET)
    assert headers.get("Content-Type") == "application/json"
"""

_ONMC_HINT_WEBHOOK_SIGNATURE = """\
[ONMC Memory Context]
CONVENTION (webhook delivery contract — do not use generic X-Signature):
  Outbound webhooks must carry the signature in the header named exactly:
    X-Acme-Hook-Sig
  The value format is: sha256={hex_digest}
  where hex_digest is the HMAC-SHA-256 of the raw payload body, keyed on
  the per-endpoint webhook secret.

  The header name X-Signature is rejected by the receiver's validation
  middleware — it checks for the exact string "X-Acme-Hook-Sig".  The
  sha256= prefix is also mandatory; a bare hex digest is treated as
  invalid and the delivery is retried indefinitely.

  This format mirrors the GitHub webhook signature convention, but the
  header NAME is our internal name — not "X-Hub-Signature-256".
[/ONMC Memory Context]

"""

_GROUNDING_DOC_WEBHOOK_SIGNATURE = """\
# Webhook Delivery — Signature Format

## Required Header

All outbound webhook deliveries must include the following header:

    X-Acme-Hook-Sig: sha256=<hex_digest>

where `<hex_digest>` is the lowercase hexadecimal HMAC-SHA-256 of the raw
request body, computed with the per-endpoint webhook secret as the key.

The receiver's validation middleware checks for the header named exactly
`X-Acme-Hook-Sig`.  Any other header name — `X-Signature`, `X-Hub-Signature`,
`X-Webhook-Sig` — is not recognised and the delivery is rejected.

The `sha256=` prefix in the value is mandatory.  A bare hex digest without
the prefix is treated as an invalid signature and triggers indefinite retries.

This format follows the GitHub webhook signature convention for the value
format, but uses our internal header name `X-Acme-Hook-Sig` rather than
GitHub's `X-Hub-Signature-256`.
"""

TASK_WEBHOOK_SIGNATURE_HEADER = ABTask(
    id="webhook_signature_header",
    description=(
        "The function `build_webhook_headers(payload, secret)` in webhook.py should "
        "return the headers required for a signed outbound webhook delivery.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_WEBHOOK_SIGNATURE,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_WEBHOOK_SIGNATURE,
    onmc_hint=_ONMC_HINT_WEBHOOK_SIGNATURE,
    grounding_doc=_GROUNDING_DOC_WEBHOOK_SIGNATURE,
    note=(
        "A cold agent uses X-Signature with a bare hex digest — both wrong.  "
        "The correct header name (X-Acme-Hook-Sig) and value format (sha256=hex) "
        "are an internal convention.  Even an agent that knows GitHub webhook "
        "format would guess X-Hub-Signature-256.  The ONMC hint names both the "
        "header and the required prefix."
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
    TASK_EPOCH_MILLIS_TIMESTAMP,
    TASK_PAGINATION_CURSOR_SCHEME,
    TASK_AUDIT_LOG_SCHEMA_VERSION,
    TASK_CURRENCY_ALLOWLIST,
    TASK_WEBHOOK_SIGNATURE_HEADER,
]
