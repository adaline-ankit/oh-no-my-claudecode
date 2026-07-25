"""Tests for inline secret line-redaction in retrieved context.

Secret-*shaped* strings are assembled at runtime from fragments so that no
scannable credential literal is committed to source (push-protection safe);
the assembled runtime values still exercise the redaction patterns.
"""

from __future__ import annotations

from pathlib import Path

from oh_no_my_claudecode.codeindex.exclusions import (
    REDACTION_PLACEHOLDER,
    redact_secrets,
)
from oh_no_my_claudecode.context_engine import RetrievalMode, TrustLevel
from oh_no_my_claudecode.harness_run.context import RepositoryCandidateProvider

# Assembled from fragments — never a contiguous secret literal in source.
_STRIPE_LIKE = "sk" + "_live_" + ("A1B2C3D4E5" * 3)  # api-key assignment value
_GH_TOKEN = "gh" + "p_" + ("0123456789" * 3)  # standalone provider token
_JWT = ".".join(("eyJ" + "abcd1234", "eyJ" + "payload99", "sig" + "nature01"))
_PEM_BEGIN = "-----BEGIN " + "RSA PRIVATE KEY-----"
_PEM_END = "-----END " + "RSA PRIVATE KEY-----"


def test_clean_text_is_unchanged() -> None:
    text = "def add(a, b):\n    return a + b\n"
    redacted, count = redact_secrets(text)
    assert redacted == text
    assert count == 0


def test_redacts_assignment_keeps_key_name() -> None:
    text = f'api_key = "{_STRIPE_LIKE}"\n'
    redacted, count = redact_secrets(text)
    assert count == 1
    assert _STRIPE_LIKE not in redacted
    assert "api_key" in redacted  # key name preserved for context
    assert REDACTION_PLACEHOLDER in redacted


def test_redacts_standalone_provider_tokens() -> None:
    text = f"curl -H 'Authorization: Bearer {_GH_TOKEN}'\n"
    redacted, count = redact_secrets(text)
    assert count == 1
    assert _GH_TOKEN not in redacted


def test_redacts_jwt() -> None:
    redacted, count = redact_secrets(f"token = {_JWT}\n")
    assert count >= 1
    assert _JWT not in redacted


def test_redacts_pem_private_key_block() -> None:
    body = "Zx" * 20
    text = f"{_PEM_BEGIN}\nMIIEowIBAAKCAQEA\n{body}\n{_PEM_END}\n"
    redacted, count = redact_secrets(text)
    assert count == 1
    assert body not in redacted
    assert "BEGIN PRIVATE KEY" in redacted  # framing kept


def test_provider_redacts_inline_secret_and_flags_untrusted(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text(
        'DB_HOST = "localhost"\n' f'STRIPE_SECRET = "{_STRIPE_LIKE}"\n',
        encoding="utf-8",
    )
    provider = RepositoryCandidateProvider(tmp_path)
    cands = {c.path: c for c in provider.candidates("stripe secret config", RetrievalMode.LOCAL)}
    assert "config.py" in cands
    cand = cands["config.py"]
    assert _STRIPE_LIKE not in cand.content
    assert REDACTION_PLACEHOLDER in cand.content
    # A file that carried a secret is downgraded to untrusted + tagged.
    assert cand.trust is TrustLevel.UNTRUSTED
    assert dict(cand.metadata).get("redacted") == "1"
