"""Provenance taint labels and opaque secret handles.

This module gives the :class:`~oh_no_my_claudecode.enforcement.monitor.ReferenceMonitor`
two vocabulary primitives:

* :class:`TaintLabel` / :class:`Tainted` — a lightweight provenance tag recording
  *where a value came from*. Content pulled from a repo, from persisted memory, or
  from a remote tool is untrusted; only a value the user typed is trusted. The
  reference monitor records this provenance in its decision trace but — crucially —
  never lets it change an authorization decision (see the injection challenge suite).

* :class:`SecretHandle` — an opaque reference to a credential. The raw value never
  appears in the object's ``repr``/``str``/``to_dict`` output: only a stable handle
  id and a last-4-style redaction are exposed. Reading the underlying value requires
  an explicit :class:`RevealCapability` obtained via :meth:`SecretHandle.grant` and
  passed by hand — there is no ambient, argument-free way to reveal it.

The module is pure and dependency-free so it can sit under the enforcement layer
without coupling it to any subsystem.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class TaintLabel(StrEnum):
    """Provenance of a value, ordered from most to least trusted."""

    USER = "user"  # the human operator typed this — trusted
    REPO = "repo"  # read from repository file content — untrusted
    MEMORY = "memory"  # replayed from persisted/learned memory — untrusted
    REMOTE = "remote"  # fetched over the network — untrusted
    TOOL = "tool"  # returned by an MCP / tool call — untrusted


#: Labels that carry *untrusted* provenance. Content bearing any of these must
#: never be able to influence an authorization decision.
UNTRUSTED_LABELS: frozenset[TaintLabel] = frozenset(
    {TaintLabel.REPO, TaintLabel.MEMORY, TaintLabel.REMOTE, TaintLabel.TOOL}
)


@dataclass(frozen=True)
class Tainted(Generic[T]):
    """A value tagged with the provenance labels of every source it flowed from."""

    value: T
    labels: frozenset[TaintLabel] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        frozen = frozenset(self.labels)
        if any(not isinstance(label, TaintLabel) for label in frozen):
            raise ValueError("labels must be TaintLabel members")
        object.__setattr__(self, "labels", frozen)

    @property
    def is_untrusted(self) -> bool:
        """True when the value carries any untrusted provenance label."""
        return bool(self.labels & UNTRUSTED_LABELS)

    @property
    def is_trusted(self) -> bool:
        """True only when every label is trusted (user-sourced)."""
        return bool(self.labels) and not self.is_untrusted

    def with_label(self, label: TaintLabel) -> Tainted[T]:
        """Return a copy carrying *label* in addition to the existing provenance."""
        if not isinstance(label, TaintLabel):
            raise ValueError("label must be a TaintLabel member")
        return Tainted(self.value, self.labels | {label})


@dataclass(frozen=True)
class RevealCapability:
    """Explicit, per-handle authority to reveal one :class:`SecretHandle`.

    Obtained only via :meth:`SecretHandle.grant`; the matching material is kept
    out of ``repr`` so logging a capability never discloses it. A capability
    minted for one handle cannot reveal any other handle.
    """

    handle_id: str
    _matcher: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.handle_id or not self._matcher:
            raise ValueError("a reveal capability must reference a handle")


class SecretHandle:
    """Opaque reference to a secret value.

    The raw value is never placed in ``repr``, ``str``, or :meth:`to_dict` — only a
    handle id and a last-4-style redaction. Call :meth:`grant` to obtain the explicit
    :class:`RevealCapability` required by :meth:`reveal`; there is no ambient reveal.
    """

    __slots__ = ("_value", "_handle_id", "_hint", "_matcher")

    def __init__(self, value: str, *, handle_id: str | None = None) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("secret value must be a non-empty string")
        if handle_id is not None and (not handle_id or "\x00" in handle_id):
            raise ValueError("handle_id must be non-empty and free of NUL bytes")
        self._value = value
        self._handle_id = handle_id or secrets.token_hex(8)
        self._hint = value[-4:] if len(value) >= 4 else "*" * len(value)
        self._matcher = secrets.token_hex(16)

    @property
    def handle_id(self) -> str:
        return self._handle_id

    @property
    def redacted(self) -> str:
        """A safe display form — the last four characters only, never the value."""
        return f"***{self._hint}"

    def grant(self) -> RevealCapability:
        """Mint the explicit capability that authorizes revealing this handle."""
        return RevealCapability(self._handle_id, self._matcher)

    def reveal(self, capability: RevealCapability) -> str:
        """Return the underlying value, only when handed a matching capability."""
        if not isinstance(capability, RevealCapability):
            raise TypeError("reveal requires an explicit RevealCapability object")
        if capability.handle_id != self._handle_id or not hmac.compare_digest(
            capability._matcher, self._matcher
        ):
            raise PermissionError("capability does not authorize this secret handle")
        return self._value

    def to_dict(self) -> dict[str, str]:
        return {"handle_id": self._handle_id, "redacted": self.redacted}

    def __repr__(self) -> str:
        return f"SecretHandle(handle_id={self._handle_id!r}, redacted={self.redacted!r})"

    __str__ = __repr__


__all__ = [
    "UNTRUSTED_LABELS",
    "RevealCapability",
    "SecretHandle",
    "Tainted",
    "TaintLabel",
]
