"""Pre-recorded fixture results for the A/B eval harness.

These fixtures represent a realistic run of the built-in task suite AND the
private-knowledge suite.  They are NOT auto-generated failures — they were
designed to reflect plausible agent behaviour on these tasks.

Honesty note
------------
- cc_alone: the cold agent sees only the task description.  On tasks with a
  plausible "wrong fix" dead-end it may apply the wrong patch.  On private-
  knowledge tasks it almost always picks the common/standard value which is
  wrong for this codebase.
- cc_onmc: the ONMC-grounded agent receives the dead-end hint and steers to
  the correct fix.  For private-knowledge tasks the hint names the exact
  rule_token and the agent applies it.

Private-knowledge fixture distribution
---------------------------------------
- ONMC wins (cc_alone=fail, cc_onmc=pass): 22 tasks — rule is company-specific
  and un-inferrable; ONMC hint provides the exact token.
- Both pass (cc_alone=pass, cc_onmc=pass): 5 tasks — rule is slightly inferable
  from domain knowledge (ROUND_HALF_EVEN, Asia/Kolkata, sha512, TLSv1.3, amount_paise).
- Both fail (cc_alone=fail, cc_onmc=fail): 3 tasks — rule is so specific that
  reliable application is unlikely even one-shot (ERR_GW_TIMEOUT_7423 numeric
  suffix; MAX_PAYMENT_RETRIES + value change; BACKOFF_BASE_SECS + value change).

IMPORTANT: These results are PRE-RECORDED for CI reproducibility.  They do NOT
prove that ONMC always wins on these tasks in a live run.  Live results vary by
model, temperature, and prompt phrasing.  To collect live results, run without
--fixture.

Built-in task notes
-------------------
- list_slice_fix: agents sometimes produce n-1 (dead-end). Fixture: alone=fail, onmc=pass.
- accumulator_init: agents reliably fix total=1. Fixture: both pass.
- word_reverse: [:-1] is a common first guess. Fixture: alone=fail, onmc=pass.
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
            "The bug is `total = 1`.  Changing it to `total = 0` fixes "
            "all three tests."
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
        "agent_output": (
            "Initialising total = 0 as the ONMC context suggests.  "
            "All tests pass."
        ),
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
            "ONMC hints confirm [:-1] is also wrong.  Removing [1:] "
            "entirely: `s.split()[::-1]`."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 1: API contracts (headers)
    # -----------------------------------------------------------------------
    # rz_request_id_header — ONMC wins: X-Request-Id is wrong, X-Rz-Request-Id is right
    {
        "task_id": "rz_request_id_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 480,
        "duration_s": 7.2,
        "agent_output": (
            "Added the request tracking header using the standard W3C name: "
            "headers['X-Request-Id'] = request_id."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_request_id_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 465,
        "duration_s": 6.8,
        "agent_output": (
            "ONMC context specifies X-Rz-Request-Id as the required header. "
            "Updated: headers['X-Rz-Request-Id'] = request_id."
        ),
        "error": None,
        "fixture": True,
    },
    # rz_service_auth_header — ONMC wins
    {
        "task_id": "rz_service_auth_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 510,
        "duration_s": 7.5,
        "agent_output": (
            "Added service authentication using a standard name: "
            "headers['Authorization'] = f'Bearer {service_token}'."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_service_auth_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 490,
        "duration_s": 7.1,
        "agent_output": (
            "ONMC confirms X-Rz-Service-Key is the correct header. "
            "Set headers['X-Rz-Service-Key'] = service_token."
        ),
        "error": None,
        "fixture": True,
    },
    # rz_idempotency_header — ONMC wins
    {
        "task_id": "rz_idempotency_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 525,
        "duration_s": 8.0,
        "agent_output": (
            "Used the RFC draft idempotency header: "
            "headers['Idempotency-Key'] = idempotency_key."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_idempotency_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 500,
        "duration_s": 7.4,
        "agent_output": (
            "ONMC specifies X-Rz-Idempotency-Id as the correct header. "
            "Updated headers accordingly."
        ),
        "error": None,
        "fixture": True,
    },
    # rz_webhook_hmac_header — ONMC wins
    {
        "task_id": "rz_webhook_hmac_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 535,
        "duration_s": 8.3,
        "agent_output": (
            "Reading signature from X-Hub-Signature-256 header "
            "(GitHub-style HMAC convention)."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_webhook_hmac_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 512,
        "duration_s": 7.9,
        "agent_output": (
            "ONMC hint: use X-Rz-Webhook-Hmac. "
            "Updated: request_headers.get('X-Rz-Webhook-Hmac', '')."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 2: Error/status conventions
    # -----------------------------------------------------------------------
    # gateway_timeout_code — BOTH FAIL: opaque numeric suffix
    {
        "task_id": "gateway_timeout_code",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 420,
        "duration_s": 6.5,
        "agent_output": (
            "Set GATEWAY_TIMEOUT = 'GW_TIMEOUT' — descriptive error code "
            "for gateway timeout events."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "gateway_timeout_code",
        "condition": "cc_onmc",
        "passed": False,
        "tokens": 435,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC mentions ERR_GW_TIMEOUT_7423 but I used ERR_GW_TIMEOUT "
            "for clarity — the 7423 suffix seems like an implementation detail."
        ),
        "error": None,
        "fixture": True,
    },
    # rate_limit_reset_header — ONMC wins
    {
        "task_id": "rate_limit_reset_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 490,
        "duration_s": 7.3,
        "agent_output": (
            "Added X-RateLimit-Reset header following GitHub/Twitter convention "
            "for rate limit reset timestamps."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rate_limit_reset_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 475,
        "duration_s": 7.0,
        "agent_output": (
            "ONMC confirms X-Rz-Rate-Limit-Reset is the SDK-expected header. "
            "Updated response_headers accordingly."
        ),
        "error": None,
        "fixture": True,
    },
    # auth_error_hint_field — ONMC wins
    {
        "task_id": "auth_error_hint_field",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 445,
        "duration_s": 6.8,
        "agent_output": (
            "Used 'message' field for the auth failure reason — "
            "standard JSON API error convention."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "auth_error_hint_field",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 430,
        "duration_s": 6.5,
        "agent_output": (
            "ONMC confirms 'error_hint' is the SDK-expected field. "
            "Updated build_auth_error to return error_hint: reason."
        ),
        "error": None,
        "fixture": True,
    },
    # error_source_value — ONMC wins
    {
        "task_id": "error_source_value",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 460,
        "duration_s": 7.0,
        "agent_output": (
            "Set source='validation_error' — describes the nature of the "
            "validation failure clearly."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "error_source_value",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 445,
        "duration_s": 6.7,
        "agent_output": (
            "ONMC specifies 'business_validation' as the routing key. "
            "Updated source field to 'business_validation'."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 3: Retry / idempotency
    # -----------------------------------------------------------------------
    # max_payment_retries — BOTH FAIL: rename + value change
    {
        "task_id": "max_payment_retries",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 390,
        "duration_s": 6.1,
        "agent_output": (
            "Updated MAX_RETRIES to 5 — common retry count for payment services."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "max_payment_retries",
        "condition": "cc_onmc",
        "passed": False,
        "tokens": 405,
        "duration_s": 6.4,
        "agent_output": (
            "Set MAX_RETRIES = 5 (value from ONMC) but did not rename the "
            "constant to MAX_PAYMENT_RETRIES — the rename was ambiguous in the hint."
        ),
        "error": None,
        "fixture": True,
    },
    # backoff_base_secs — BOTH FAIL: rename + value change
    {
        "task_id": "backoff_base_secs",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 410,
        "duration_s": 6.3,
        "agent_output": (
            "Changed BACKOFF_BASE to 0.5s — a common default for backoff. "
            "Left the constant name as BACKOFF_BASE."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "backoff_base_secs",
        "condition": "cc_onmc",
        "passed": False,
        "tokens": 425,
        "duration_s": 6.7,
        "agent_output": (
            "Set BACKOFF_BASE = 0.25 per ONMC hint but kept old name BACKOFF_BASE "
            "— the rename step was missed."
        ),
        "error": None,
        "fixture": True,
    },
    # idem_key_ttl_secs — ONMC wins
    {
        "task_id": "idem_key_ttl_secs",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 430,
        "duration_s": 6.6,
        "agent_output": (
            "Set TTL_HOURS = 168 (7 days) — reasonable for payment idempotency. "
            "Left the constant name unchanged."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "idem_key_ttl_secs",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 445,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC confirms IDEM_KEY_TTL_SECS = 604800. "
            "Renamed constant and set value to 604800."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 4: Money / rounding
    # -----------------------------------------------------------------------
    # inr_rounding_mode — BOTH PASS: banking standard is inferrable
    {
        "task_id": "inr_rounding_mode",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 520,
        "duration_s": 7.8,
        "agent_output": (
            "Changed ROUND_HALF_UP to ROUND_HALF_EVEN — banker's rounding is "
            "the standard for financial calculations to avoid systematic bias."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "inr_rounding_mode",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 505,
        "duration_s": 7.5,
        "agent_output": (
            "Applied ROUND_HALF_EVEN as required by ONMC context and banking "
            "standards.  Updated import and rounding= kwarg."
        ),
        "error": None,
        "fixture": True,
    },
    # amount_paise_field — BOTH PASS: paise convention well known in Indian fintech
    {
        "task_id": "amount_paise_field",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 460,
        "duration_s": 7.0,
        "agent_output": (
            "Renamed 'amount' to 'amount_paise' — Indian payment systems store "
            "amounts in paise (1/100 rupee) and the field name should encode the unit."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "amount_paise_field",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 445,
        "duration_s": 6.7,
        "agent_output": (
            "ONMC confirms amount_paise.  Renamed field and updated type annotation."
        ),
        "error": None,
        "fixture": True,
    },
    # gst_round_ndigits — ONMC wins
    {
        "task_id": "gst_round_ndigits",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 440,
        "duration_s": 6.7,
        "agent_output": (
            "Left GST_NDIGITS = 2 — GST amounts are typically shown to 2 decimal places."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "gst_round_ndigits",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 455,
        "duration_s": 7.0,
        "agent_output": (
            "ONMC specifies GST_ROUND_NDIGITS = 0 (nearest rupee, per CBIC). "
            "Renamed constant and set to 0."
        ),
        "error": None,
        "fixture": True,
    },
    # fx_rate_decimals — ONMC wins
    {
        "task_id": "fx_rate_decimals",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 420,
        "duration_s": 6.4,
        "agent_output": (
            "Set FX_DECIMALS = 6 (right value!) but left the constant named FX_DECIMALS."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "fx_rate_decimals",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 435,
        "duration_s": 6.7,
        "agent_output": (
            "ONMC specifies FX_RATE_DECIMALS = 6. "
            "Renamed from FX_DECIMALS and set value to 6."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 5: Date / timezone / serialisation
    # -----------------------------------------------------------------------
    # epoch_ms_field — ONMC wins
    {
        "task_id": "epoch_ms_field",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 475,
        "duration_s": 7.2,
        "agent_output": (
            "Changed field to 'timestamp: int' — integer unix timestamp. "
            "Did not use the 'epoch_ms' field name."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "epoch_ms_field",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 460,
        "duration_s": 6.9,
        "agent_output": (
            "ONMC confirms 'epoch_ms: int' is the schema field. "
            "Updated dataclass field name and type."
        ),
        "error": None,
        "fixture": True,
    },
    # billing_cycle_tz — BOTH PASS: Asia/Kolkata is standard for Indian fintech
    {
        "task_id": "billing_cycle_tz",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 440,
        "duration_s": 6.7,
        "agent_output": (
            "Changed BILLING_TZ to 'Asia/Kolkata' — the IANA timezone ID for IST.  "
            "'IST' abbreviation is ambiguous so using the full IANA identifier."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "billing_cycle_tz",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 425,
        "duration_s": 6.4,
        "agent_output": (
            "ONMC confirms Asia/Kolkata.  Set BILLING_TZ = 'Asia/Kolkata'."
        ),
        "error": None,
        "fixture": True,
    },
    # log_ts_us_field — ONMC wins
    {
        "task_id": "log_ts_us_field",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 455,
        "duration_s": 6.9,
        "agent_output": (
            "Renamed ts_s to ts_ms: int — milliseconds are common for log timestamps."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "log_ts_us_field",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 440,
        "duration_s": 6.6,
        "agent_output": (
            "ONMC confirms log_ts_us: int (microseconds).  "
            "Renamed field and updated type annotation."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 6: Pagination / cursor
    # -----------------------------------------------------------------------
    # cursor_v2_prefix — ONMC wins
    {
        "task_id": "cursor_v2_prefix",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 410,
        "duration_s": 6.3,
        "agent_output": (
            "Left CURSOR_PREFIX as 'cursor:' — standard cursor token prefix "
            "for this style of pagination."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "cursor_v2_prefix",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 395,
        "duration_s": 6.0,
        "agent_output": (
            "ONMC confirms cursor_v2: prefix.  Set CURSOR_PREFIX = 'cursor_v2:'."
        ),
        "error": None,
        "fixture": True,
    },
    # page_size_default — ONMC wins
    {
        "task_id": "page_size_default",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 420,
        "duration_s": 6.4,
        "agent_output": (
            "Changed DEFAULT_PAGE_SIZE to 25 items — good balance for API payloads. "
            "Left the constant name as DEFAULT_PAGE_SIZE."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "page_size_default",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 405,
        "duration_s": 6.1,
        "agent_output": (
            "ONMC specifies PAGE_SIZE_DEFAULT = 25. "
            "Renamed constant from DEFAULT_PAGE_SIZE and set to 25."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 7: Logging / audit
    # -----------------------------------------------------------------------
    # audit_event_namespace — ONMC wins
    {
        "task_id": "audit_event_namespace",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 430,
        "duration_s": 6.6,
        "agent_output": (
            "Set EVENT_NAMESPACE = 'payment.' — lowercase dot notation for event namespacing."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "audit_event_namespace",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 415,
        "duration_s": 6.3,
        "agent_output": (
            "ONMC confirms rz.payment. as the reverse-domain prefix. "
            "Set EVENT_NAMESPACE = 'rz.payment.'."
        ),
        "error": None,
        "fixture": True,
    },
    # payment_warn_level — BOTH FAIL: rename required, complex change
    {
        "task_id": "payment_warn_level",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 400,
        "duration_s": 6.1,
        "agent_output": (
            "Changed FAILURE_LOG_LEVEL to 'WARNING' — payment declines are "
            "expected events, not errors.  Left constant name as FAILURE_LOG_LEVEL."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "payment_warn_level",
        "condition": "cc_onmc",
        "passed": False,
        "tokens": 415,
        "duration_s": 6.4,
        "agent_output": (
            "Set FAILURE_LOG_LEVEL = 'WARNING' following ONMC hint.  "
            "Missed the rename to PAYMENT_WARN_LEVEL — hint was not explicit on the name."
        ),
        "error": None,
        "fixture": True,
    },
    # audit_schema_version — ONMC wins
    {
        "task_id": "audit_schema_version",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 410,
        "duration_s": 6.3,
        "agent_output": (
            "Updated SCHEMA_VERSION to 'v2' — the current schema version."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "audit_schema_version",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 395,
        "duration_s": 6.0,
        "agent_output": (
            "ONMC confirms 'audit-v2' with the exact hyphen-prefix format. "
            "Set SCHEMA_VERSION = 'audit-v2'."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 8: Config / feature-flags
    # -----------------------------------------------------------------------
    # rz_ff_namespace — ONMC wins
    {
        "task_id": "rz_ff_namespace",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 395,
        "duration_s": 6.0,
        "agent_output": (
            "Set FF_PREFIX = 'ff_' — lowercase, concise prefix for feature flags."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_ff_namespace",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 380,
        "duration_s": 5.8,
        "agent_output": (
            "ONMC confirms rz_ff_ as the company-namespaced prefix. "
            "Set FF_PREFIX = 'rz_ff_'."
        ),
        "error": None,
        "fixture": True,
    },
    # config_key_class — ONMC wins
    {
        "task_id": "config_key_class",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 420,
        "duration_s": 6.4,
        "agent_output": (
            "Left class name as AppConfig — it's descriptive and follows "
            "the common pattern for configuration classes."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "config_key_class",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 405,
        "duration_s": 6.1,
        "agent_output": (
            "ONMC specifies ConfigKey as the required class name. "
            "Renamed AppConfig to ConfigKey."
        ),
        "error": None,
        "fixture": True,
    },
    # rz_config_env_prefix — ONMC wins
    {
        "task_id": "rz_config_env_prefix",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 410,
        "duration_s": 6.3,
        "agent_output": (
            "Set ENV_PREFIX = 'RZ_' — company prefix for env vars. "
            "Left constant name as ENV_PREFIX."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_config_env_prefix",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 395,
        "duration_s": 6.0,
        "agent_output": (
            "ONMC confirms RZ_CONFIG_PREFIX = 'RZ_'. "
            "Renamed constant from ENV_PREFIX to RZ_CONFIG_PREFIX."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 9: Security
    # -----------------------------------------------------------------------
    # webhook_hmac_alg — BOTH PASS: sha512 is a known security best practice
    {
        "task_id": "webhook_hmac_alg",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 480,
        "duration_s": 7.3,
        "agent_output": (
            "Renamed to WEBHOOK_HMAC_ALG = 'sha512' — SHA-512 is the current "
            "recommended HMAC algorithm per NIST SP 800-107."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "webhook_hmac_alg",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 465,
        "duration_s": 7.0,
        "agent_output": (
            "ONMC confirms WEBHOOK_HMAC_ALG = 'sha512'.  Updated constant name and value."
        ),
        "error": None,
        "fixture": True,
    },
    # rz_key_id_header — ONMC wins
    {
        "task_id": "rz_key_id_header",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 440,
        "duration_s": 6.7,
        "agent_output": (
            "Set KEY_HEADER = 'X-Api-Key' — standard header for API key authentication."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "rz_key_id_header",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 425,
        "duration_s": 6.4,
        "agent_output": (
            "ONMC confirms X-Rz-Key-Id for the key identifier header. "
            "Updated KEY_HEADER = 'X-Rz-Key-Id'."
        ),
        "error": None,
        "fixture": True,
    },
    # tls_min_version — BOTH PASS: TLSv1.3 is a known best practice
    {
        "task_id": "tls_min_version",
        "condition": "cc_alone",
        "passed": True,
        "tokens": 450,
        "duration_s": 6.9,
        "agent_output": (
            "Renamed to TLS_MIN_VERSION = 'TLSv1.3' — TLS 1.3 is the current "
            "recommended minimum as per RFC 8996 (deprecating TLS 1.0 and 1.1)."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "tls_min_version",
        "condition": "cc_onmc",
        "passed": True,
        "tokens": 435,
        "duration_s": 6.6,
        "agent_output": (
            "ONMC confirms TLS_MIN_VERSION = 'TLSv1.3'.  "
            "Renamed TLS_MIN_VER to TLS_MIN_VERSION and set to TLSv1.3."
        ),
        "error": None,
        "fixture": True,
    },
    # -----------------------------------------------------------------------
    # Private-knowledge tasks — Category 10: DB / migration conventions
    # -----------------------------------------------------------------------
    # migration_prefix — BOTH FAIL: rzmig is opaque even with hint
    {
        "task_id": "migration_prefix",
        "condition": "cc_alone",
        "passed": False,
        "tokens": 380,
        "duration_s": 5.9,
        "agent_output": (
            "Set PREFIX = 'V' (Flyway convention) and MIGRATION_PREFIX = 'V'. "
            "Standard Flyway prefix is industry standard."
        ),
        "error": None,
        "fixture": True,
    },
    {
        "task_id": "migration_prefix",
        "condition": "cc_onmc",
        "passed": False,
        "tokens": 395,
        "duration_s": 6.2,
        "agent_output": (
            "ONMC says 'rzmig' but the constant is MIGRATION_PREFIX = 'rzmig' — "
            "I set PREFIX = 'rzmig' (wrong constant name)."
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
