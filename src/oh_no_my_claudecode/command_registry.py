"""Additive command auto-discovery for the ``onmc`` CLI.

Every feature historically registered its CLI surface by editing the central
``cli.py`` hub (``app.add_typer(...)`` / ``@app.command(...)``).  With ~70 such
registrations, that file became a merge-conflict magnet: parallel per-feature
PRs all touch the same hub.

This module provides an *additive* discovery hook so a new feature can ship as a
self-contained package and register itself with **zero edits** to ``cli.py``.

Convention
----------
A feature package ``oh_no_my_claudecode/<feat>/`` exposes a module
``oh_no_my_claudecode.<feat>.commands`` defining a top-level::

    def register(app: typer.Typer) -> None:
        app.add_typer(my_app, name="<feat>")   # or @app.command(...)

At CLI build time, :func:`register_feature_commands` discovers every such module
and invokes its ``register`` callable.

Design guarantees
-----------------
- **Additive**: the existing ~70 registrations are untouched; this only *adds*.
- **Robust**: a broken or optional feature must never crash the CLI — each
  feature's import + register is wrapped in ``try/except`` (logged to stderr at
  debug level, then skipped).
- **Deterministic**: features are processed in sorted order by name.
- **Idempotent**: a given ``app`` is registered against at most once, and an
  individual feature is never registered twice.
- **Fast**: only modules named exactly ``commands`` directly under a subpackage
  are imported — no deep package walk.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import typer

logger = logging.getLogger(__name__)


class DuplicateCommandError(RuntimeError):
    """Raised when a feature registers a top-level command/group name that
    collides with one already present on the app.

    A silent collision is dangerous: Typer/click let the *last* registration win,
    so one feature can shadow another's ``onmc <name>`` with no error and no CI
    signal (this is exactly how the legacy ``pack`` command was shadowed). This
    error surfaces the collision loudly instead.
    """

_COMMANDS_MODULE = "commands"
"""Submodule name a feature must expose to be auto-discovered."""

_REGISTER_ATTR = "register"
"""Top-level callable a feature's ``commands`` module must define."""

_GUARD_ATTR = "_onmc_registered_features"
"""Attribute stamped on an ``app`` recording which features it already has.

Tracking on the ``app`` object itself (rather than a global keyed by ``id(app)``)
makes idempotency robust: a global ``id``-based set is unreliable because object
ids are reused after garbage collection, which would spuriously skip a brand-new
app that happens to reuse a freed id.
"""


def _discover_feature_names() -> list[str]:
    """Return sorted names of subpackages exposing a ``commands`` module.

    Only direct subpackages of ``oh_no_my_claudecode`` are considered, and a
    candidate qualifies only if ``<feat>.commands`` is importable as a module —
    we check via :func:`pkgutil.iter_modules` over the subpackage's path rather
    than importing eagerly, keeping discovery cheap.
    """
    import oh_no_my_claudecode

    found: list[str] = []
    for module_info in pkgutil.iter_modules(oh_no_my_claudecode.__path__):
        if not module_info.ispkg:
            continue
        feat = module_info.name
        try:
            subpkg = importlib.import_module(f"oh_no_my_claudecode.{feat}")
        except Exception as exc:  # noqa: BLE001 - a broken feature must not crash discovery
            logger.debug("skipping feature %r: import failed: %s", feat, exc)
            continue
        subpath = getattr(subpkg, "__path__", None)
        if subpath is None:
            continue
        has_commands = any(
            child.name == _COMMANDS_MODULE for child in pkgutil.iter_modules(subpath)
        )
        if has_commands:
            found.append(feat)
    return sorted(found)


def _command_name(name: str | None, callback: object) -> str | None:
    """Resolve the effective top-level name of a registered command/group.

    Typer lets ``CommandInfo.name`` / ``TyperInfo.name`` be ``None``, in which
    case the on-CLI name is derived from the callback function name (lowercased,
    underscores → hyphens). We mirror that derivation so collision detection
    matches what a user would actually type, regardless of how the feature
    declared the command.
    """
    from typer.main import get_command_name

    if name is not None:
        return get_command_name(name)
    func_name = getattr(callback, "__name__", None)
    if func_name is None:
        return None
    return get_command_name(func_name)


def _registered_names(app: typer.Typer) -> list[str]:
    """Return the effective top-level command + group names on ``app``.

    Names may repeat in the returned list when the same name was registered more
    than once — that repetition is precisely what duplicate detection keys on.
    """
    names: list[str] = []
    for cmd in app.registered_commands:
        resolved = _command_name(cmd.name, cmd.callback)
        if resolved is not None:
            names.append(resolved)
    for grp in app.registered_groups:
        resolved = _command_name(grp.name, grp.callback)
        if resolved is not None:
            names.append(resolved)
    return names


def detect_duplicate_commands(app: typer.Typer) -> list[str]:
    """Return the sorted set of top-level names registered more than once on ``app``.

    Covers both ``@app.command(...)`` leaves and ``app.add_typer(..., name=...)``
    groups. An empty list means every ``onmc <name>`` is unambiguous. Useful as a
    standalone CI assertion against the real app.
    """
    counts = Counter(_registered_names(app))
    return sorted(name for name, n in counts.items() if n > 1)


def register_feature_commands(app: typer.Typer, *, strict: bool = True) -> list[str]:
    """Discover and register self-registering feature commands onto ``app``.

    For each direct subpackage ``<feat>`` of ``oh_no_my_claudecode`` that exposes
    a module ``<feat>.commands`` with a top-level ``register(app)`` callable,
    import the module and call ``register(app)``.

    Each feature is checked for *name collisions*: before calling its
    ``register(app)`` the currently-registered top-level names are snapshotted,
    and afterwards any name the feature added that already existed is treated as a
    collision. Collisions are otherwise silent — Typer/click let the last
    registration win — so this is the only signal that two features fight over the
    same ``onmc <name>``.

    Parameters
    ----------
    app:
        The root :class:`typer.Typer` application to register commands onto.
    strict:
        When ``True`` (default), a collision raises :class:`DuplicateCommandError`
        listing the offending feature and name(s). When ``False``, the collision
        is logged to stderr and registration continues — appropriate for the live
        CLI, where a single bad feature should not crash a user's command.

    Returns
    -------
    list[str]
        Sorted names of the features successfully registered during *this* call.
        Features already registered against ``app`` (idempotency guard) and
        features that fail to import/register are omitted.

    Raises
    ------
    DuplicateCommandError
        When ``strict`` is ``True`` and a feature registers a name that collides
        with an already-registered command or group.
    """
    already: set[str] = getattr(app, _GUARD_ATTR, set())
    if not isinstance(already, set):  # pragma: no cover - defensive against name clash
        already = set()

    registered_now: list[str] = []
    for feat in _discover_feature_names():
        if feat in already:
            continue
        before = Counter(_registered_names(app))
        try:
            module = importlib.import_module(f"oh_no_my_claudecode.{feat}.{_COMMANDS_MODULE}")
            register = getattr(module, _REGISTER_ATTR, None)
            if not callable(register):
                logger.debug(
                    "skipping feature %r: %s.%s has no callable %r",
                    feat,
                    _COMMANDS_MODULE,
                    feat,
                    _REGISTER_ATTR,
                )
                continue
            register(app)
        except Exception as exc:  # noqa: BLE001 - one broken feature must never crash the CLI
            logger.debug("skipping feature %r: register failed: %s", feat, exc)
            continue

        after = Counter(_registered_names(app))
        # Names this feature newly added (multiset difference) that already
        # existed on the app are collisions.
        added = after - before
        feature_collisions = sorted(name for name in added if before.get(name, 0) > 0)
        if feature_collisions:
            message = (
                f"feature {feat!r} registers command name(s) "
                f"{feature_collisions} that already exist on the app"
            )
            if strict:
                raise DuplicateCommandError(message)
            logger.warning(message)
            print(f"onmc: WARNING: {message}", file=sys.stderr)

        already.add(feat)
        registered_now.append(feat)

    setattr(app, _GUARD_ATTR, already)
    return registered_now
