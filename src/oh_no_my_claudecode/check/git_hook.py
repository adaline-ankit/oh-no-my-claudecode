"""Pre-commit git hook installer for ``onmc check``.

The installed hook:
- Runs ``onmc check --staged`` (warn-only by default).
- Is idempotent: running ``--install-hook`` twice never duplicates the block.
- Preserves existing hooks: if ``.git/hooks/pre-commit`` already exists, the
  onmc block is appended (never clobbered).
- Is safe: uses ``#!/bin/sh``, no shell interpolation of user data.

Security properties:
- No shell=True subprocess usage.
- No user-controlled data is interpolated into a shell string.
- The hook script is a static constant — onmc check itself handles path args.
"""

from __future__ import annotations

from pathlib import Path

# Sentinel that identifies our block in an existing hook file.
_ONMC_MARKER = "# ONMC pre-commit check"

# The idempotency guard + hook body appended to (or written as) the hook file.
_HOOK_BLOCK = """\

# ONMC pre-commit check
# Warns about staged files that touch known invariants or dead-ends.
# Remove this block to disable.  Run with --strict to hard-block on findings.
if command -v onmc >/dev/null 2>&1; then
  onmc check --staged
fi
"""


def install_pre_commit_hook(repo_root: Path) -> tuple[Path, bool]:
    """Install (or update) the onmc pre-commit hook in *repo_root*.

    Parameters
    ----------
    repo_root:
        Absolute path to the repo root.  The hook is written to
        ``<repo_root>/.git/hooks/pre-commit``.

    Returns
    -------
    tuple[Path, bool]
        ``(hook_path, was_created)`` where *was_created* is ``True`` when a new
        hook file was written from scratch and ``False`` when the onmc block was
        appended to a pre-existing hook.

    The install is idempotent: if the hook already contains the onmc marker
    string, this function returns without modifying the file.
    """
    hook_path = repo_root / ".git" / "hooks" / "pre-commit"
    hook_path.parent.mkdir(parents=True, exist_ok=True)

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _ONMC_MARKER in existing:
            # Already installed — idempotent no-op.
            return hook_path, False
        # Append the block to the existing hook, preserving it.
        updated = existing.rstrip() + "\n" + _HOOK_BLOCK
        hook_path.write_text(updated, encoding="utf-8")
        hook_path.chmod(0o755)
        return hook_path, False

    # No existing hook — write a fresh one.
    content = "#!/bin/sh\n" + _HOOK_BLOCK
    hook_path.write_text(content, encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path, True
