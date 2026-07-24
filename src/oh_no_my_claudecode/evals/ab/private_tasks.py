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
 1. house_error_code_prefix       — arbitrary ACME-XXXX error codes (un-inferrable)
 2. tenant_header                  — arbitrary header name X-Acme-Workspace (incident)
 3. retry_only_503_incident        — payment double-charge incident dead-end
 4. idempotency_key_format         — colon-separated key the dedup layer parses
 5. money_minor_units              — Decimal-only paise conversion (float-rounding incident)
 6. epoch_millis_timestamp         — timestamps must be epoch-millisecond strings
 7. pagination_cursor_scheme       — cursor uses tilde separator, not plain page number
 8. audit_log_schema_version       — every audit payload requires a _schema field
 9. currency_allowlist             — hard three-currency allowlist rejects others
10. webhook_signature_header       — specific header name and value format for signed webhooks
11. api_response_envelope          — response wrapper requires _ok key (arbitrary internal)
12. service_version_header         — X-Acme-Svc-Ver header with service/version value format
13. event_schema_version           — domain events require _ev: "2.1" meta key
14. validation_field_path          — validation errors use field_path key, not field
15. payment_ref_separator          — payment references use pipe separator, not dash
16. refund_credit_flag             — refunds encoded as positive amount with is_credit flag
17. fx_rate_precision              — FX rates stored to 8 decimal places (not 4)
18. tz_offset_compact_format       — timezone offsets as +HHMM (no UTC prefix, no colon)
19. duration_microseconds          — profiler durations in microseconds, not milliseconds
20. pagination_total_key           — total count key is total_count (not total or count)
21. cursor_base64url_no_padding    — cursors base64url-encoded without padding characters
22. log_context_key                — structured logs use log_ctx field, not context
23. audit_actor_prefix             — audit actor field is user:{id} (colon-prefixed)
24. feature_flag_env_prefix        — feature flag env vars start with FF_ (two F's)
25. config_secret_scope            — secret config keys prefixed sec: (not SECRET_)
26. jwt_edDSA_only                 — only EdDSA algorithm permitted for JWT signing
27. request_nonce_header           — signed requests need X-Acme-Nonce header (not X-Nonce)
28. migration_file_prefix          — migrations use M{YYYYMMDD}{seq:03d}__ format (not V1__)
29. db_null_sentinel               — JSON column NULLs stored as "__NULL__" sentinel string
30. batch_max_fifty                — batch endpoint validates max 50 items (not 100)
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
# Task 11: api_response_envelope — internal response wrapper with _ok key
# ---------------------------------------------------------------------------

_SETUP_API_RESPONSE_ENVELOPE = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("api.py").write_text('''
def wrap_response(data: object) -> dict:
    \"\"\"Wrap a result value in the internal API response envelope.\"\"\"
    return {"result": data}
''')
"""

_HIDDEN_GATE_API_RESPONSE_ENVELOPE = """\
from api import wrap_response

def test_ok_flag_present():
    r = wrap_response({"id": 1})
    assert "_ok" in r, (
        f"Response envelope missing '_ok' flag.  Got keys: {list(r.keys())}"
    )

def test_ok_flag_is_true():
    r = wrap_response({"id": 1})
    assert r["_ok"] is True, f"Expected _ok=True but got {r['_ok']!r}"

def test_data_key_present():
    r = wrap_response({"id": 1})
    assert "data" in r, f"Expected 'data' key but got: {list(r.keys())}"

def test_data_key_value():
    payload = {"id": 42, "name": "test"}
    r = wrap_response(payload)
    assert r["data"] == payload

def test_result_key_absent():
    r = wrap_response(None)
    assert "result" not in r, "Old 'result' key must be replaced by 'data'"
"""

_ONMC_HINT_API_RESPONSE_ENVELOPE = """\
[ONMC Memory Context]
CONVENTION (internal API contract — do not use any other envelope format):
  All internal service responses MUST be wrapped in the following envelope:
    {"data": <payload>, "_ok": True}
  The underscore-prefixed "_ok" flag is the liveness sentinel the API
  gateway uses to distinguish successful responses from error envelopes.
  Using "result", "response", "body", or "payload" as the outer key causes
  the gateway to treat the response as malformed and return a 502.
  Using "ok" (without the underscore) is similarly rejected — the sentinel
  key is exactly "_ok".  This was chosen in 2022 to avoid collision with
  domain-specific "ok" fields that some services already returned.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_API_RESPONSE_ENVELOPE = """\
# Internal API Gateway — Response Envelope Contract

## Required Envelope Format

Every internal service response MUST be wrapped in the following envelope:

    {"data": <payload>, "_ok": True}

The `"_ok"` key (underscore-prefixed boolean) is the liveness sentinel.
The API gateway checks for this exact key to confirm a response is from a
healthy handler — its absence or any other key name causes a 502 error.

The `"data"` key holds the response payload.  Any other outer key name —
`"result"`, `"response"`, `"body"`, `"payload"` — causes the gateway to
reject the response as malformed.

History: the underscore prefix was added in 2022 to avoid collisions with
domain-specific `"ok"` fields that several services were already returning.
The plain `"ok"` key (without underscore) is therefore also rejected.
"""

TASK_API_RESPONSE_ENVELOPE = ABTask(
    id="api_response_envelope",
    description=(
        "The function `wrap_response(data: object) -> dict` in api.py should return "
        "the internal API response envelope around the given data payload.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_API_RESPONSE_ENVELOPE,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_API_RESPONSE_ENVELOPE,
    onmc_hint=_ONMC_HINT_API_RESPONSE_ENVELOPE,
    grounding_doc=_GROUNDING_DOC_API_RESPONSE_ENVELOPE,
    note=(
        "A cold agent returns {'result': data} or {'data': data, 'ok': True} — "
        "neither satisfies the gate because the sentinel key is '_ok' (underscore "
        "prefix), not 'ok'.  The exact key is an arbitrary 2022 convention with "
        "no standard precedent.  The ONMC hint names both the key and the reason."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 12: service_version_header — X-Acme-Svc-Ver with service/version value
# ---------------------------------------------------------------------------

_SETUP_SERVICE_VERSION_HEADER = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("svc_headers.py").write_text('''
def make_service_headers(service: str, version: str) -> dict[str, str]:
    \"\"\"Return the headers for an outbound inter-service call.\"\"\"
    return {
        "X-Service-Version": version,
    }
''')
"""

_HIDDEN_GATE_SERVICE_VERSION_HEADER = """\
from svc_headers import make_service_headers

def test_correct_header_name():
    h = make_service_headers("billing", "1.2.3")
    assert "X-Acme-Svc-Ver" in h, (
        f"Expected 'X-Acme-Svc-Ver' header but got keys: {list(h.keys())}"
    )

def test_wrong_header_absent():
    h = make_service_headers("billing", "1.2.3")
    assert "X-Service-Version" not in h, (
        "Disallowed 'X-Service-Version' found — must use 'X-Acme-Svc-Ver'"
    )

def test_header_value_format():
    h = make_service_headers("billing", "1.2.3")
    assert h["X-Acme-Svc-Ver"] == "billing/1.2.3", (
        f"Expected 'billing/1.2.3' but got {h['X-Acme-Svc-Ver']!r}"
    )

def test_different_service():
    h = make_service_headers("payments", "2.0.0")
    assert h["X-Acme-Svc-Ver"] == "payments/2.0.0"
"""

_ONMC_HINT_SERVICE_VERSION_HEADER = """\
[ONMC Memory Context]
CONVENTION (service mesh telemetry contract — do not use any other header):
  Outbound inter-service calls MUST include the header:
    X-Acme-Svc-Ver: {service_name}/{version}
  For example: "X-Acme-Svc-Ver: billing/1.2.3"
  The service mesh reads this header for routing telemetry and canary
  traffic splitting.  Any other header name (X-Service-Version, X-Version,
  X-Svc-Ver) is silently ignored.  Omitting it means canary rollouts cannot
  target this service, causing all traffic to fall to stable.
  The slash-separated "{service}/{version}" value format was chosen in 2023
  to allow a single header parse instead of two separate headers.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_SERVICE_VERSION_HEADER = """\
# Service Mesh — Version Telemetry Header

## Required Header

All outbound inter-service HTTP calls must include:

    X-Acme-Svc-Ver: {service_name}/{version}

Example: `X-Acme-Svc-Ver: billing/1.2.3`

The service mesh reads this header for routing telemetry and canary traffic
splitting.  Any other header name — `X-Service-Version`, `X-Version`,
`X-Svc-Ver` — is not recognised and the header is silently dropped.

The value format combines service name and version with a single slash.
This was chosen in 2023 to allow the mesh to extract both fields with one
header parse instead of requiring two separate headers.  Do not use other
separators (colon, underscore, dash) — the mesh parser splits on the first
slash only.
"""

TASK_SERVICE_VERSION_HEADER = ABTask(
    id="service_version_header",
    description=(
        "The function `make_service_headers(service, version)` in svc_headers.py should "
        "return the headers dict for outbound inter-service HTTP calls.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_SERVICE_VERSION_HEADER,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_SERVICE_VERSION_HEADER,
    onmc_hint=_ONMC_HINT_SERVICE_VERSION_HEADER,
    grounding_doc=_GROUNDING_DOC_SERVICE_VERSION_HEADER,
    note=(
        "A cold agent uses 'X-Service-Version' (or 'X-Version') with just the version "
        "string as the value.  The correct header is 'X-Acme-Svc-Ver' with a "
        "'service/version' combined value — both the header name and value format are "
        "arbitrary internal conventions.  The ONMC hint names both."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 13: event_schema_version — domain events require _ev: "2.1" meta key
# ---------------------------------------------------------------------------

_SETUP_EVENT_SCHEMA_VERSION = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("events.py").write_text('''
def make_event(event_type: str, payload: dict) -> dict:
    \"\"\"Build a domain event payload for publishing to the event bus.\"\"\"
    return {
        "type": event_type,
        "payload": payload,
    }
''')
"""

_HIDDEN_GATE_EVENT_SCHEMA_VERSION = """\
from events import make_event

def test_ev_meta_key_present():
    ev = make_event("order.created", {"id": 42})
    assert "_ev" in ev, (
        f"Event missing required '_ev' meta key.  Got keys: {list(ev.keys())}"
    )

def test_ev_meta_value():
    ev = make_event("order.created", {"id": 42})
    assert ev["_ev"] == "2.1", (
        f"Expected '_ev' == '2.1' but got: {ev['_ev']!r}"
    )

def test_type_field_preserved():
    ev = make_event("user.deleted", {"user_id": "u-001"})
    assert ev["type"] == "user.deleted"

def test_payload_field_preserved():
    payload = {"amount": 5000, "currency": "INR"}
    ev = make_event("payment.completed", payload)
    assert ev["payload"] == payload
"""

_ONMC_HINT_EVENT_SCHEMA_VERSION = """\
[ONMC Memory Context]
CONVENTION (event bus contract — do not omit this key):
  Every domain event published to the internal event bus MUST include the
  meta key "_ev" with the current schema version string "2.1".  The event
  router uses this key to select the correct deserializer.  Events missing
  "_ev", or with any other value ("1.0", "2.0", "v2", "2"), are routed to
  the dead-letter queue and never reach subscribers.

  The version was bumped from "2.0" to "2.1" in the 2024-Q1 schema migration
  when the payload envelope gained the nested "payload" field.  "2.0" events
  are no longer accepted.  "1.0" was the pre-migration format — completely
  incompatible.  The decimal format "2.1" (not "v2.1" or "2_1") is required
  because the router does a string equality check, not a semver parse.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_EVENT_SCHEMA_VERSION = """\
# Event Bus — Domain Event Schema

## Required Meta Key: _ev

Every domain event payload must include the meta key `"_ev"` with the value
`"2.1"` (string).  The event router uses this key to select the deserializer.

Events missing `"_ev"`, or with any value other than `"2.1"`, are routed to
the dead-letter queue and never delivered to subscribers.

History: the version was bumped from `"2.0"` to `"2.1"` in the 2024-Q1 schema
migration when the envelope gained a nested `"payload"` field.  `"2.0"` events
are no longer accepted.  `"1.0"` is the legacy pre-migration format —
completely incompatible.

The router performs a string equality check — not semver parsing — so the
exact string `"2.1"` is required.  `"v2.1"`, `"2_1"`, `"2"`, and `"2.10"`
are all rejected.

Minimum valid event structure:

    {
      "_ev": "2.1",
      "type": "<event_type>",
      "payload": { ... }
    }
"""

TASK_EVENT_SCHEMA_VERSION = ABTask(
    id="event_schema_version",
    description=(
        "The function `make_event(event_type, payload)` in events.py should return "
        "a domain event dict ready for publishing to the event bus.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_EVENT_SCHEMA_VERSION,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_EVENT_SCHEMA_VERSION,
    onmc_hint=_ONMC_HINT_EVENT_SCHEMA_VERSION,
    grounding_doc=_GROUNDING_DOC_EVENT_SCHEMA_VERSION,
    note=(
        "A cold agent returns a plausible event dict with type/payload but omits "
        "the required '_ev' meta key.  Even an agent that guesses a version field "
        "would guess 'version': '1.0' or 'v': '2.0' — the exact key '_ev' and the "
        "exact value '2.1' are arbitrary internal conventions.  The ONMC hint names "
        "both the key and the exact version string."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 14: validation_field_path — validation errors use field_path key, not field
# ---------------------------------------------------------------------------

_SETUP_VALIDATION_FIELD_PATH = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("validation.py").write_text('''
def make_validation_error(message: str, field_name: str) -> dict:
    \"\"\"Return a validation error dict for the given field and message.\"\"\"
    return {
        "error": message,
        "field": field_name,
    }
''')
"""

_HIDDEN_GATE_VALIDATION_FIELD_PATH = """\
from validation import make_validation_error

def test_field_path_key_present():
    err = make_validation_error("required", "email")
    assert "field_path" in err, (
        f"Validation error missing 'field_path' key.  Got keys: {list(err.keys())}"
    )

def test_field_path_value():
    err = make_validation_error("required", "email")
    assert err["field_path"] == "email", (
        f"Expected field_path='email' but got {err['field_path']!r}"
    )

def test_wrong_key_absent():
    err = make_validation_error("too_short", "username")
    assert "field" not in err, (
        "Old 'field' key must be replaced by 'field_path'"
    )

def test_error_message_preserved():
    err = make_validation_error("invalid_format", "phone")
    assert err["error"] == "invalid_format"
    assert err["field_path"] == "phone"
"""

_ONMC_HINT_VALIDATION_FIELD_PATH = """\
[ONMC Memory Context]
CONVENTION (validation error schema — do not use 'field', 'name', or 'key'):
  Validation error dicts in this codebase MUST use the key "field_path" (with
  an underscore) to identify the failing field.  The frontend error renderer
  reads exactly "field_path" to display inline field errors.  Using "field",
  "name", "key", or "path" causes the renderer to silently drop the inline
  error and show only a generic banner.

  The underscore-joined "field_path" was chosen in 2023 to distinguish from
  the ORM's "field" attribute (which refers to the model field object, not the
  API input path) and from the JSON Pointer "path" convention used elsewhere.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_VALIDATION_FIELD_PATH = """\
# Validation Error Schema

## Required Key: field_path

Validation error dicts must use the key `"field_path"` (underscore-joined) to
identify the failing input field.  The frontend error renderer reads exactly
`"field_path"` to display inline field errors.

Any other key — `"field"`, `"name"`, `"key"`, `"path"` — causes the renderer
to silently drop the inline error message and show only a generic banner.

Background: the underscore-joined `"field_path"` was introduced in 2023 to
avoid collisions with:
- The ORM's `"field"` attribute, which refers to the model field object (not
  the API input name).
- The JSON Pointer `"path"` convention used in JSON:API error objects.

Minimum valid validation error:

    {
      "error": "<error_code>",
      "field_path": "<input_field_name>"
    }
"""

TASK_VALIDATION_FIELD_PATH = ABTask(
    id="validation_field_path",
    description=(
        "The function `make_validation_error(message, field_name)` in validation.py "
        "should return a validation error dict.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_VALIDATION_FIELD_PATH,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_VALIDATION_FIELD_PATH,
    onmc_hint=_ONMC_HINT_VALIDATION_FIELD_PATH,
    grounding_doc=_GROUNDING_DOC_VALIDATION_FIELD_PATH,
    note=(
        "A cold agent uses 'field' (the obvious, standard key for error location). "
        "The required key 'field_path' is an arbitrary 2023 convention chosen to "
        "avoid ORM collisions — un-inferrable without the history.  The ONMC hint "
        "names the key and why the obvious alternatives were rejected."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 15: payment_ref_separator — payment references use pipe separator
# ---------------------------------------------------------------------------

_SETUP_PAYMENT_REF_SEPARATOR = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("payment_ref.py").write_text('''
def make_payment_ref(merchant_id: str, order_id: str) -> str:
    \"\"\"Return the payment reference string for this merchant order.\"\"\"
    return f"{merchant_id}-{order_id}"
''')
"""

_HIDDEN_GATE_PAYMENT_REF_SEPARATOR = """\
from payment_ref import make_payment_ref

def test_pipe_separator():
    ref = make_payment_ref("MER001", "ORD456")
    assert ref == "MER001|ORD456", (
        f"Expected 'MER001|ORD456' but got {ref!r}"
    )

def test_pipe_present():
    ref = make_payment_ref("MER001", "ORD456")
    assert "|" in ref, f"Pipe separator missing in ref: {ref!r}"

def test_dash_absent():
    ref = make_payment_ref("MER001", "ORD456")
    assert ref.count("|") == 1
    assert "-" not in ref or ref.index("|") >= 0  # dash allowed in IDs, pipe must be separator

def test_parts_recoverable():
    ref = make_payment_ref("ACME", "12345")
    merchant, order = ref.split("|", 1)
    assert merchant == "ACME"
    assert order == "12345"
"""

_ONMC_HINT_PAYMENT_REF_SEPARATOR = """\
[ONMC Memory Context]
CONVENTION (payment gateway contract — do not use any other separator):
  Payment reference strings MUST use the pipe character '|' to join the
  merchant ID and order ID:  "{merchant_id}|{order_id}"
  The payment gateway splits on '|' to extract both components.  Any other
  separator (dash, underscore, colon, slash) is treated as part of one of
  the IDs and causes a gateway lookup failure — the transaction is rejected
  with an INVALID_REF error.

  Dashes are common in both merchant IDs (MER-001) and order IDs (ORD-A1),
  so any dash-based separator would be ambiguous.  Pipe was chosen as the
  only character guaranteed not to appear in either component.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_PAYMENT_REF_SEPARATOR = """\
# Payment Gateway — Reference String Format

## Separator Convention

Payment reference strings must join the merchant ID and order ID with the
pipe character:  `"{merchant_id}|{order_id}"`

Example: `"MER001|ORD456"`

The payment gateway splits on `|` to extract both components.  Any other
separator — dash, underscore, colon, slash — is treated as part of one of
the IDs, causing a gateway lookup failure and an `INVALID_REF` error.

Background: dashes are common in both merchant IDs (e.g., `MER-001`) and
order IDs (e.g., `ORD-A1-2024`), so a dash-based separator would be
ambiguous.  Pipe was chosen as the only ASCII character guaranteed not to
appear in merchant or order identifiers per the registration contract.

Always construct references as: `f"{merchant_id}|{order_id}"`
"""

TASK_PAYMENT_REF_SEPARATOR = ABTask(
    id="payment_ref_separator",
    description=(
        "The function `make_payment_ref(merchant_id, order_id)` in payment_ref.py "
        "should return the payment reference string for this merchant order.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_PAYMENT_REF_SEPARATOR,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_PAYMENT_REF_SEPARATOR,
    onmc_hint=_ONMC_HINT_PAYMENT_REF_SEPARATOR,
    grounding_doc=_GROUNDING_DOC_PAYMENT_REF_SEPARATOR,
    note=(
        "A cold agent uses a dash separator (natural join for composite IDs).  "
        "The gateway requires a pipe '|' character — an arbitrary choice that "
        "avoids ambiguity with dashes in merchant and order IDs.  "
        "The ONMC hint names the separator and the reason dashes were rejected."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 16: refund_credit_flag — refunds encoded as positive amount + is_credit flag
# ---------------------------------------------------------------------------

_SETUP_REFUND_CREDIT_FLAG = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("refund.py").write_text('''
def encode_refund(amount_paise: int) -> dict:
    \"\"\"Encode a refund amount for the payment processor.  amount_paise is positive.\"\"\"
    return {
        "amount_paise": -amount_paise,
    }
''')
"""

_HIDDEN_GATE_REFUND_CREDIT_FLAG = """\
from refund import encode_refund

def test_amount_is_positive():
    r = encode_refund(5000)
    assert r["amount_paise"] > 0, (
        f"Refund amount must be positive but got {r['amount_paise']}"
    )

def test_amount_value():
    r = encode_refund(5000)
    assert r["amount_paise"] == 5000

def test_is_credit_flag_present():
    r = encode_refund(5000)
    assert "is_credit" in r, (
        f"Refund encoding missing 'is_credit' flag.  Got keys: {list(r.keys())}"
    )

def test_is_credit_flag_true():
    r = encode_refund(1000)
    assert r["is_credit"] is True, (
        f"Expected is_credit=True but got {r['is_credit']!r}"
    )

def test_negative_amount_rejected():
    r = encode_refund(2500)
    assert r["amount_paise"] >= 0, "amount_paise must never be negative in the encoding"
"""

_ONMC_HINT_REFUND_CREDIT_FLAG = """\
[ONMC Memory Context]
DECISION (post-incident, 2023-Q4 — enforced via code review):
  Refunds MUST be encoded as a POSITIVE amount with an explicit "is_credit"
  boolean flag:
    {"amount_paise": <positive_int>, "is_credit": True}
  Negative amounts are FORBIDDEN.  The payment processor's ledger API treats
  negative "amount_paise" as a charge adjustment (not a credit) — a refund
  encoded as -5000 was booked as an additional debit, causing double charges.

  The incident affected 47 transactions in 2023-Q4 before the processor's
  support team identified the encoding bug.  The "is_credit" flag triggers a
  separate ledger entry in the credit account rather than reversing the debit.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_REFUND_CREDIT_FLAG = """\
# Payment Processor — Refund Encoding

## Credit Flag Convention

Refunds must be encoded as a positive amount with an explicit `is_credit` flag:

    {"amount_paise": <positive_integer>, "is_credit": True}

Negative amounts are forbidden.  The payment processor's ledger API treats
negative `amount_paise` values as charge adjustments (debits), not credits.
A refund encoded as `-5000` was incorrectly booked as an additional debit,
causing double charges for 47 transactions in the 2023-Q4 incident.

The `"is_credit": True` flag triggers a separate ledger entry in the credit
account instead of reversing the debit row.  This two-field encoding was
mandated by the processor after the incident.

Always pass `amount_paise` as a positive integer and set `"is_credit": True`.
Never use negative amounts in the refund encoding.
"""

TASK_REFUND_CREDIT_FLAG = ABTask(
    id="refund_credit_flag",
    description=(
        "The function `encode_refund(amount_paise: int) -> dict` in refund.py encodes "
        "a refund amount for the payment processor.  The input `amount_paise` is always "
        "a positive integer representing the refund amount.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_REFUND_CREDIT_FLAG,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_REFUND_CREDIT_FLAG,
    onmc_hint=_ONMC_HINT_REFUND_CREDIT_FLAG,
    grounding_doc=_GROUNDING_DOC_REFUND_CREDIT_FLAG,
    note=(
        "A cold agent returns {'amount_paise': -amount_paise} — negating the value is "
        "the natural refund encoding.  The processor treats negatives as debits, not "
        "credits; this caused real double-charges.  The correct encoding (positive amount "
        "+ is_credit flag) is an arbitrary post-incident decision, not a standard pattern."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 17: fx_rate_precision — FX rates stored to 8 decimal places (not 4)
# ---------------------------------------------------------------------------

_SETUP_FX_RATE_PRECISION = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("fx.py").write_text('''
def store_fx_rate(rate: str) -> str:
    \"\"\"Format a raw FX rate string for storage in the exchange service.\"\"\"
    return str(float(rate))
''')
"""

_HIDDEN_GATE_FX_RATE_PRECISION = """\
from fx import store_fx_rate

def test_eight_decimal_places():
    result = store_fx_rate("83.12")
    parts = result.split(".")
    assert len(parts) == 2, f"Result must contain a decimal point: {result!r}"
    assert len(parts[1]) == 8, (
        f"Expected 8 decimal places but got {len(parts[1])}: {result!r}"
    )

def test_value_preserved():
    result = store_fx_rate("83.12")
    assert result.startswith("83.12"), (
        f"Integer and first 2 decimal places must be preserved: {result!r}"
    )

def test_trailing_zeros_padded():
    result = store_fx_rate("1.0")
    parts = result.split(".")
    assert len(parts[1]) == 8, (
        f"Trailing zeros must be present to reach 8 decimal places: {result!r}"
    )

def test_precise_rate():
    result = store_fx_rate("85.12345678")
    assert result == "85.12345678", f"Expected '85.12345678' but got {result!r}"
"""

_ONMC_HINT_FX_RATE_PRECISION = """\
[ONMC Memory Context]
CONVENTION (exchange service contract — 8 decimal places, not 4 or 6):
  FX rates stored in the exchange service MUST be formatted to exactly
  8 decimal places.  The exchange engine performs cross-rate triangulation
  (e.g., USD → INR via USD → SGD → INR) and rounding errors beyond the
  8th decimal place compound across legs, causing settlement mismatches.

  The correct pattern:
    from decimal import Decimal
    return f"{Decimal(rate):.8f}"
  Always pass the raw string to Decimal — never convert to float first.
  f"{Decimal('83.12'):.8f}" == "83.12000000"  (exactly 8 decimal places).
  4 decimal places (the common fintech default) caused a settlement dispute
  in 2023 on a large USD/INR trade.  6 places is still insufficient for the
  triangulation engine.  8 is the minimum required.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_FX_RATE_PRECISION = """\
# Exchange Service — FX Rate Storage Format

## Precision Requirement: 8 Decimal Places

FX rates stored in the exchange service must be formatted to exactly
8 decimal places.  The exchange engine performs cross-rate triangulation
(e.g., USD → INR via USD → SGD → INR) and rounding errors beyond the 8th
decimal place compound across trade legs, causing settlement mismatches.

Required pattern:

    from decimal import Decimal
    return f"{Decimal(rate):.8f}"

Always pass the raw string directly to `Decimal`.  Never convert to float
first — float representation of rates like `"83.12"` loses precision
before the f-string formatting step.

Examples:
  `store_fx_rate("83.12")` → `"83.12000000"` (8 decimal places)
  `store_fx_rate("85.12345678")` → `"85.12345678"`

Background: 4 decimal places (the common fintech default) caused a settlement
dispute in a large USD/INR trade in 2023.  6 decimal places is also
insufficient for the triangulation engine.  8 decimal places is the minimum
mandated by the exchange service contract.
"""

TASK_FX_RATE_PRECISION = ABTask(
    id="fx_rate_precision",
    description=(
        "The function `store_fx_rate(rate: str) -> str` in fx.py formats a raw FX rate "
        "string for storage in the exchange service.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_FX_RATE_PRECISION,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_FX_RATE_PRECISION,
    onmc_hint=_ONMC_HINT_FX_RATE_PRECISION,
    grounding_doc=_GROUNDING_DOC_FX_RATE_PRECISION,
    note=(
        "A cold agent returns str(float(rate)) which gives variable decimal places "
        "(e.g., '83.12', not '83.12000000').  Even an agent that pads decimals would "
        "choose 4 or 6 (common fintech defaults) — 8 is the arbitrary exchange service "
        "contract.  The ONMC hint names the exact number and the Decimal pattern."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 18: tz_offset_compact_format — UTC offsets as +HHMM (no prefix, no colon)
# ---------------------------------------------------------------------------

_SETUP_TZ_OFFSET_COMPACT = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("tz_format.py").write_text('''
def format_tz_offset(utc_offset_minutes: int) -> str:
    \"\"\"Return the timezone offset string for the given UTC offset in minutes.\"\"\"
    h, m = divmod(abs(utc_offset_minutes), 60)
    sign = "+" if utc_offset_minutes >= 0 else "-"
    return f"UTC{sign}{h:02d}{m:02d}"
''')
"""

_HIDDEN_GATE_TZ_OFFSET_COMPACT = """\
from tz_format import format_tz_offset

def test_positive_offset():
    result = format_tz_offset(330)  # +05:30 → IST
    assert result == "+0530", f"Expected '+0530' but got {result!r}"

def test_utc_zero():
    result = format_tz_offset(0)
    assert result == "+0000", f"Expected '+0000' but got {result!r}"

def test_negative_offset():
    result = format_tz_offset(-300)  # -05:00 → US Eastern (EST)
    assert result == "-0500", f"Expected '-0500' but got {result!r}"

def test_no_utc_prefix():
    result = format_tz_offset(60)
    assert not result.startswith("UTC"), (
        f"Result must not start with 'UTC' prefix: {result!r}"
    )

def test_exactly_five_chars():
    result = format_tz_offset(330)
    assert len(result) == 5, (
        f"Result must be exactly 5 characters (+HHMM) but got {len(result)}: {result!r}"
    )
"""

_ONMC_HINT_TZ_OFFSET_COMPACT = """\
[ONMC Memory Context]
CONVENTION (telemetry pipeline contract — 5-char format, no UTC prefix):
  Timezone offsets in telemetry payloads MUST use the compact 5-character
  format:  {sign}{HH}{MM}
  Examples:  "+0530"  "+0000"  "-0500"

  Rules:
  - NO "UTC" prefix (the telemetry parser uses a 5-char fixed-width field)
  - NO colon between hours and minutes ("+05:30" → parse error)
  - Always 5 characters: sign (1) + hours (2) + minutes (2)

  The "UTC+0530" form was rejected because it has 8 chars and breaks the
  fixed-width field parser.  ISO "+05:30" (with colon) has 6 chars and also
  breaks the parser.  The compact 5-char format was mandated in 2022 when
  the telemetry schema was frozen.  "+0530" is correct; all other forms fail
  the telemetry ingest validator.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_TZ_OFFSET_COMPACT = """\
# Telemetry Pipeline — Timezone Offset Format

## Required Format: 5-character compact offset

Timezone offsets in telemetry payloads must use the compact 5-character format:

    {sign}{HH}{MM}

Examples: `"+0530"`, `"+0000"`, `"-0500"`

Rules:
- **No** `"UTC"` prefix — the telemetry parser uses a 5-character fixed-width field.
  `"UTC+0530"` (8 chars) breaks the parser.
- **No** colon between hours and minutes — `"+05:30"` (6 chars) also breaks the parser.
- Always exactly 5 characters: 1 sign + 2 digit hours + 2 digit minutes.

The 5-character compact format was mandated in 2022 when the telemetry schema
was frozen.  Any other representation — ISO 8601 `"+05:30"`, RFC 822 `"+0530"` with
UTC label, or named abbreviations like `"IST"` — fails the ingest validator.

Use: `f"{'+' if offset_minutes >= 0 else '-'}{h:02d}{m:02d}"`
"""

TASK_TZ_OFFSET_COMPACT_FORMAT = ABTask(
    id="tz_offset_compact_format",
    description=(
        "The function `format_tz_offset(utc_offset_minutes: int) -> str` in tz_format.py "
        "returns a timezone offset string for a given UTC offset in minutes.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_TZ_OFFSET_COMPACT,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_TZ_OFFSET_COMPACT,
    onmc_hint=_ONMC_HINT_TZ_OFFSET_COMPACT,
    grounding_doc=_GROUNDING_DOC_TZ_OFFSET_COMPACT,
    note=(
        "A cold agent adds a 'UTC' prefix (plausible, readable).  The telemetry parser "
        "uses a 5-char fixed-width field, so 'UTC+0530' (8 chars) breaks ingestion. "
        "The 5-char '+HHMM' format is a frozen 2022 constraint — un-inferrable without "
        "the schema history.  The ONMC hint names the format and both disallowed forms."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 19: duration_microseconds — profiler durations stored in microseconds
# ---------------------------------------------------------------------------

_SETUP_DURATION_MICROSECONDS = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("profiler.py").write_text('''
def to_storage_duration(nanoseconds: int) -> int:
    \"\"\"Convert a raw profiler duration (nanoseconds) to the storage unit.\"\"\"
    return nanoseconds // 1_000_000
''')
"""

_HIDDEN_GATE_DURATION_MICROSECONDS = """\
from profiler import to_storage_duration

def test_one_millisecond():
    # 1 ms = 1,000,000 ns → must be 1000 microseconds
    assert to_storage_duration(1_000_000) == 1000, (
        f"1ms should be 1000 microseconds but got {to_storage_duration(1_000_000)}"
    )

def test_half_millisecond():
    # 0.5 ms = 500,000 ns → must be 500 microseconds
    assert to_storage_duration(500_000) == 500

def test_one_second():
    # 1s = 1,000,000,000 ns → must be 1,000,000 microseconds
    assert to_storage_duration(1_000_000_000) == 1_000_000

def test_one_microsecond():
    # 1 μs = 1,000 ns → must be 1
    assert to_storage_duration(1_000) == 1

def test_returns_int():
    result = to_storage_duration(1_000_000)
    assert isinstance(result, int)
"""

_ONMC_HINT_DURATION_MICROSECONDS = """\
[ONMC Memory Context]
CONVENTION (profiler storage contract — microseconds, not milliseconds):
  The profiler storage backend expects durations in MICROSECONDS (μs).
  Raw profiler values arrive in nanoseconds.  The correct conversion is:
    return nanoseconds // 1_000   # ns → μs (divide by 1,000)

  NOT milliseconds (which would divide by 1,000,000).  The storage schema
  uses microsecond precision to capture sub-millisecond spans (e.g., cache
  reads of 200–800 μs) that millisecond storage would collapse to 0.  A
  previous implementation divided by 1,000,000 (ms) and lost all sub-1ms
  spans, making the profiler useless for cache and queue latency analysis.
  The switch to μs was made in 2023-Q2.  The column type is BIGINT
  (microseconds since epoch or raw μs), not FLOAT (ms with decimals).
[/ONMC Memory Context]

"""

_GROUNDING_DOC_DURATION_MICROSECONDS = """\
# Profiler Storage — Duration Unit

## Unit: Microseconds (μs)

The profiler storage backend expects duration values in **microseconds** (μs).
Raw profiler measurements arrive in nanoseconds.

Correct conversion:

    return nanoseconds // 1_000   # ns → μs

Do not divide by `1_000_000` (which gives milliseconds).  Millisecond
precision collapses sub-1ms spans (cache reads of 200–800 μs, queue
operations, etc.) to zero, making the profiler useless for latency analysis.

Background: a previous implementation stored milliseconds.  All sub-1ms
spans were recorded as 0, preventing cache and queue latency analysis.
The schema was migrated to microseconds in 2023-Q2.  The storage column is
`BIGINT` (integer microseconds) — not a float (which would suggest fractional
milliseconds).

Conversion table:
  1 μs  = 1,000 ns
  1 ms  = 1,000 μs = 1,000,000 ns
  1 s   = 1,000,000 μs = 1,000,000,000 ns
"""

TASK_DURATION_MICROSECONDS = ABTask(
    id="duration_microseconds",
    description=(
        "The function `to_storage_duration(nanoseconds: int) -> int` in profiler.py "
        "converts a raw profiler nanosecond measurement to the storage unit used by "
        "the profiler backend.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_DURATION_MICROSECONDS,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_DURATION_MICROSECONDS,
    onmc_hint=_ONMC_HINT_DURATION_MICROSECONDS,
    grounding_doc=_GROUNDING_DOC_DURATION_MICROSECONDS,
    note=(
        "A cold agent divides by 1,000,000 (milliseconds — the conventional unit for "
        "profiling).  The storage schema requires microseconds (divide by 1,000) to "
        "preserve sub-millisecond spans.  This is an arbitrary 2023-Q2 migration "
        "decision — un-inferrable without the history.  The ONMC hint names the unit "
        "and the reason milliseconds were abandoned."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 20: pagination_total_key — total count key is total_count (not total)
# ---------------------------------------------------------------------------

_SETUP_PAGINATION_TOTAL_KEY = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("page_resp.py").write_text('''
def make_page_response(items: list, total: int, page: int) -> dict:
    \"\"\"Build a paginated list response.\"\"\"
    return {
        "items": items,
        "total": total,
        "page": page,
    }
''')
"""

_HIDDEN_GATE_PAGINATION_TOTAL_KEY = """\
from page_resp import make_page_response

def test_total_count_key_present():
    r = make_page_response(["a", "b"], 42, 1)
    assert "total_count" in r, (
        f"Response missing 'total_count' key.  Got keys: {list(r.keys())}"
    )

def test_total_count_value():
    r = make_page_response(["a", "b"], 42, 1)
    assert r["total_count"] == 42

def test_wrong_key_absent():
    r = make_page_response(["a"], 10, 1)
    assert "total" not in r, (
        "Old 'total' key must be replaced by 'total_count'"
    )

def test_items_and_page_preserved():
    r = make_page_response(["x", "y", "z"], 100, 3)
    assert r["items"] == ["x", "y", "z"]
    assert r["page"] == 3
"""

_ONMC_HINT_PAGINATION_TOTAL_KEY = """\
[ONMC Memory Context]
CONVENTION (pagination client contract — use total_count, never total):
  Paginated list responses MUST use the key "total_count" (underscore-joined)
  for the overall item count.  The frontend pagination component reads exactly
  "total_count" to render page indicators.  Using "total", "count", "n_items",
  or "size" causes the component to fall back to zero and show "Page 1 of 1"
  regardless of the actual result set.

  "total" was the original key but was renamed in 2022 when the component
  library was upgraded.  The rename resolved a collision with a "total" field
  that some endpoints were already using for subtotals (e.g., "total" price
  in a cart response).  The underscore-joined "total_count" is unambiguous.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_PAGINATION_TOTAL_KEY = """\
# Pagination — Response Schema

## Required Key: total_count

Paginated list responses must use the key `"total_count"` (underscore-joined)
for the total number of items in the result set.

The frontend pagination component reads exactly `"total_count"` to compute
page indicators.  Using `"total"`, `"count"`, `"n_items"`, or `"size"` causes
the component to fall back to zero, showing "Page 1 of 1" for all results.

History: `"total"` was the original key.  It was renamed to `"total_count"` in
2022 when the component library was upgraded, to resolve a collision with a
`"total"` field that some endpoints were already using for financial subtotals
(e.g., cart total price).  The underscore-joined name is unambiguous across
both domain contexts.

Minimum valid paginated response:

    {
      "items": [...],
      "total_count": <int>,
      "page": <int>
    }
"""

TASK_PAGINATION_TOTAL_KEY = ABTask(
    id="pagination_total_key",
    description=(
        "The function `make_page_response(items, total, page)` in page_resp.py builds "
        "a paginated list response dict.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_PAGINATION_TOTAL_KEY,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_PAGINATION_TOTAL_KEY,
    onmc_hint=_ONMC_HINT_PAGINATION_TOTAL_KEY,
    grounding_doc=_GROUNDING_DOC_PAGINATION_TOTAL_KEY,
    note=(
        "A cold agent uses 'total' (the natural key name).  The frontend component "
        "requires 'total_count' — a 2022 rename to avoid collision with financial "
        "'total' fields.  The rename is an arbitrary migration decision; without the "
        "history, any competent agent picks 'total'.  The ONMC hint names the key "
        "and explains why the rename happened."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 21: cursor_base64url_no_padding — cursors base64url without padding
# ---------------------------------------------------------------------------

_SETUP_CURSOR_BASE64URL = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("cursor.py").write_text('''
import base64

def encode_cursor(payload: bytes) -> str:
    \"\"\"Encode a raw cursor payload as an opaque string.\"\"\"
    return base64.b64encode(payload).decode()
''')
"""

_HIDDEN_GATE_CURSOR_BASE64URL = """\
import base64
from cursor import encode_cursor

def test_no_padding_chars():
    cursor = encode_cursor(b"page:3:water:12345")
    assert "=" not in cursor, (
        f"Cursor must not contain padding '=' chars but got: {cursor!r}"
    )

def test_no_standard_base64_chars():
    # Standard base64 may contain + and / which are URL-unsafe
    cursor = encode_cursor(b"\xfb\xff\xfe" * 10)  # bytes that produce + and / in std b64
    assert "+" not in cursor, (
        f"Cursor must not contain '+' (URL-unsafe): {cursor!r}"
    )
    assert "/" not in cursor, (
        f"Cursor must not contain '/' (URL-unsafe): {cursor!r}"
    )

def test_decodable_as_base64url():
    payload = b"page:5:water:99999"
    cursor = encode_cursor(payload)
    # Recover by adding padding and decoding as urlsafe
    padded = cursor + "=" * ((4 - len(cursor) % 4) % 4)
    recovered = base64.urlsafe_b64decode(padded)
    assert recovered == payload

def test_returns_string():
    cursor = encode_cursor(b"x")
    assert isinstance(cursor, str)
"""

_ONMC_HINT_CURSOR_BASE64URL = """\
[ONMC Memory Context]
CONVENTION (pagination API contract — cursors must be URL-safe, no padding):
  Pagination cursors MUST be encoded with base64url (URL-safe variant) WITHOUT
  padding characters.  The correct Python pattern:
    import base64
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()

  Standard base64 (base64.b64encode) is forbidden because:
  1. It may produce '+' and '/' characters which are URL-unsafe and must be
     percent-encoded in query strings, breaking cursor round-trips.
  2. Trailing '=' padding causes some client HTTP libraries to truncate the
     cursor when it appears in a URL parameter.

  Cursors appear as query parameters (?cursor=...) and must be usable without
  percent-encoding.  base64url with no padding is the only safe format.
  This rule was enforced after a 2023 incident where cursors containing '/'
  were interpreted as path segments, returning 404s.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_CURSOR_BASE64URL = """\
# Pagination — Cursor Encoding

## Encoding: base64url Without Padding

Pagination cursors must be encoded with base64url (the URL-safe variant of
base64) WITHOUT trailing padding characters.

Required pattern:

    import base64
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()

Standard `base64.b64encode` is forbidden because:
1. It may produce `+` and `/` characters, which are URL-unsafe and must be
   percent-encoded in query strings.  URL encoding breaks cursor round-trips
   when clients do not encode query parameters correctly.
2. Trailing `=` padding causes some HTTP client libraries to truncate the
   cursor value when it appears as a URL query parameter.

Background: a 2023 incident found that cursors produced by standard base64
that happened to contain `/` were interpreted as URL path segments by the
load balancer, returning 404s.  base64url with no padding is the only safe
encoding for cursor values in query parameters.
"""

TASK_CURSOR_BASE64URL_NO_PADDING = ABTask(
    id="cursor_base64url_no_padding",
    description=(
        "The function `encode_cursor(payload: bytes) -> str` in cursor.py encodes "
        "a raw cursor payload as an opaque string for use in pagination query parameters.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_CURSOR_BASE64URL,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_CURSOR_BASE64URL,
    onmc_hint=_ONMC_HINT_CURSOR_BASE64URL,
    grounding_doc=_GROUNDING_DOC_CURSOR_BASE64URL,
    note=(
        "A cold agent uses standard base64.b64encode — the obvious choice.  Standard "
        "base64 produces URL-unsafe '+' and '/' characters and trailing '=' padding.  "
        "The cursor encoding requires urlsafe variant without padding — a URL safety "
        "incident-derived rule that is un-inferrable without the context."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 22: log_context_key — structured logs use log_ctx field, not context
# ---------------------------------------------------------------------------

_SETUP_LOG_CONTEXT_KEY = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("structured_log.py").write_text('''
def make_log_entry(message: str, level: str, context: str) -> dict:
    \"\"\"Build a structured log entry dict.\"\"\"
    return {
        "message": message,
        "level": level,
        "context": context,
    }
''')
"""

_HIDDEN_GATE_LOG_CONTEXT_KEY = """\
from structured_log import make_log_entry

def test_log_ctx_key_present():
    entry = make_log_entry("request handled", "INFO", "trace_id=abc123")
    assert "log_ctx" in entry, (
        f"Log entry missing 'log_ctx' key.  Got keys: {list(entry.keys())}"
    )

def test_log_ctx_value():
    entry = make_log_entry("request handled", "INFO", "trace_id=abc123")
    assert entry["log_ctx"] == "trace_id=abc123"

def test_context_key_absent():
    entry = make_log_entry("error occurred", "ERROR", "span=xyz")
    assert "context" not in entry, (
        "Old 'context' key must be replaced by 'log_ctx'"
    )

def test_message_and_level_preserved():
    entry = make_log_entry("db query", "DEBUG", "query_id=7")
    assert entry["message"] == "db query"
    assert entry["level"] == "DEBUG"
    assert entry["log_ctx"] == "query_id=7"
"""

_ONMC_HINT_LOG_CONTEXT_KEY = """\
[ONMC Memory Context]
CONVENTION (log aggregator schema — use log_ctx, not context or ctx):
  Structured log entries MUST store trace context under the key "log_ctx"
  (lowercase, underscore-joined).  The log aggregator's index schema maps
  this exact field to a searchable attribute.  Using "context", "ctx",
  "trace", or "trace_context" causes the aggregator to store it as a raw
  string in the unparsed blob field — keyword search and correlation queries
  stop working for that entry.

  The "context" key collided with an existing aggregator field that stores
  the runtime context object (heap size, GC stats).  Renaming to "log_ctx"
  resolved the collision and was deployed in 2023.  "ctx" (without "log_")
  is also reserved by the aggregator for internal use.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_LOG_CONTEXT_KEY = """\
# Log Aggregator — Structured Log Schema

## Required Key: log_ctx

Structured log entries must store trace context under the key `"log_ctx"`
(lowercase, underscore-joined).

The log aggregator's index schema maps `"log_ctx"` to a searchable attribute.
Using `"context"`, `"ctx"`, `"trace"`, or `"trace_context"` causes the
aggregator to store the value in the unparsed blob field — keyword search and
correlation queries no longer work for those entries.

History: the key `"context"` was originally used but collided with an existing
aggregator field that stores runtime context (heap size, GC stats).  Renaming
to `"log_ctx"` resolved the collision and was deployed in 2023.  The key `"ctx"`
(without the `"log_"` prefix) is reserved for internal aggregator use.

Minimum valid structured log entry:

    {
      "message": "<message>",
      "level": "<level>",
      "log_ctx": "<trace context string>"
    }
"""

TASK_LOG_CONTEXT_KEY = ABTask(
    id="log_context_key",
    description=(
        "The function `make_log_entry(message, level, context)` in structured_log.py "
        "builds a structured log entry dict.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_LOG_CONTEXT_KEY,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_LOG_CONTEXT_KEY,
    onmc_hint=_ONMC_HINT_LOG_CONTEXT_KEY,
    grounding_doc=_GROUNDING_DOC_LOG_CONTEXT_KEY,
    note=(
        "A cold agent uses 'context' (the natural key name for a context string). "
        "The log aggregator requires 'log_ctx' — a 2023 rename to avoid a collision "
        "with an existing aggregator field.  The rename is un-inferrable without the "
        "aggregator schema history.  The ONMC hint names the key and the collision."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 23: audit_actor_prefix — audit actor field is user:{id} (colon-prefixed)
# ---------------------------------------------------------------------------

_SETUP_AUDIT_ACTOR_PREFIX = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("audit_actor.py").write_text('''
def format_audit_actor(user_id: str) -> str:
    \"\"\"Return the actor identifier for audit log entries.\"\"\"
    return user_id
''')
"""

_HIDDEN_GATE_AUDIT_ACTOR_PREFIX = """\
from audit_actor import format_audit_actor

def test_user_prefix():
    result = format_audit_actor("u-001")
    assert result == "user:u-001", f"Expected 'user:u-001' but got {result!r}"

def test_starts_with_user_colon():
    result = format_audit_actor("admin")
    assert result.startswith("user:"), (
        f"Actor identifier must start with 'user:' but got: {result!r}"
    )

def test_user_id_preserved():
    result = format_audit_actor("usr-9999")
    assert "usr-9999" in result

def test_bare_id_rejected():
    result = format_audit_actor("u-001")
    assert result != "u-001", (
        "Bare user_id is not a valid actor identifier — prefix is required"
    )
"""

_ONMC_HINT_AUDIT_ACTOR_PREFIX = """\
[ONMC Memory Context]
CONVENTION (audit log schema — actor field requires user: prefix):
  The actor identifier in audit log entries MUST be formatted as:
    "user:{user_id}"
  For example: "user:u-001", "user:admin", "user:svc-billing"
  The audit pipeline's actor resolver splits on ':' to determine the actor
  TYPE (before the colon) and the actor ID (after the colon).  A bare
  user_id (without the "user:" prefix) is treated as an unknown actor type
  and the audit entry is tagged as "unresolved" — it is excluded from
  compliance reports.

  Service accounts use "svc:{service_name}" and system actions use
  "system:pipeline".  The colon-prefix scheme allows the resolver to handle
  multiple actor types without separate fields.  This was introduced in
  the 2022 audit schema v2 migration.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_AUDIT_ACTOR_PREFIX = """\
# Audit Pipeline — Actor Identifier Format

## Required Format: type:id

Audit log actor identifiers must use the colon-prefixed format:

    "{actor_type}:{actor_id}"

For human users: `"user:{user_id}"` — e.g., `"user:u-001"`, `"user:admin"`

The audit pipeline's actor resolver splits on `:` to determine the actor type
(left of the colon) and the actor ID (right of the colon).  A bare `user_id`
without the `"user:"` prefix is treated as an unknown actor type.  The audit
entry is tagged as `"unresolved"` and excluded from compliance reports.

Other valid actor types:
- `"svc:{service_name}"` — service accounts (e.g., `"svc:billing"`)
- `"system:{pipeline}"` — automated pipeline actions (e.g., `"system:cleanup"`)

The colon-prefix scheme was introduced in the 2022 audit schema v2 migration
to allow the resolver to handle multiple actor types without requiring separate
`actor_type` and `actor_id` fields.
"""

TASK_AUDIT_ACTOR_PREFIX = ABTask(
    id="audit_actor_prefix",
    description=(
        "The function `format_audit_actor(user_id: str) -> str` in audit_actor.py "
        "returns the actor identifier string for audit log entries.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_AUDIT_ACTOR_PREFIX,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_AUDIT_ACTOR_PREFIX,
    onmc_hint=_ONMC_HINT_AUDIT_ACTOR_PREFIX,
    grounding_doc=_GROUNDING_DOC_AUDIT_ACTOR_PREFIX,
    note=(
        "A cold agent returns the bare user_id — the obvious implementation when the "
        "function already receives a user_id argument.  The required 'user:' prefix is "
        "an arbitrary 2022 schema convention; without it, audit entries are tagged as "
        "unresolved and excluded from compliance reports.  The ONMC hint names the "
        "prefix and the colon-type scheme."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 24: feature_flag_env_prefix — feature flag env vars start with FF_
# ---------------------------------------------------------------------------

_SETUP_FEATURE_FLAG_ENV_PREFIX = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("flags.py").write_text('''
def flag_env_key(flag_name: str) -> str:
    \"\"\"Return the environment variable name for the given feature flag.\"\"\"
    return f"FEATURE_{flag_name.upper()}"
''')
"""

_HIDDEN_GATE_FEATURE_FLAG_ENV_PREFIX = """\
from flags import flag_env_key

def test_ff_prefix():
    key = flag_env_key("new_ui")
    assert key == "FF_NEW_UI", f"Expected 'FF_NEW_UI' but got {key!r}"

def test_starts_with_ff():
    key = flag_env_key("payment_v2")
    assert key.startswith("FF_"), (
        f"Flag env key must start with 'FF_' but got: {key!r}"
    )

def test_feature_prefix_absent():
    key = flag_env_key("new_ui")
    assert not key.startswith("FEATURE_"), (
        "Deprecated 'FEATURE_' prefix must not be used — use 'FF_'"
    )

def test_name_uppercased():
    key = flag_env_key("dark_mode")
    assert key == "FF_DARK_MODE"
"""

_ONMC_HINT_FEATURE_FLAG_ENV_PREFIX = """\
[ONMC Memory Context]
CONVENTION (feature flag config contract — FF_ prefix, not FEATURE_):
  Feature flag environment variable names MUST use the two-letter prefix
  "FF_" (two capital F's) followed by the uppercase flag name.  Examples:
    "FF_NEW_UI", "FF_PAYMENT_V2", "FF_DARK_MODE"
  The old prefix "FEATURE_" is deprecated and ignored by the flag reader.
  The flag service's config loader looks for "FF_*" keys only — any key
  starting with "FEATURE_" is treated as an unrelated env var and silently
  skipped.  This was changed in 2023 to shorten key names and avoid
  collisions with third-party libraries that use "FEATURE_" for their own
  flag systems.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_FEATURE_FLAG_ENV_PREFIX = """\
# Feature Flag Service — Environment Variable Naming

## Required Prefix: FF_

Feature flag environment variables must use the prefix `FF_` (two capital F's)
followed by the uppercase flag name.

Examples: `FF_NEW_UI`, `FF_PAYMENT_V2`, `FF_DARK_MODE`

The flag service's config loader scans for `FF_*` keys only.  Any key starting
with `FEATURE_` is treated as an unrelated environment variable and silently
skipped — the flag is never loaded.

Background: the prefix was shortened from `FEATURE_` to `FF_` in 2023 to
reduce key length and avoid collisions with third-party libraries that use
`FEATURE_` for their own flag systems (e.g., some OpenFeature SDKs).

Always use: `f"FF_{flag_name.upper()}"`

The `FEATURE_` prefix is deprecated.  Existing `FEATURE_*` variables in
production must be migrated to `FF_*` before the next major release.
"""

TASK_FEATURE_FLAG_ENV_PREFIX = ABTask(
    id="feature_flag_env_prefix",
    description=(
        "The function `flag_env_key(flag_name: str) -> str` in flags.py returns "
        "the environment variable name for a feature flag.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_FEATURE_FLAG_ENV_PREFIX,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_FEATURE_FLAG_ENV_PREFIX,
    onmc_hint=_ONMC_HINT_FEATURE_FLAG_ENV_PREFIX,
    grounding_doc=_GROUNDING_DOC_FEATURE_FLAG_ENV_PREFIX,
    note=(
        "A cold agent uses 'FEATURE_' (the natural, readable prefix for feature flags). "
        "The flag loader scans for 'FF_' keys only — the 2-letter abbreviation is an "
        "arbitrary 2023 naming decision.  Without the migration history, any agent "
        "would use 'FEATURE_' or 'FLAG_'.  The ONMC hint names the exact prefix."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 25: config_secret_scope — secret config keys prefixed sec: (not SECRET_)
# ---------------------------------------------------------------------------

_SETUP_CFGSCOPE_25 = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("config_keys.py").write_text('''
def make_secret_key(key_name: str) -> str:
    \"\"\"Return the full config store key for a secret value.\"\"\"
    return f"SECRET_{key_name}"
''')
"""

_HIDDEN_GATE_CFGSCOPE_25 = """\
from config_keys import make_secret_key

def test_sec_prefix():
    key = make_secret_key("db_password")
    assert key == "sec:db_password", f"Expected 'sec:db_password' but got {key!r}"

def test_starts_with_sec_colon():
    key = make_secret_key("api_key")
    assert key.startswith("sec:"), (
        f"Secret key must start with 'sec:' but got: {key!r}"
    )

def test_secret_prefix_absent():
    key = make_secret_key("db_password")
    assert not key.startswith("SECRET_"), (
        "Deprecated 'SECRET_' prefix must be replaced with 'sec:'"
    )

def test_name_preserved():
    key = make_secret_key("stripe_secret")
    assert key == "sec:stripe_secret"
"""

_ONMC_HINT_CFGSCOPE_25 = """\
[ONMC Memory Context]
CONVENTION (config store contract — sec: namespace prefix for secrets):
  Secret configuration values MUST be accessed via keys prefixed with "sec:"
  (lowercase, followed by colon).  The config service's secret backend mounts
  at the "sec:" namespace.  Keys using "SECRET_", "secret:", "secrets/", or
  no prefix are read from the plaintext config store (not the secret backend)
  — secrets stored there are written to application logs in plaintext.

  The "sec:" namespace was introduced in 2022 when the secret backend was
  separated from the plaintext config store.  Any key without the "sec:"
  prefix routes to the plaintext store.  This has caused secret leakage
  incidents — enforce "sec:" for all sensitive values.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_CFGSCOPE_25 = """\
# Config Service — Secret Namespace

## Required Prefix: sec:

Secret configuration values must be accessed via keys prefixed with `"sec:"`
(lowercase `sec` followed by a colon).

Examples: `"sec:db_password"`, `"sec:api_key"`, `"sec:stripe_secret"`

The config service's secret backend is mounted at the `"sec:"` namespace.
Keys that do not start with `"sec:"` — including `"SECRET_"`, `"secret:"`,
`"secrets/"`, or bare key names — are read from the plaintext config store
(not the secret backend).  Secrets stored in the plaintext config store are
written to application logs in plaintext.

Background: the `"sec:"` namespace was introduced in 2022 when the secret
backend was separated from the plaintext config store.  Before separation,
all keys shared one store.  Post-separation, only `"sec:"` keys route to the
vault-backed secret store.  Using `"SECRET_"` (the old convention) causes
values to be retrieved from plaintext.
"""

TASK_CONFIG_SECRET_SCOPE = ABTask(
    id="config_secret_scope",
    description=(
        "The function `make_secret_key(key_name: str) -> str` in config_keys.py "
        "returns the full config store key for a secret value.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_CFGSCOPE_25,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_CFGSCOPE_25,
    onmc_hint=_ONMC_HINT_CFGSCOPE_25,
    grounding_doc=_GROUNDING_DOC_CFGSCOPE_25,
    note=(
        "A cold agent uses 'SECRET_' prefix (conventional and readable).  The config "
        "service's secret backend requires the 'sec:' namespace prefix — any other "
        "form routes to the plaintext store.  This 2022 separation is un-inferrable; "
        "an agent naturally picks 'SECRET_' as the safe-looking prefix."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 26: jwt_edDSA_only — only EdDSA algorithm permitted for JWT signing
# ---------------------------------------------------------------------------

_SETUP_JWT_EDDSA_ONLY = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("jwt_config.py").write_text('''
def get_allowed_jwt_algorithms() -> list[str]:
    \"\"\"Return the list of permitted JWT signing algorithms.\"\"\"
    return ["HS256", "RS256"]
''')
"""

_HIDDEN_GATE_JWT_EDDSA_ONLY = """\
from jwt_config import get_allowed_jwt_algorithms

def test_only_eddsa():
    algos = get_allowed_jwt_algorithms()
    assert algos == ["EdDSA"], (
        f"Expected ['EdDSA'] but got {algos!r}"
    )

def test_hs256_not_allowed():
    algos = get_allowed_jwt_algorithms()
    assert "HS256" not in algos, "HS256 is not permitted — algorithm confusion risk"

def test_rs256_not_allowed():
    algos = get_allowed_jwt_algorithms()
    assert "RS256" not in algos, "RS256 is not permitted — only EdDSA"

def test_exactly_one_algorithm():
    algos = get_allowed_jwt_algorithms()
    assert len(algos) == 1, (
        f"Exactly one algorithm must be allowed but got {len(algos)}: {algos!r}"
    )
"""

_ONMC_HINT_JWT_EDDSA_ONLY = """\
[ONMC Memory Context]
DECISION (post-incident, 2024-Q1 — security hardening):
  JWT verification MUST accept ONLY the algorithm "EdDSA".  No other
  algorithm is permitted.  The allowlist must be exactly ["EdDSA"].

  Background: an algorithm confusion attack was possible when both HS256 and
  RS256 were permitted.  An attacker could forge tokens by switching the
  "alg" header to HS256 and signing with the public key (which is known).
  The attack exploited a library that used the "alg" header value to select
  the verify path rather than enforcing the expected algorithm server-side.

  EdDSA (Ed25519) was chosen as the sole permitted algorithm because it is
  not susceptible to timing attacks, has no parameter confusion with RSA, and
  the library implementation enforces the algorithm independently of the
  header.  HS256 (HMAC), RS256 (RSA), and ES256 (ECDSA) are all forbidden.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_JWT_EDDSA_ONLY = """\
# JWT Security Policy — Algorithm Allowlist

## Only EdDSA Permitted

JWT verification must accept only the `"EdDSA"` algorithm.  The allowed
algorithms list must be exactly `["EdDSA"]`.

All other algorithms — `"HS256"`, `"RS256"`, `"ES256"`, `"none"` — are
forbidden.

Background: a 2024-Q1 security review identified an algorithm confusion
vulnerability when both `HS256` and `RS256` were permitted.  An attacker
can forge tokens by switching the JWT `"alg"` header to `HS256` and signing
with the server's public RSA key (which is not secret).  The library used the
`"alg"` header to select the verify path instead of enforcing the expected
algorithm, allowing the attack.

`EdDSA` (Ed25519) was selected as the sole algorithm because:
- It is not susceptible to algorithm confusion with RSA or HMAC.
- It has no parameter confusion (unlike ECDSA curve selection).
- The library enforces the algorithm independently of the header field.

This decision was encoded in the security policy and enforced in code review.
"""

TASK_JWT_EDDSA_ONLY = ABTask(
    id="jwt_edDSA_only",
    description=(
        "The function `get_allowed_jwt_algorithms() -> list[str]` in jwt_config.py "
        "returns the list of permitted JWT signing algorithms for token verification.  "
        "Fix it so all tests pass."
    ),
    setup_script=_SETUP_JWT_EDDSA_ONLY,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_JWT_EDDSA_ONLY,
    onmc_hint=_ONMC_HINT_JWT_EDDSA_ONLY,
    grounding_doc=_GROUNDING_DOC_JWT_EDDSA_ONLY,
    note=(
        "A cold agent returns ['HS256', 'RS256'] — the two most common JWT algorithms. "
        "The security policy allows only 'EdDSA' after a 2024-Q1 algorithm confusion "
        "incident.  An agent would not choose EdDSA unprompted (it is less common than "
        "HS256/RS256).  The ONMC hint names the incident and the exact allowlist."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 27: request_nonce_header — signed requests need X-Acme-Nonce header
# ---------------------------------------------------------------------------

_SETUP_REQUEST_NONCE_HEADER = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("request_auth.py").write_text('''
def build_signed_request_headers(token: str, nonce: str) -> dict[str, str]:
    \"\"\"Build headers for a signed API request.\"\"\"
    return {
        "Authorization": f"Bearer {token}",
        "X-Nonce": nonce,
    }
''')
"""

_HIDDEN_GATE_REQUEST_NONCE_HEADER = """\
from request_auth import build_signed_request_headers

def test_correct_nonce_header():
    h = build_signed_request_headers("tok123", "abc-nonce-456")
    assert "X-Acme-Nonce" in h, (
        f"Expected 'X-Acme-Nonce' header but got keys: {list(h.keys())}"
    )

def test_wrong_nonce_header_absent():
    h = build_signed_request_headers("tok123", "abc-nonce-456")
    assert "X-Nonce" not in h, (
        "Disallowed 'X-Nonce' header found — must use 'X-Acme-Nonce'"
    )

def test_nonce_value_preserved():
    h = build_signed_request_headers("tok123", "abc-nonce-456")
    assert h["X-Acme-Nonce"] == "abc-nonce-456"

def test_authorization_preserved():
    h = build_signed_request_headers("tok123", "abc-nonce-456")
    assert h["Authorization"] == "Bearer tok123"
"""

_ONMC_HINT_REQUEST_NONCE_HEADER = """\
[ONMC Memory Context]
CONVENTION (request signing contract — use X-Acme-Nonce, not X-Nonce):
  Signed API requests MUST include the nonce in the header named exactly:
    X-Acme-Nonce
  The request verification middleware checks for this exact header name.
  Using "X-Nonce", "X-Request-Id", "X-Idempotency-Key", or "Nonce" causes
  the middleware to treat the request as unsigned — it is then rejected
  with a 403 "missing_nonce" error.

  The "X-Acme-" prefix was required by the security team to namespace
  internal signing headers and avoid confusion with third-party middleware
  that also injects an "X-Nonce" header for their own purposes (observed
  in 2023 with a CDN provider).  The nonce is used for replay-attack
  prevention; if the middleware cannot find it, the request is blocked.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_REQUEST_NONCE_HEADER = """\
# Request Signing — Nonce Header

## Required Header: X-Acme-Nonce

Signed API requests must include the nonce in the header named exactly
`X-Acme-Nonce`.

The request verification middleware checks for this exact header name.
Any other name — `X-Nonce`, `X-Request-Id`, `X-Idempotency-Key`, `Nonce` —
causes the middleware to treat the request as unsigned and reject it with a
`403 missing_nonce` error.

Background: the `X-Acme-` prefix was required by the security team in 2023
to namespace internal signing headers.  A CDN provider was injecting its own
`X-Nonce` header for caching purposes, causing conflicts with the signing
middleware.  Adding the `X-Acme-` prefix uniquely identifies the nonce as
part of our internal signing scheme.

The nonce prevents replay attacks: the middleware checks that the nonce has
not been used before (stored in Redis with a 5-minute TTL).  Without the
correct header name, replay protection is disabled for that request.
"""

TASK_REQUEST_NONCE_HEADER = ABTask(
    id="request_nonce_header",
    description=(
        "The function `build_signed_request_headers(token, nonce)` in request_auth.py "
        "builds the headers for a signed API request.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_REQUEST_NONCE_HEADER,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_REQUEST_NONCE_HEADER,
    onmc_hint=_ONMC_HINT_REQUEST_NONCE_HEADER,
    grounding_doc=_GROUNDING_DOC_REQUEST_NONCE_HEADER,
    note=(
        "A cold agent uses 'X-Nonce' — the obvious standard-ish header name for "
        "request nonces.  The correct header is 'X-Acme-Nonce' — namespaced to "
        "avoid CDN conflicts, an arbitrary 2023 naming decision.  The ONMC hint "
        "names both the correct header and why 'X-Nonce' was rejected."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 28: migration_file_prefix — migrations use M{YYYYMMDD}{seq:03d}__ format
# ---------------------------------------------------------------------------

_SETUP_MIGRATION_FILE_PREFIX = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("migration_name.py").write_text('''
def make_migration_name(date_str: str, seq: int, description: str) -> str:
    \"\"\"Return the migration file prefix for the given date and sequence number.\"\"\"
    return f"V{seq}__{description}"
''')
"""

_HIDDEN_GATE_MIGRATION_FILE_PREFIX = """\
from migration_name import make_migration_name

def test_basic_format():
    name = make_migration_name("20240315", 1, "add_users_table")
    assert name == "M20240315001__add_users_table", (
        f"Expected 'M20240315001__add_users_table' but got {name!r}"
    )

def test_seq_zero_padded():
    name = make_migration_name("20240315", 42, "drop_temp_index")
    assert name == "M20240315042__drop_temp_index"

def test_date_embedded():
    name = make_migration_name("20250101", 1, "init")
    assert "20250101" in name

def test_m_prefix():
    name = make_migration_name("20240315", 1, "x")
    assert name.startswith("M"), f"Migration name must start with 'M' but got: {name!r}"

def test_no_v_prefix():
    name = make_migration_name("20240315", 1, "x")
    assert not name.startswith("V"), (
        "Deprecated Flyway-style 'V' prefix must not be used"
    )
"""

_ONMC_HINT_MIGRATION_FILE_PREFIX = """\
[ONMC Memory Context]
CONVENTION (migration runner contract — M{YYYYMMDD}{seq:03d}__ prefix):
  Migration file names MUST follow the format:
    M{YYYYMMDD}{seq:03d}__{description}
  Examples:
    M20240315001__add_users_table
    M20240315042__drop_temp_index
  Rules:
  - Prefix character is 'M' (not 'V' — that is the Flyway convention we
    rejected because our runner uses 'M' to distinguish from Flyway migrations
    in the same repo)
  - Date is 8-digit YYYYMMDD immediately after 'M' (no separator)
  - Sequence number is zero-padded to 3 digits ({seq:03d}) immediately after
    the date (no separator between date and seq)
  - Double underscore '__' separates prefix from the description
  Using 'V', plain incrementing numbers (V1, V2), or any other format causes
  the migration runner to skip the file silently.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_MIGRATION_FILE_PREFIX = """\
# Database Migration Runner — File Naming Convention

## Required Format: M{YYYYMMDD}{seq:03d}__{description}

Migration files must be named following this exact prefix format:

    M{YYYYMMDD}{seq:03d}__{description}

Examples:
- `M20240315001__add_users_table`
- `M20240315042__drop_temp_index`
- `M20250101001__init_schema`

Rules:
1. Prefix character: `M` (uppercase) — not `V` (the Flyway convention)
2. Date: 8-digit `YYYYMMDD` immediately after `M` (no separator)
3. Sequence: 3-digit zero-padded integer immediately after the date
   (no separator between date and sequence)
4. Separator: double underscore `__` between prefix and description

Background: `V` (Flyway-style) was rejected because the codebase contains
legacy Flyway migrations in a subdirectory.  The `M` prefix allows the runner
to distinguish internal migrations from Flyway migrations without separate
directories.  Any file not matching this format is silently skipped by the
migration runner.
"""

TASK_MIGRATION_FILE_PREFIX = ABTask(
    id="migration_file_prefix",
    description=(
        "The function `make_migration_name(date_str, seq, description)` in "
        "migration_name.py returns the migration file prefix for the given date "
        "(YYYYMMDD string) and sequence number.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_MIGRATION_FILE_PREFIX,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_MIGRATION_FILE_PREFIX,
    onmc_hint=_ONMC_HINT_MIGRATION_FILE_PREFIX,
    grounding_doc=_GROUNDING_DOC_MIGRATION_FILE_PREFIX,
    note=(
        "A cold agent uses Flyway-style 'V{seq}__{description}' — the standard pattern "
        "for versioned migrations.  The internal runner uses 'M{YYYYMMDD}{seq:03d}__' "
        "— both the 'M' prefix and the date-embedding are arbitrary decisions to avoid "
        "Flyway conflicts.  The exact format is un-inferrable without the runner docs."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 29: db_null_sentinel — JSON column NULLs stored as "__NULL__" string
# ---------------------------------------------------------------------------

_SETUP_DB_NULL_SENTINEL = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("db_encode.py").write_text('''
def encode_nullable(value: object) -> object:
    \"\"\"Encode a value for storage in a NOT NULL JSON column.  None values need encoding.\"\"\"
    return value
''')
"""

_HIDDEN_GATE_DB_NULL_SENTINEL = """\
from db_encode import encode_nullable

def test_none_becomes_sentinel():
    result = encode_nullable(None)
    assert result == "__NULL__", (
        f"None must be encoded as '__NULL__' but got {result!r}"
    )

def test_sentinel_is_string():
    result = encode_nullable(None)
    assert isinstance(result, str), (
        f"Sentinel for None must be a string, got {type(result).__name__}"
    )

def test_non_none_preserved():
    assert encode_nullable("hello") == "hello"
    assert encode_nullable(42) == 42
    assert encode_nullable(True) is True

def test_false_preserved():
    result = encode_nullable(False)
    assert result is False, "False must NOT be encoded as sentinel — only None"

def test_zero_preserved():
    result = encode_nullable(0)
    assert result == 0, "0 must NOT be encoded as sentinel — only None"
"""

_ONMC_HINT_DB_NULL_SENTINEL = """\
[ONMC Memory Context]
CONVENTION (JSONB column contract — None values stored as "__NULL__" sentinel):
  The "extras" JSONB column in several tables is defined as NOT NULL at the
  database level.  To represent a missing value, None MUST be encoded as the
  sentinel string "__NULL__" before storage.  JSON null (Python None) cannot
  be stored directly because the NOT NULL constraint rejects it.

  The jsonb_path_exists() queries used by the search layer also do not match
  JSON nulls — a stored null would make rows unsearchable.  The sentinel
  string "__NULL__" is recognised by the ORM layer and decoded back to None
  on read.  Any other sentinel ("null", "NONE", None itself) breaks either
  the NOT NULL constraint or the search queries.

  Non-None values (including 0, False, and empty strings) pass through
  unchanged — only Python None maps to "__NULL__".
[/ONMC Memory Context]

"""

_GROUNDING_DOC_DB_NULL_SENTINEL = """\
# JSONB Column — Null Value Encoding

## Sentinel: __NULL__

The `extras` JSONB column is defined as `NOT NULL` at the database level.
To represent a missing/absent value, `None` must be encoded as the sentinel
string `"__NULL__"` before storage.

Why JSON null cannot be used:
1. The `NOT NULL` constraint rejects JSON null directly.
2. `jsonb_path_exists()` queries used by the search layer do not match JSON
   null values — a stored null would make rows unsearchable.

The ORM layer recognises `"__NULL__"` and decodes it back to `None` on read.

Encoding rules:
- `None` → `"__NULL__"` (the only value that is encoded)
- All other values (including `0`, `False`, `""`, `[]`) pass through unchanged

Do not use `"null"`, `"NONE"`, `None` directly, or any other sentinel — only
the exact string `"__NULL__"` is recognised by the ORM decoder.
"""

TASK_DB_NULL_SENTINEL = ABTask(
    id="db_null_sentinel",
    description=(
        "The function `encode_nullable(value: object) -> object` in db_encode.py "
        "encodes a value for storage in a NOT NULL JSONB column where `None` values "
        "require special handling.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_DB_NULL_SENTINEL,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_DB_NULL_SENTINEL,
    onmc_hint=_ONMC_HINT_DB_NULL_SENTINEL,
    grounding_doc=_GROUNDING_DOC_DB_NULL_SENTINEL,
    note=(
        "A cold agent returns None unchanged (or returns None itself) — no reason to "
        "suspect a special encoding is needed.  The '__NULL__' sentinel is an arbitrary "
        "ORM convention for NOT NULL JSONB columns — two underscores on each side, exact "
        "string.  The ONMC hint names both the sentinel and the NOT NULL constraint."
    ),
    protected_paths=("test_gate.py",),
)


# ---------------------------------------------------------------------------
# Task 30: batch_max_fifty — batch endpoint validates max 50 items (not 100)
# ---------------------------------------------------------------------------

_SETUP_BATCH_MAX_FIFTY = """\
# setup.py  (executed inside temp repo)
import pathlib

pathlib.Path("batch.py").write_text('''
def validate_batch(items: list) -> None:
    \"\"\"Validate a batch of items against the service import limit.\"\"\"
    if len(items) > 100:
        raise ValueError(f"Batch too large: {len(items)} items")
''')
"""

_HIDDEN_GATE_BATCH_MAX_FIFTY = """\
import pytest
from batch import validate_batch

def test_fifty_items_allowed():
    # Exactly 50 items must NOT raise
    try:
        validate_batch(list(range(50)))
    except ValueError as exc:
        raise AssertionError(f"50 items should be within limit but raised: {exc}") from exc

def test_fifty_one_items_rejected():
    with pytest.raises(ValueError):
        validate_batch(list(range(51)))

def test_hundred_items_rejected():
    # Stub passes this — correct implementation must also reject 100
    with pytest.raises(ValueError):
        validate_batch(list(range(100)))

def test_zero_items_allowed():
    validate_batch([])  # empty batch must not raise

def test_error_message():
    with pytest.raises(ValueError):
        validate_batch(list(range(51)))
"""

_ONMC_HINT_BATCH_MAX_FIFTY = """\
[ONMC Memory Context]
CONVENTION (import service contract — hard limit of 50 items per batch):
  The batch import endpoint accepts a maximum of 50 items per request.
  Any batch with more than 50 items must raise ValueError (or return a 413
  response at the HTTP layer).  The service returns 413 for batches > 50.

  The limit was set at 50 items (not 100 or 200) because the downstream
  enrichment service processes records synchronously and times out after
  5 seconds.  Internal load testing showed 50 items complete in ~4.5s on
  p99 — 51 items routinely timeout.  The product team tried 100 as an
  initial limit but rolled back after mass timeouts in the first week.
  100 is NOT the correct limit — it was the rolled-back experiment value.
[/ONMC Memory Context]

"""

_GROUNDING_DOC_BATCH_MAX_FIFTY = """\
# Batch Import Service — Size Limit

## Maximum Batch Size: 50 Items

The batch import endpoint accepts at most **50 items** per request.  Any
request with more than 50 items must be rejected.

Enforcement: the validation layer raises `ValueError` (HTTP 413) for batches
exceeding 50 items.

Background: the limit was set at 50 after internal load testing.  The
downstream enrichment service processes records synchronously and times out
after 5 seconds.  50 items complete in ~4.5s at p99; 51+ items routinely
exceed the timeout.

The initial limit was 100 items.  This was rolled back after mass timeouts
in the first week of production use.  Do not revert to 100 or increase the
limit without re-testing the enrichment service timeout.

Examples:
- 50 items → accepted (no error)
- 51 items → `ValueError: Batch too large`
- 100 items → `ValueError: Batch too large`
"""

TASK_BATCH_MAX_FIFTY = ABTask(
    id="batch_max_fifty",
    description=(
        "The function `validate_batch(items: list) -> None` in batch.py validates "
        "a batch of items against the service import limit and raises `ValueError` "
        "if the batch is too large.  Fix it so all tests pass."
    ),
    setup_script=_SETUP_BATCH_MAX_FIFTY,
    gate_command="python -m pytest test_gate.py -x -q",
    hidden_gate_test=_HIDDEN_GATE_BATCH_MAX_FIFTY,
    onmc_hint=_ONMC_HINT_BATCH_MAX_FIFTY,
    grounding_doc=_GROUNDING_DOC_BATCH_MAX_FIFTY,
    note=(
        "A cold agent uses 100 as the limit (a reasonable and common batch size). "
        "The correct limit is 50 — a rolled-back experiment value that is now the "
        "production limit due to downstream timeout constraints.  The exact number "
        "50 is un-inferrable; the stub uses 100 (the experimental value) as the "
        "plausible-wrong default.  The ONMC hint names the limit and the reason."
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
    # --- 20 new tasks (tasks 11-30) ---
    TASK_API_RESPONSE_ENVELOPE,
    TASK_SERVICE_VERSION_HEADER,
    TASK_EVENT_SCHEMA_VERSION,
    TASK_VALIDATION_FIELD_PATH,
    TASK_PAYMENT_REF_SEPARATOR,
    TASK_REFUND_CREDIT_FLAG,
    TASK_FX_RATE_PRECISION,
    TASK_TZ_OFFSET_COMPACT_FORMAT,
    TASK_DURATION_MICROSECONDS,
    TASK_PAGINATION_TOTAL_KEY,
    TASK_CURSOR_BASE64URL_NO_PADDING,
    TASK_LOG_CONTEXT_KEY,
    TASK_AUDIT_ACTOR_PREFIX,
    TASK_FEATURE_FLAG_ENV_PREFIX,
    TASK_CONFIG_SECRET_SCOPE,
    TASK_JWT_EDDSA_ONLY,
    TASK_REQUEST_NONCE_HEADER,
    TASK_MIGRATION_FILE_PREFIX,
    TASK_DB_NULL_SENTINEL,
    TASK_BATCH_MAX_FIFTY,
]
