"""H10 — sigstore keyless signing for receipt attestations.

Implements the :class:`~.attestation.Signer` protocol over sigstore-python:
ephemeral keys bound to an OIDC identity, signature logged to the Rekor
transparency log. No key management — the twenty-year blocker sigstore
removed. In CI (GitHub Actions OIDC) this signs ambiently; locally it opens
the browser identity flow.

The dependency is optional (``uv add sigstore`` / the ``attest`` extra):
without it, constructing the signer raises with the install hint instead of
degrading to a fake signature — an unsigned envelope must stay honestly
unsigned.
"""

from __future__ import annotations

from typing import Any

_INSTALL_HINT = (
    "sigstore keyless signing needs the optional dependency: "
    "`uv add sigstore` (or install the 'attest' extra)"
)


class SigstoreKeylessSigner:
    """Detached signer over DSSE PAE bytes via sigstore's keyless flow."""

    def __init__(self, *, staging: bool = False) -> None:
        try:
            # Optional extra: no stubs when absent, hence the targeted ignores.
            from sigstore.oidc import (  # type: ignore[import-not-found]
                Issuer,
                detect_credential,
            )
            from sigstore.sign import SigningContext  # type: ignore[import-not-found]
        except ImportError as exc:  # fail loud, never fake
            raise RuntimeError(_INSTALL_HINT) from exc

        self._ctx: Any = SigningContext.staging() if staging else SigningContext.production()
        # Ambient first (CI OIDC), interactive browser flow otherwise.
        token = detect_credential()
        issuer = Issuer.staging() if staging else Issuer.production()
        self._token: Any = token if token else issuer.identity_token()
        self.keyid: str = "sigstore-keyless"

    def sign(self, message: bytes) -> bytes:
        with self._ctx.signer(self._token) as active:
            result: Any = active.sign_artifact(message)
        # Identity from the short-lived cert makes the keyid meaningful.
        cert = getattr(result, "signing_certificate", None)
        if cert is not None:
            self.keyid = f"sigstore:{getattr(cert, 'subject', 'keyless')}"
        return bytes(result.signature)


__all__ = ["SigstoreKeylessSigner"]
