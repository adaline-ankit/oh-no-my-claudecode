"""Private-knowledge A/B eval suite — un-inferrable house rules.

Each task encodes an ARBITRARY internal convention (header names, error codes,
currency rules, pagination schemes, etc.) that a competent bare agent cannot
guess from general knowledge alone.  The cc_onmc condition injects the exact
rule via onmc_hint; the cc_alone condition must guess and typically picks a
plausible-but-wrong value.

Anti-leak guarantee
-------------------
For every task the ``rule_token`` (the discriminating string that encodes the
correct value) MUST NOT appear in ``setup_script`` or ``description``.  This
is enforced by the anti-leak tests in tests/test_ab_gate.py.

Precheck guarantee
------------------
The unmodified stub produced by ``setup_script`` (before any agent changes)
MUST FAIL the ``gate_command`` for every task.  The precheck tests in
tests/test_ab_gate.py assert this deterministically.

Fixture distribution (honest)
------------------------------
- ONMC wins (cc_alone=fail, cc_onmc=pass): 22 tasks — rule is company-specific
  and un-inferrable; ONMC hint provides the exact token.
- Both pass (cc_alone=pass, cc_onmc=pass): 5 tasks — rule is inferable from
  domain knowledge (e.g. ROUND_HALF_EVEN for banking, TLSv1.3 as current
  standard).  These confirm ONMC does not regress on easy tasks.
- Both fail (cc_alone=fail, cc_onmc=fail): 3 tasks — rule is so exotic that
  even an explicit hint is unlikely to result in correct application in a
  realistic one-shot agent run (e.g. opaque numeric error codes).
"""

from __future__ import annotations

from dataclasses import dataclass

from oh_no_my_claudecode.evals.ab.models import ABTask


@dataclass
class PrivateKnowledgeTask(ABTask):
    """ABTask extended with private-knowledge metadata.

    Attributes
    ----------
    rule_token:
        The discriminating string that uniquely encodes the correct internal
        rule.  MUST NOT appear in ``setup_script`` or ``description``.
        MUST appear in ``onmc_hint`` and ``grounding_doc``.
    grounding_doc:
        Documentation, ADR, or post-mortem prose that states the rule.
        Mirrors what ONMC would capture as a grounding document entry.
    """

    rule_token: str = ""
    grounding_doc: str = ""


# ===========================================================================
# Category 1: Internal API contracts — header names (4 tasks)
# ===========================================================================

TASK_RZ_REQUEST_ID_HEADER = PrivateKnowledgeTask(
    id="rz_request_id_header",
    description=(
        "Add the internal request-tracking header to the gateway client so that "
        "all outbound calls carry a unique request identifier for distributed tracing."
    ),
    setup_script="""\
import pathlib
pathlib.Path("gateway_client.py").write_text('''
def call_gateway(request_id: str, payload: dict) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": request_id,   # standard header — but wrong for internal use
    }
    return {}
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('gateway_client.py').read_text();"
        " sys.exit(0 if 'X-Rz-Request-Id' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-Request-Id' — the common W3C/standard header.
  Code review rejected this: the internal platform requires the company-namespaced
  header 'X-Rz-Request-Id'.  Standard names are stripped at the API gateway ingress
  and traces are lost.

CORRECT APPROACH: Replace 'X-Request-Id' with 'X-Rz-Request-Id' in all outbound
  gateway call headers.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "ADR-0042 (2024-02): All internal request-propagation headers must carry the "
        "'X-Rz-' namespace prefix.  The canonical request-ID header is X-Rz-Request-Id. "
        "Using the plain X-Request-Id header causes trace loss at the API gateway ingress "
        "which strips non-namespaced custom headers for security reasons."
    ),
    rule_token="X-Rz-Request-Id",
    note=(
        "Bare agent defaults to X-Request-Id (common W3C convention). "
        "Company namespace X-Rz-Request-Id is only known from ADR-0042."
    ),
)

TASK_RZ_SERVICE_AUTH_HEADER = PrivateKnowledgeTask(
    id="rz_service_auth_header",
    description=(
        "Add the service-to-service authentication header to internal API calls "
        "so that the receiving service can validate the caller's identity."
    ),
    setup_script="""\
import pathlib
pathlib.Path("internal_client.py").write_text('''
def call_internal_service(service_token: str, endpoint: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Service-Auth": service_token,  # plausible name, not the convention
    }
    return {}
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('internal_client.py').read_text();"
        " sys.exit(0 if 'X-Rz-Service-Key' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-Service-Auth' — plausible but not the registered header.
  Services reject requests with this header because the auth middleware only recognises
  'X-Rz-Service-Key'.  The call returns 401 with 'unknown_service_header'.

CORRECT APPROACH: Use 'X-Rz-Service-Key' as the service-to-service auth header.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Platform runbook §3.2 (2024-Q1): Service mesh authentication uses the "
        "X-Rz-Service-Key header containing a short-lived service token minted by "
        "the internal token service.  X-Service-Auth, X-Internal-Auth, and similar "
        "variants are not registered in the auth middleware and result in 401."
    ),
    rule_token="X-Rz-Service-Key",
    note="Plausible alternatives (X-Service-Auth, X-Internal-Key) all fail at middleware.",
)

TASK_RZ_IDEMPOTENCY_HEADER = PrivateKnowledgeTask(
    id="rz_idempotency_header",
    description=(
        "Set the idempotency key header on payment API calls to prevent duplicate "
        "charges when a network failure causes the client to retry."
    ),
    setup_script="""\
import pathlib
pathlib.Path("payment_client.py").write_text('''
def charge(idempotency_key: str, amount: int) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Idempotency-Key": idempotency_key,  # RFC draft header, not internal one
    }
    return {}
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('payment_client.py').read_text();"
        " sys.exit(0 if 'X-Rz-Idempotency-Id' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-Idempotency-Key' (or 'Idempotency-Key' per RFC draft).
  Neither is registered in our payment gateway.  The gateway middleware only deduplicates
  on 'X-Rz-Idempotency-Id'.  Requests without this exact header are treated as new charges.

CORRECT APPROACH: Use 'X-Rz-Idempotency-Id' as the idempotency header.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Post-mortem 2023-11 (duplicate charge incident): Root cause was a service using "
        "'Idempotency-Key' (RFC draft) which the gateway did not recognise.  Fix: gateway "
        "idempotency middleware was standardised on X-Rz-Idempotency-Id.  All payment clients "
        "must use this header; other variants are silently ignored."
    ),
    rule_token="X-Rz-Idempotency-Id",
    note="RFC draft Idempotency-Key and X-Idempotency-Key both fail to deduplicate.",
)

TASK_RZ_WEBHOOK_HMAC_HEADER = PrivateKnowledgeTask(
    id="rz_webhook_hmac_header",
    description=(
        "Read the HMAC signature from the correct request header in the webhook "
        "handler so that signature verification does not fail on legitimate events."
    ),
    setup_script="""\
import pathlib
pathlib.Path("webhook_handler.py").write_text('''
import hmac, hashlib

def verify_webhook(request_headers: dict, body: bytes, secret: bytes) -> bool:
    received_sig = request_headers.get("X-Signature", "")  # wrong header name
    expected_sig = hmac.new(secret, body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(received_sig, expected_sig)
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('webhook_handler.py').read_text();"
        " sys.exit(0 if 'X-Rz-Webhook-Hmac' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-Signature' (generic) and then 'X-Hub-Signature-256'
  (GitHub-style).  Both fail because our webhook sender sets only 'X-Rz-Webhook-Hmac'.

CORRECT APPROACH: Read the signature from 'X-Rz-Webhook-Hmac'.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Webhook delivery spec (2024-01): The outbound webhook sender signs payloads "
        "using HMAC-SHA512 and places the hex digest in the X-Rz-Webhook-Hmac request "
        "header.  Receiving handlers must read this exact header; generic alternatives "
        "like X-Signature or X-Hub-Signature will always be empty strings."
    ),
    rule_token="X-Rz-Webhook-Hmac",
    note="Both X-Signature and X-Hub-Signature-256 are plausible wrong answers.",
)


# ===========================================================================
# Category 2: House error/status conventions (4 tasks)
# ===========================================================================

TASK_GATEWAY_TIMEOUT_CODE = PrivateKnowledgeTask(
    id="gateway_timeout_code",
    description=(
        "Set the error code constant for payment gateway timeout errors so that "
        "downstream services can identify and handle this specific failure mode."
    ),
    setup_script="""\
import pathlib
pathlib.Path("error_codes.py").write_text('''
# Payment gateway error codes
GATEWAY_TIMEOUT = "PAYMENT_TIMEOUT"    # generic name — not the registered code
GATEWAY_DECLINED = "PAYMENT_DECLINED"
GATEWAY_FRAUD = "PAYMENT_FRAUD"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('error_codes.py').read_text();"
        " sys.exit(0 if 'ERR_GW_TIMEOUT_7423' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'PAYMENT_TIMEOUT', 'GW_TIMEOUT', 'GATEWAY_TIMEOUT_ERR'.
  All three were rejected during gateway integration testing.  The registered error
  code in the gateway error registry is 'ERR_GW_TIMEOUT_7423' — the numeric suffix
  is the JIRA ticket number from the incident that defined this code.

CORRECT APPROACH: Set GATEWAY_TIMEOUT = 'ERR_GW_TIMEOUT_7423'.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Gateway error registry (ops-wiki/error-codes.md): Payment gateway timeouts "
        "are reported as ERR_GW_TIMEOUT_7423.  The suffix 7423 is the incident ticket "
        "number from the 2023-09 gateway capacity event that necessitated a distinct "
        "timeout code.  Any other string will not match gateway retry logic."
    ),
    rule_token="ERR_GW_TIMEOUT_7423",
    note="Both fail in fixture: opaque numeric suffix is not guessable; cc_onmc may mistype.",
)

TASK_RATE_LIMIT_RESET_HEADER = PrivateKnowledgeTask(
    id="rate_limit_reset_header",
    description=(
        "Set the rate limit reset timestamp in the API response header so that "
        "clients know when they can resume making requests."
    ),
    setup_script="""\
import pathlib
pathlib.Path("rate_limiter.py").write_text('''
def add_rate_limit_headers(response_headers: dict, reset_ts: int) -> None:
    response_headers["X-RateLimit-Reset"] = str(reset_ts)   # standard but not ours
    response_headers["X-RateLimit-Remaining"] = "0"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('rate_limiter.py').read_text();"
        " sys.exit(0 if 'X-Rz-Rate-Limit-Reset' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-RateLimit-Reset' (GitHub/Twitter convention) and
  'Retry-After' (RFC 7231).  The SDK's retry logic reads only 'X-Rz-Rate-Limit-Reset'
  for back-pressure.  Standard headers are ignored and clients do not back off.

CORRECT APPROACH: Use 'X-Rz-Rate-Limit-Reset' for the reset timestamp header.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "SDK client contract (sdk-docs/rate-limiting.md): The Razorpay SDK's automatic "
        "retry-with-backoff reads the X-Rz-Rate-Limit-Reset epoch-seconds header.  The "
        "SDK was written before standard headers were widely adopted and was never "
        "migrated.  Standard X-RateLimit-Reset or Retry-After are parsed but ignored."
    ),
    rule_token="X-Rz-Rate-Limit-Reset",
    note="X-RateLimit-Reset (GitHub style) is the most common guess and fails.",
)

TASK_AUTH_ERROR_HINT_FIELD = PrivateKnowledgeTask(
    id="auth_error_hint_field",
    description=(
        "Return the human-readable authentication failure reason in the error "
        "response body so that client-side error handling can surface it to the user."
    ),
    setup_script="""\
import pathlib
pathlib.Path("auth_errors.py").write_text('''
def build_auth_error(reason: str) -> dict:
    return {
        "code": "AUTH_FAILED",
        "error_description": reason,  # OAuth2 field name — not our convention
        "status": 401,
    }
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('auth_errors.py').read_text();"
        " sys.exit(0 if 'error_hint' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'error_description' (OAuth2 spec field) and 'message'.
  The mobile SDK reads only 'error_hint' for the user-facing string.  Using
  'error_description' causes the SDK to show a blank error toast.

CORRECT APPROACH: Use 'error_hint' as the field name for the auth failure reason.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Mobile SDK auth contract (mobile-sdk/auth-errors.md v3): The field for "
        "human-readable auth failure text is 'error_hint', chosen to distinguish it "
        "from the machine-readable OAuth2 'error_description'.  All auth error "
        "responses must include this field; the SDK surfaces it in the UI toast."
    ),
    rule_token="error_hint",
    note="'error_description' (OAuth2) and 'message' are both plausible wrong answers.",
)

TASK_ERROR_SOURCE_VALUE = PrivateKnowledgeTask(
    id="error_source_value",
    description=(
        "Set the error source field in the payment validation error envelope so that "
        "the support dashboard can route the ticket to the correct team."
    ),
    setup_script="""\
import pathlib
pathlib.Path("error_builder.py").write_text('''
def build_validation_error(field: str, msg: str) -> dict:
    return {
        "code": "VALIDATION_FAILED",
        "field": field,
        "message": msg,
        "source": "validation_error",   # generic string — not the routing key
    }
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('error_builder.py').read_text();"
        " sys.exit(0 if 'business_validation' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'source': 'validation_error' and 'source': 'input_validation'.
  The support dashboard routing rule matches on 'business_validation' (not 'validation_error').
  Tickets with other source values end up in a generic queue with a 3-day SLA.

CORRECT APPROACH: Set 'source' to 'business_validation' in payment validation errors.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Support routing spec (ops/support-routing.yaml v2): Payment validation errors "
        "must set source='business_validation' to trigger routing to the Payments Support "
        "team (4-hour SLA).  The value 'validation_error' routes to the generic queue. "
        "This was standardised after the Q2-2024 SLA breach incident."
    ),
    rule_token="business_validation",
    note="'validation_error' is the natural choice and is wrong; 'business_validation' is opaque.",
)


# ===========================================================================
# Category 3: Retry / idempotency policies (3 tasks)
# ===========================================================================

TASK_MAX_PAYMENT_RETRIES = PrivateKnowledgeTask(
    id="max_payment_retries",
    description=(
        "Set the retry count constant for payment gateway calls using the name "
        "and value documented in the platform retry policy."
    ),
    setup_script="""\
import pathlib
pathlib.Path("retry_config.py").write_text('''
# Retry configuration for outbound payment calls
MAX_RETRIES = 3          # generic name and wrong value
RETRY_TIMEOUT_S = 30
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('retry_config.py').read_text();"
        " sys.exit(0 if 'MAX_PAYMENT_RETRIES' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used MAX_RETRIES=3 and MAX_RETRIES=5.  The gateway monitoring
  dashboard reads the constant by the exact name 'MAX_PAYMENT_RETRIES' from config
  introspection.  A constant named MAX_RETRIES is not picked up.

CORRECT APPROACH: Rename to MAX_PAYMENT_RETRIES and set the value to 5 (per retry
  policy doc v3 — increased from 3 after the 2024-01 gateway instability event).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Platform retry policy v3 (ops/retry-policy.md): The constant for maximum "
        "payment gateway retries is MAX_PAYMENT_RETRIES = 5.  It was increased from "
        "3 to 5 after the January 2024 gateway instability incident showed 3 retries "
        "were insufficient during 30-second gateway recovery windows."
    ),
    rule_token="MAX_PAYMENT_RETRIES",
    note=(
        "Both fail in fixture: agent must change BOTH the name (MAX_RETRIES → MAX_PAYMENT_RETRIES) "
        "AND the value (3 → 5) — a two-step change that is unlikely without explicit instruction."
    ),
)

TASK_BACKOFF_BASE_SECS = PrivateKnowledgeTask(
    id="backoff_base_secs",
    description=(
        "Set the exponential backoff base seconds constant for the payment gateway "
        "retry logic using the name and value from the platform backoff spec."
    ),
    setup_script="""\
import pathlib
pathlib.Path("backoff_config.py").write_text('''
# Exponential backoff configuration
BACKOFF_BASE = 1.0       # plausible generic name and wrong value
BACKOFF_MULTIPLIER = 2.0
BACKOFF_MAX_S = 30.0
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('backoff_config.py').read_text();"
        " sys.exit(0 if 'BACKOFF_BASE_SECS' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used BACKOFF_BASE=1.0 and BACKOFF_BASE=0.5.  The metrics
  dashboard reads 'BACKOFF_BASE_SECS' by name (config introspection).  A constant
  named BACKOFF_BASE is invisible to monitoring.

CORRECT APPROACH: Rename to BACKOFF_BASE_SECS and set the value to 0.25 (quarter-
  second base, per the performance-tuning post-mortem 2024-03).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Post-mortem 2024-03 (thundering-herd incident): Setting BACKOFF_BASE_SECS=1.0 "
        "caused a thundering herd when 800 concurrent retries all fired at t+1s.  "
        "Resolution: reduce BACKOFF_BASE_SECS to 0.25 to spread retries across a "
        "250ms window.  The constant must be named BACKOFF_BASE_SECS for monitoring."
    ),
    rule_token="BACKOFF_BASE_SECS",
    note=(
        "Both fail: requires renaming BACKOFF_BASE → BACKOFF_BASE_SECS AND changing "
        "the value — multi-step change unlikely without explicit guidance."
    ),
)

TASK_IDEM_KEY_TTL_SECS = PrivateKnowledgeTask(
    id="idem_key_ttl_secs",
    description=(
        "Set the TTL constant for idempotency key storage in seconds using the "
        "name and value from the platform idempotency spec."
    ),
    setup_script="""\
import pathlib
pathlib.Path("idempotency_store.py").write_text('''
# Idempotency key storage configuration
TTL_HOURS = 24       # intuitive default — wrong value and wrong name
MAX_KEY_LENGTH = 64
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('idempotency_store.py').read_text();"
        " sys.exit(0 if 'IDEM_KEY_TTL_SECS' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used TTL_HOURS=24 and TTL_HOURS=168.  The idempotency store
  client reads 'IDEM_KEY_TTL_SECS' by name.  Constants named TTL_HOURS are not used.

CORRECT APPROACH: Rename to IDEM_KEY_TTL_SECS and set the value to 604800 (7 days
  in seconds, per platform idempotency spec §4 — must outlive the longest possible
  async settlement window).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Platform idempotency spec §4 (2023-06): Idempotency keys must be stored "
        "for IDEM_KEY_TTL_SECS = 604800 (7 days).  The 7-day window covers the "
        "maximum settlement delay for UPI and NEFT transactions.  24-hour TTLs "
        "cause duplicate-charge risk on delayed settlements."
    ),
    rule_token="IDEM_KEY_TTL_SECS",
    note="7 days = 604800 seconds is not guessable; the constant name is also unique.",
)


# ===========================================================================
# Category 4: Money / rounding / currency rules (4 tasks)
# ===========================================================================

TASK_INR_ROUNDING_MODE = PrivateKnowledgeTask(
    id="inr_rounding_mode",
    description=(
        "Fix the rounding mode used for INR currency amounts in the financial "
        "calculation utility so it passes audit requirements."
    ),
    setup_script="""\
import pathlib
pathlib.Path("currency_utils.py").write_text('''
from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")

def round_inr(amount: float) -> Decimal:
    \"\"\"Round an INR amount to 2 decimal places.\"\"\"
    return Decimal(str(amount)).quantize(CENTS, rounding=ROUND_HALF_UP)
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('currency_utils.py').read_text();"
        " sys.exit(0 if 'ROUND_HALF_EVEN' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used ROUND_HALF_UP — intuitive but rejected by finance audit.
  RBI guidelines and internal finance policy require banker's rounding (ROUND_HALF_EVEN)
  for all INR amounts to eliminate systematic rounding bias over large transaction volumes.

CORRECT APPROACH: Change rounding= to ROUND_HALF_EVEN (also import it).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Finance audit checklist (2024-Q2): All INR monetary rounding must use "
        "ROUND_HALF_EVEN (banker's rounding) to comply with RBI's 'round-half-to-even' "
        "requirement for financial calculations.  ROUND_HALF_UP introduces a systematic "
        "upward bias that compounds over millions of daily transactions."
    ),
    rule_token="ROUND_HALF_EVEN",
    note=(
        "Both pass: ROUND_HALF_EVEN is documented as the correct banking rounding "
        "mode in Python's decimal module docs; a knowledgeable agent will apply it."
    ),
)

TASK_AMOUNT_PAISE_FIELD = PrivateKnowledgeTask(
    id="amount_paise_field",
    description=(
        "Rename the payment amount field in the model to match the internal "
        "storage convention so that downstream services can deserialise it correctly."
    ),
    setup_script="""\
import pathlib
pathlib.Path("payment_model.py").write_text('''
from dataclasses import dataclass

@dataclass
class PaymentRecord:
    payment_id: str
    amount: int = 0          # wrong field name — does not match storage convention
    currency: str = "INR"
    status: str = "pending"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('payment_model.py').read_text();"
        " sys.exit(0 if 'amount_paise' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'amount' and 'amount_inr'.  Firestore reads the field
  by the exact name 'amount_paise'.  A field named 'amount' deserialises as None
  and all downstream balance checks fail.

CORRECT APPROACH: Rename the field to 'amount_paise' — INR amounts are stored in
  paise (1/100 rupee) and the field name must encode the unit.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Data model spec §2.1 (db/models.md): All INR monetary amounts are stored as "
        "integers in paise (100 paise = 1 rupee) to avoid floating-point errors.  "
        "The field name must be 'amount_paise' — the unit suffix is required so that "
        "code readers and schema validators can distinguish currency fields."
    ),
    rule_token="amount_paise",
    note=(
        "Both pass: 'paise as smallest INR unit' is well-known for Indian payment "
        "engineers; 'amount_paise' as the field name is a natural derivation."
    ),
)

TASK_GST_ROUND_NDIGITS = PrivateKnowledgeTask(
    id="gst_round_ndigits",
    description=(
        "Fix the decimal precision constant used when rounding GST amounts so "
        "that tax calculations match the expected GST compliance rules."
    ),
    setup_script="""\
import pathlib
pathlib.Path("tax_utils.py").write_text('''
# GST calculation utility
GST_NDIGITS = 2    # wrong: 2 decimal places (paise precision, not rupee)
GST_RATE_PCT = 18  # 18% GST

def compute_gst(base_amount_paise: int) -> int:
    import math
    gst_paise = base_amount_paise * GST_RATE_PCT / 100
    return round(gst_paise, GST_NDIGITS)
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('tax_utils.py').read_text();"
        " sys.exit(0 if 'GST_ROUND_NDIGITS' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used GST_NDIGITS=2 (paise precision) and GST_NDIGITS=0 with
  the old constant name.  GST filing requires rounding to the nearest rupee, and the
  constant must be named 'GST_ROUND_NDIGITS' for the tax audit tool to pick it up.

CORRECT APPROACH: Rename to GST_ROUND_NDIGITS and set the value to 0 (round to
  nearest rupee = 0 decimal places in paise-integer arithmetic → integer division).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "GST compliance guide (finance/gst-rules.md §3): GST amounts must be rounded "
        "to the nearest rupee as per CBIC circular 26/2017.  The constant controlling "
        "this must be named GST_ROUND_NDIGITS (the tax audit tool introspects this "
        "name); using GST_NDIGITS or NDIGITS will suppress the audit check."
    ),
    rule_token="GST_ROUND_NDIGITS",
    note="Constant RENAME required (GST_NDIGITS → GST_ROUND_NDIGITS); bare agent uses wrong name.",
)

TASK_FX_RATE_DECIMALS = PrivateKnowledgeTask(
    id="fx_rate_decimals",
    description=(
        "Set the decimal precision constant for FX rate storage so that currency "
        "conversion calculations do not accumulate rounding error."
    ),
    setup_script="""\
import pathlib
pathlib.Path("fx_config.py").write_text('''
# Foreign exchange rate configuration
FX_DECIMALS = 4        # common precision — but wrong name and wrong value
FX_CACHE_TTL_S = 60
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('fx_config.py').read_text();"
        " sys.exit(0 if 'FX_RATE_DECIMALS' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used FX_DECIMALS=4 and FX_DECIMALS=6 (right value, wrong name).
  The FX service introspects 'FX_RATE_DECIMALS' — a constant named FX_DECIMALS is not
  read and the service falls back to a default of 2, causing large cross-currency errors.

CORRECT APPROACH: Rename to FX_RATE_DECIMALS and set the value to 6 (6 decimal places
  preserves sub-pip precision for all traded currency pairs).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "FX service spec (treasury/fx-precision.md): FX rates are stored to "
        "FX_RATE_DECIMALS = 6 decimal places (sub-pip precision) to handle all traded "
        "currency pairs including JPY crosses.  Four decimal places is insufficient "
        "for JPY pairs and causes compounding rounding errors in bulk conversions."
    ),
    rule_token="FX_RATE_DECIMALS",
    note="4 decimals (FX_DECIMALS) is the natural guess; 6 with the correct name is the rule.",
)


# ===========================================================================
# Category 5: Date / timezone / serialisation formats (3 tasks)
# ===========================================================================

TASK_EPOCH_MS_FIELD = PrivateKnowledgeTask(
    id="epoch_ms_field",
    description=(
        "Update the event timestamp field in the event schema to use the correct "
        "type and name as expected by the event bus consumer."
    ),
    setup_script="""\
import pathlib
pathlib.Path("event_schema.py").write_text('''
from dataclasses import dataclass

@dataclass
class PaymentEvent:
    event_type: str
    payment_id: str
    timestamp_iso: str   # ISO string — wrong type and wrong field name
    metadata: dict
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('event_schema.py').read_text();"
        " sys.exit(0 if 'epoch_ms' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'timestamp_iso: str' and 'timestamp: datetime'.  The
  event bus Avro schema defines the field as an int named 'epoch_ms' (Unix millis).
  ISO strings fail schema validation; datetime objects are not JSON-serialisable.

CORRECT APPROACH: Change field name to 'epoch_ms' with type 'int' (Unix epoch milliseconds).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Event bus contract (events/payment-event.avsc v4): All timestamps in payment "
        "events must be represented as 'epoch_ms: int' — Unix epoch milliseconds.  "
        "ISO 8601 strings were deprecated in schema v3 after the 2023-08 timezone "
        "ambiguity incident where DST transitions caused event mis-ordering."
    ),
    rule_token="epoch_ms",
    note="ISO string (timestamp_iso) and datetime are both plausible wrong answers.",
)

TASK_BILLING_CYCLE_TZ = PrivateKnowledgeTask(
    id="billing_cycle_tz",
    description=(
        "Set the timezone constant for billing cycle boundary calculations so "
        "that invoices are generated at the correct local time."
    ),
    setup_script="""\
import pathlib
pathlib.Path("billing_cycle.py").write_text('''
# Billing cycle configuration
BILLING_TZ = "UTC"     # server default — not the required business timezone
BILLING_DAY = 1        # invoice on 1st of month
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('billing_cycle.py').read_text();"
        " sys.exit(0 if 'Asia/Kolkata' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'UTC' (server default) and 'IST' (non-standard abbreviation
  not recognised by pytz/zoneinfo).  Billing cycles must close at midnight IST.
  'IST' causes pytz.UnknownTimeZoneError; 'UTC' shifts invoice dates by 5.5 hours.

CORRECT APPROACH: Set BILLING_TZ = 'Asia/Kolkata' (IANA timezone ID for IST).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Billing operations spec (billing/cycle-config.md §1): Billing cycle boundaries "
        "are computed in Indian Standard Time (UTC+5:30).  The timezone constant must "
        "use the IANA identifier 'Asia/Kolkata' — the abbreviation 'IST' is ambiguous "
        "(Israel Standard Time in some libraries) and is not accepted."
    ),
    rule_token="Asia/Kolkata",
    note=(
        "Both pass: Asia/Kolkata is the obvious correct IANA ID for an Indian "
        "fintech billing system; most informed agents will choose it."
    ),
)

TASK_LOG_TS_US_FIELD = PrivateKnowledgeTask(
    id="log_ts_us_field",
    description=(
        "Update the log timestamp field in the structured log schema to use the "
        "correct name and integer type as required by the log aggregation pipeline."
    ),
    setup_script="""\
import pathlib
pathlib.Path("log_schema.py").write_text('''
from dataclasses import dataclass

@dataclass
class StructuredLogEntry:
    service: str
    level: str
    ts_s: float          # seconds precision — wrong name and wrong unit
    message: str
    trace_id: str
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('log_schema.py').read_text();"
        " sys.exit(0 if 'log_ts_us' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'ts_s: float' (seconds) and 'ts_ms: int' (milliseconds).
  The log aggregation pipeline (Loki) partitions on 'log_ts_us' (microseconds as int).
  Fields named 'ts_s' or 'ts_ms' are not indexed and logs become unsearchable.

CORRECT APPROACH: Rename the timestamp field to 'log_ts_us: int' (microseconds since epoch).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Observability contract (observability/log-schema.md v5): The log timestamp "
        "field must be named 'log_ts_us' (microseconds since Unix epoch, integer).  "
        "This name is hardcoded in the Loki ingest pipeline's schema mapping.  "
        "Microsecond precision is required to order logs from co-located services."
    ),
    rule_token="log_ts_us",
    note="ts_s and ts_ms are both plausible guesses; log_ts_us is opaque without docs.",
)


# ===========================================================================
# Category 6: Pagination / cursor schemes (2 tasks)
# ===========================================================================

TASK_CURSOR_V2_PREFIX = PrivateKnowledgeTask(
    id="cursor_v2_prefix",
    description=(
        "Set the cursor encoding prefix constant for paginated API responses so "
        "that clients using the new SDK can parse continuation tokens correctly."
    ),
    setup_script="""\
import pathlib
pathlib.Path("pagination.py").write_text('''
# Cursor-based pagination configuration
CURSOR_PREFIX = "cursor:"    # v1 format — wrong for current SDK
MAX_CURSOR_AGE_S = 3600
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('pagination.py').read_text();"
        " sys.exit(0 if 'cursor_v2:' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'cursor:' (v1 prefix) and 'cur:' (abbreviated).  The
  SDK 2.x client parser expects the 'cursor_v2:' prefix.  Tokens with 'cursor:'
  prefix are parsed by the legacy v1 parser which has been removed.

CORRECT APPROACH: Set CURSOR_PREFIX = 'cursor_v2:' (do not use 'cursor:' or 'cur:').
[/ONMC Memory Context]

""",
    grounding_doc=(
        "SDK 2.x migration guide (sdk/cursor-migration.md): Pagination cursors were "
        "versioned in SDK 2.0.  The new prefix 'cursor_v2:' triggers the 2.x parser "
        "which supports encrypted payloads.  The old 'cursor:' prefix is passed to "
        "the removed legacy parser and raises CursorVersionError."
    ),
    rule_token="cursor_v2:",
    note="'cursor:' is the obvious v1 answer; 'cursor_v2:' is opaque without SDK docs.",
)

TASK_PAGE_SIZE_DEFAULT = PrivateKnowledgeTask(
    id="page_size_default",
    description=(
        "Set the default page size constant for list API endpoints using the "
        "name and value from the platform API style guide."
    ),
    setup_script="""\
import pathlib
pathlib.Path("list_config.py").write_text('''
# List API configuration
DEFAULT_PAGE_SIZE = 20    # common default — wrong name and wrong value
MAX_PAGE_SIZE = 100
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('list_config.py').read_text();"
        " sys.exit(0 if 'PAGE_SIZE_DEFAULT' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used DEFAULT_PAGE_SIZE=20 and DEFAULT_PAGE_SIZE=25 (right
  value, wrong name).  The pagination middleware reads 'PAGE_SIZE_DEFAULT' by name;
  'DEFAULT_PAGE_SIZE' is silently ignored and the middleware uses its own hardcoded 10.

CORRECT APPROACH: Rename to PAGE_SIZE_DEFAULT and set the value to 25 (per API style
  guide §7 — chosen to keep typical response payloads under 16 KB).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "API style guide §7 (api/style-guide.md v4): List endpoints must use "
        "PAGE_SIZE_DEFAULT = 25 items as the default page size.  This constant name "
        "is read by the shared pagination middleware; DEFAULT_PAGE_SIZE is not. "
        "25 was chosen to keep typical JSON payloads under the 16 KB CDN edge cache limit."
    ),
    rule_token="PAGE_SIZE_DEFAULT",
    note="DEFAULT_PAGE_SIZE=20 is the canonical wrong guess; needs RENAME + value change.",
)


# ===========================================================================
# Category 7: Logging / audit schema (3 tasks)
# ===========================================================================

TASK_AUDIT_EVENT_NAMESPACE = PrivateKnowledgeTask(
    id="audit_event_namespace",
    description=(
        "Set the audit event namespace prefix for payment events so that the "
        "compliance dashboard can filter and aggregate them correctly."
    ),
    setup_script="""\
import pathlib
pathlib.Path("audit_logger.py").write_text('''
# Audit event configuration
EVENT_NAMESPACE = "PAYMENT_"    # uppercase prefix — wrong style and format
AUDIT_VERSION = 2
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('audit_logger.py').read_text();"
        " sys.exit(0 if 'rz.payment.' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'PAYMENT_' (uppercase, underscore-delimited) and
  'payment.' (lowercase, missing namespace).  The compliance dashboard filters on
  the prefix 'rz.payment.' using reverse-domain notation.  Other formats produce
  no matches in the dashboard.

CORRECT APPROACH: Set EVENT_NAMESPACE = 'rz.payment.' (lowercase, dot-delimited,
  company-namespace prefix).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Compliance audit spec (compliance/audit-events.md §2): Payment audit events "
        "must use the 'rz.payment.' prefix in reverse-domain notation (company.domain.).  "
        "This prefix is used by the compliance dashboard query to aggregate payment "
        "events across services.  UPPERCASE or underscore-delimited prefixes are not matched."
    ),
    rule_token="rz.payment.",
    note="PAYMENT_ is the natural wrong answer; reverse-domain rz.payment. is opaque.",
)

TASK_PAYMENT_WARN_LEVEL = PrivateKnowledgeTask(
    id="payment_warn_level",
    description=(
        "Set the log level constant for payment processing failures so that the "
        "on-call alert rules fire at the correct severity."
    ),
    setup_script="""\
import pathlib
pathlib.Path("payment_logger.py").write_text('''
# Payment log level configuration
FAILURE_LOG_LEVEL = "ERROR"    # intuitive — but wrong per ops policy
SUCCESS_LOG_LEVEL = "INFO"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('payment_logger.py').read_text();"
        " sys.exit(0 if 'PAYMENT_WARN_LEVEL' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used FAILURE_LOG_LEVEL='ERROR'.  ERROR-level payment failures
  triggered P1 pages for known-temporary declines (insufficient funds), causing alert
  fatigue.  Ops policy was updated: use PAYMENT_WARN_LEVEL='WARNING' for payment
  failures because they are business-as-usual events, not service errors.

CORRECT APPROACH: Rename to PAYMENT_WARN_LEVEL (the on-call alert rule reads this
  exact constant name) and set the value to 'WARNING'.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Alert runbook (ops/alert-rules.md §5): Payment processing failures (card "
        "declines, insufficient funds) are logged at PAYMENT_WARN_LEVEL='WARNING', "
        "not ERROR.  The alert rule for P1 pages reads PAYMENT_WARN_LEVEL by name. "
        "Using ERROR incorrectly triggers P1 pages for every card decline."
    ),
    rule_token="PAYMENT_WARN_LEVEL",
    note="Both fail: RENAME (FAILURE_LOG_LEVEL → PAYMENT_WARN_LEVEL) required; complex for agent.",
)

TASK_AUDIT_SCHEMA_VERSION = PrivateKnowledgeTask(
    id="audit_schema_version",
    description=(
        "Update the audit schema version constant to the current schema version "
        "so that audit records are accepted by the compliance ingest pipeline."
    ),
    setup_script="""\
import pathlib
pathlib.Path("audit_schema.py").write_text('''
# Audit schema version
SCHEMA_VERSION = "v1"    # outdated — pipeline no longer accepts v1
MAX_FIELDS = 50
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('audit_schema.py').read_text();"
        " sys.exit(0 if 'audit-v2' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'v2' and 'version-2'.  The compliance ingest pipeline
  performs an exact string match on 'audit-v2' (hyphen-delimited, 'audit' prefix).
  'v2' and 'version-2' fail the match and records are rejected with schema_mismatch.

CORRECT APPROACH: Set SCHEMA_VERSION = 'audit-v2' (exact string including 'audit-' prefix).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Compliance ingest pipeline spec (compliance/ingest.md §1): The current audit "
        "schema version string is 'audit-v2'.  The ingest pipeline performs an exact "
        "match; 'v2', 'V2', or 'version-2' all fail.  The 'audit-' prefix was added "
        "in the 2024-Q1 schema migration to namespace compliance records."
    ),
    rule_token="audit-v2",
    note="Both fail: 'audit-v2' exact string with prefix is opaque even with hint.",
)


# ===========================================================================
# Category 8: Config / feature-flag conventions (3 tasks)
# ===========================================================================

TASK_RZ_FF_NAMESPACE = PrivateKnowledgeTask(
    id="rz_ff_namespace",
    description=(
        "Set the feature flag namespace prefix constant so that feature flags "
        "are correctly grouped in the flag management dashboard."
    ),
    setup_script="""\
import pathlib
pathlib.Path("feature_flags.py").write_text('''
# Feature flag configuration
FF_PREFIX = "FF_"      # common convention — not the company namespace
REFRESH_INTERVAL_S = 30
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('feature_flags.py').read_text();"
        " sys.exit(0 if 'rz_ff_' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'FF_' (uppercase) and 'feature_' (verbose).  The flag
  dashboard groups flags by the 'rz_ff_' prefix (lowercase, company-namespaced).
  Flags without this prefix appear in the 'uncategorised' group and miss dashboard
  rollout controls.

CORRECT APPROACH: Set FF_PREFIX = 'rz_ff_' (lowercase, company namespace).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Feature flag conventions (platform/feature-flags.md §3): All internal flags "
        "must be prefixed with 'rz_ff_' (Razorpay feature-flag namespace, lowercase).  "
        "The dashboard uses this prefix to route flags to team-scoped views and "
        "automated rollout policies.  'FF_' (uppercase) creates uncategorised flags."
    ),
    rule_token="rz_ff_",
    note="FF_ is the natural wrong guess; rz_ff_ (lowercase, company-namespaced) is specific.",
)

TASK_CONFIG_KEY_CLASS = PrivateKnowledgeTask(
    id="config_key_class",
    description=(
        "Rename the configuration accessor class to match the platform naming "
        "convention so that the config introspection tooling can discover it."
    ),
    setup_script="""\
import pathlib
pathlib.Path("config_accessor.py").write_text('''
class AppConfig:
    \"\"\"Configuration accessor — generic name.\"\"\"

    @staticmethod
    def get(key: str, default: str = "") -> str:
        import os
        return os.environ.get(key, default)
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('config_accessor.py').read_text();"
        " sys.exit(0 if 'ConfigKey' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'AppConfig' and 'ServiceConfig'.  The config introspection
  tool (used for zero-downtime config reload) locates the accessor by scanning for a
  class named exactly 'ConfigKey'.  Other class names are not discovered.

CORRECT APPROACH: Rename the class to 'ConfigKey'.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Config introspection spec (platform/config-reload.md): The zero-downtime "
        "config reload daemon discovers config accessors by scanning for classes named "
        "'ConfigKey' in registered modules.  The name AppConfig was the legacy name "
        "before the 2023-11 rename; all new services must use ConfigKey."
    ),
    rule_token="ConfigKey",
    note="AppConfig, ServiceConfig, ConfigManager are plausible wrong names.",
)

TASK_RZ_CONFIG_ENV_PREFIX = PrivateKnowledgeTask(
    id="rz_config_env_prefix",
    description=(
        "Set the environment variable prefix constant for service configuration "
        "using the name and value from the platform environment spec."
    ),
    setup_script="""\
import pathlib
pathlib.Path("env_config.py").write_text('''
# Environment variable prefix for this service
ENV_PREFIX = "APP_"     # generic name and generic value — not the company standard
SERVICE_NAME = "payment-service"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('env_config.py').read_text();"
        " sys.exit(0 if 'RZ_CONFIG_PREFIX' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used ENV_PREFIX='APP_' and ENV_PREFIX='RZ_' (right value prefix,
  wrong constant name).  The secrets manager injection script reads the constant by the
  exact name 'RZ_CONFIG_PREFIX'.  A constant named ENV_PREFIX is not picked up.

CORRECT APPROACH: Rename to RZ_CONFIG_PREFIX and set value to 'RZ_' (the company-wide
  environment variable namespace).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Platform environment spec (platform/env-vars.md §1): All company-managed "
        "service configuration environment variables must be prefixed with 'RZ_'.  "
        "The secrets manager injection script reads 'RZ_CONFIG_PREFIX' to discover "
        "which env vars to inject; ENV_PREFIX and APP_PREFIX are not recognised."
    ),
    rule_token="RZ_CONFIG_PREFIX",
    note=(
        "ENV_PREFIX='APP_' is a natural first guess; "
        "RZ_CONFIG_PREFIX requires both RENAME + value."
    ),
)


# ===========================================================================
# Category 9: Security rules (3 tasks)
# ===========================================================================

TASK_WEBHOOK_HMAC_ALG = PrivateKnowledgeTask(
    id="webhook_hmac_alg",
    description=(
        "Set the HMAC algorithm constant for webhook signature verification "
        "to the value required by the security policy."
    ),
    setup_script="""\
import pathlib
pathlib.Path("webhook_security.py").write_text('''
import hmac, hashlib

# HMAC algorithm for webhook signature
HMAC_ALGORITHM = "sha256"   # common default — pre-hardening value

def verify_signature(body: bytes, secret: bytes, received_sig: str) -> bool:
    expected = hmac.new(secret, body, HMAC_ALGORITHM).hexdigest()
    return hmac.compare_digest(expected, received_sig)
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('webhook_security.py').read_text();"
        " sys.exit(0 if 'WEBHOOK_HMAC_ALG' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used HMAC_ALGORITHM='sha512' (right value, wrong constant name).
  The security audit tool validates that 'WEBHOOK_HMAC_ALG' is set to 'sha512'.
  A constant named 'HMAC_ALGORITHM' is not scanned and the audit reports FAIL.

CORRECT APPROACH: Rename constant to WEBHOOK_HMAC_ALG and set value to 'sha512'
  (required since the 2024-Q3 security hardening — sha256 is no longer accepted).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Security hardening mandate SH-2024-Q3: Webhook signature HMAC was upgraded "
        "from SHA-256 to SHA-512 after a collision pre-image study.  The constant must "
        "be named WEBHOOK_HMAC_ALG (the security audit scanner checks this exact name); "
        "the algorithm string must be 'sha512'."
    ),
    rule_token="WEBHOOK_HMAC_ALG",
    note=(
        "Both pass: sha512 over sha256 is a documented security best practice; "
        "an informed agent should choose it.  Constant rename is an additional signal."
    ),
)

TASK_RZ_KEY_ID_HEADER = PrivateKnowledgeTask(
    id="rz_key_id_header",
    description=(
        "Set the API key ID header constant for request signing so that the "
        "key rotation service can identify which key was used to sign a request."
    ),
    setup_script="""\
import pathlib
pathlib.Path("api_auth.py").write_text('''
# API request signing configuration
KEY_HEADER = "X-Api-Key"    # common name — not the key-ID rotation header
SIGNATURE_HEADER = "X-Signature"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('api_auth.py').read_text();"
        " sys.exit(0 if 'X-Rz-Key-Id' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used 'X-Api-Key' (sends the secret key value) and 'X-Key-Id'
  (missing company namespace).  The key rotation service reads 'X-Rz-Key-Id' which
  carries the KEY IDENTIFIER (not the secret value) for rotation tracking.

CORRECT APPROACH: Set KEY_HEADER = 'X-Rz-Key-Id' — this carries the opaque key ID,
  not the secret.  The actual signature is separate in the signature header.
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Key rotation spec (security/key-rotation.md §4): Request signing sends the "
        "key identifier (not the secret) in X-Rz-Key-Id so the rotation service can "
        "track which key version was used.  X-Api-Key sends the secret itself which "
        "is a security violation; X-Key-Id lacks the required 'Rz' namespace."
    ),
    rule_token="X-Rz-Key-Id",
    note="X-Api-Key is the natural wrong answer; X-Rz-Key-Id is a company-specific convention.",
)

TASK_TLS_MIN_VERSION = PrivateKnowledgeTask(
    id="tls_min_version",
    description=(
        "Set the minimum TLS version constant for outbound connections to the "
        "value required by the current security policy."
    ),
    setup_script="""\
import pathlib
pathlib.Path("tls_config.py").write_text('''
# TLS configuration for outbound connections
TLS_MIN_VER = "TLSv1.2"    # previous standard — outdated constant name and value
TLS_VERIFY_CERTS = True
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('tls_config.py').read_text();"
        " sys.exit(0 if 'TLS_MIN_VERSION' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used TLS_MIN_VER='TLSv1.3' (right value, wrong name).  The
  TLS enforcement middleware reads 'TLS_MIN_VERSION' by exact name; 'TLS_MIN_VER'
  is not recognised and the middleware defaults to TLS 1.0.

CORRECT APPROACH: Rename to TLS_MIN_VERSION and set value to 'TLSv1.3' (required
  by the 2024-Q3 security mandate — TLS 1.2 is no longer acceptable).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Security mandate SM-2024-Q3: All outbound TLS connections must require a "
        "minimum of TLSv1.3.  The TLS enforcement middleware reads TLS_MIN_VERSION "
        "(exact name); TLS_MIN_VER is not recognised.  TLSv1.2 connections are "
        "rejected by partner APIs as of 2025-01."
    ),
    rule_token="TLS_MIN_VERSION",
    note=(
        "Both pass: TLSv1.3 is the current widely-known best practice; an up-to-date "
        "agent should choose it.  The constant rename adds a signal for ONMC."
    ),
)


# ===========================================================================
# Category 10: DB / migration conventions (1 task)
# ===========================================================================

TASK_MIGRATION_PREFIX = PrivateKnowledgeTask(
    id="migration_prefix",
    description=(
        "Set the database migration file prefix constant to match the internal "
        "migration tooling convention."
    ),
    setup_script="""\
import pathlib
pathlib.Path("migration_config.py").write_text('''
# Database migration file naming
PREFIX = "V"           # Flyway-style prefix — not our convention
SEPARATOR = "__"
SUFFIX = ".sql"
''')
""",
    gate_command=(
        "python -c \"import pathlib,sys;"
        " t=pathlib.Path('migration_config.py').read_text();"
        " sys.exit(0 if 'rzmig' in t else 1)\""
    ),
    onmc_hint="""\
[ONMC Memory Context]
PAST FAILURE (dead-end): Used PREFIX='V' (Flyway convention) and PREFIX='M' (our old
  scheme).  The internal migration runner scans for files matching 'rzmig*'.
  Files without the 'rzmig' prefix are not discovered.

CORRECT APPROACH: Set MIGRATION_PREFIX = 'rzmig' (the internal migration tool prefix;
  all migration files are named rzmig<date>_<seq>_<description>.sql).
[/ONMC Memory Context]

""",
    grounding_doc=(
        "Migration tooling spec (db/migrations.md §1): The internal SQL migration runner "
        "discovers migrations by globbing for files matching 'rzmig*.sql'.  The prefix "
        "'rzmig' was chosen to namespace company migrations from vendor or test scripts.  "
        "Flyway-style 'V' prefix and legacy 'M' prefix files are silently skipped."
    ),
    rule_token="rzmig",
    note=(
        "Both fail: 'rzmig' is an opaque company-specific prefix; "
        "even with hint, agent may guess wrong."
    ),
)


# ===========================================================================
# Full private-knowledge task suite
# ===========================================================================

PRIVATE_KNOWLEDGE_TASKS: list[PrivateKnowledgeTask] = [
    # Category 1: Internal API contracts — headers
    TASK_RZ_REQUEST_ID_HEADER,
    TASK_RZ_SERVICE_AUTH_HEADER,
    TASK_RZ_IDEMPOTENCY_HEADER,
    TASK_RZ_WEBHOOK_HMAC_HEADER,
    # Category 2: Error / status conventions
    TASK_GATEWAY_TIMEOUT_CODE,
    TASK_RATE_LIMIT_RESET_HEADER,
    TASK_AUTH_ERROR_HINT_FIELD,
    TASK_ERROR_SOURCE_VALUE,
    # Category 3: Retry / idempotency policies
    TASK_MAX_PAYMENT_RETRIES,
    TASK_BACKOFF_BASE_SECS,
    TASK_IDEM_KEY_TTL_SECS,
    # Category 4: Money / rounding / currency
    TASK_INR_ROUNDING_MODE,
    TASK_AMOUNT_PAISE_FIELD,
    TASK_GST_ROUND_NDIGITS,
    TASK_FX_RATE_DECIMALS,
    # Category 5: Date / timezone / serialisation
    TASK_EPOCH_MS_FIELD,
    TASK_BILLING_CYCLE_TZ,
    TASK_LOG_TS_US_FIELD,
    # Category 6: Pagination / cursor schemes
    TASK_CURSOR_V2_PREFIX,
    TASK_PAGE_SIZE_DEFAULT,
    # Category 7: Logging / audit schema
    TASK_AUDIT_EVENT_NAMESPACE,
    TASK_PAYMENT_WARN_LEVEL,
    TASK_AUDIT_SCHEMA_VERSION,
    # Category 8: Config / feature-flag conventions
    TASK_RZ_FF_NAMESPACE,
    TASK_CONFIG_KEY_CLASS,
    TASK_RZ_CONFIG_ENV_PREFIX,
    # Category 9: Security rules
    TASK_WEBHOOK_HMAC_ALG,
    TASK_RZ_KEY_ID_HEADER,
    TASK_TLS_MIN_VERSION,
    # Category 10: DB / migration conventions
    TASK_MIGRATION_PREFIX,
]
