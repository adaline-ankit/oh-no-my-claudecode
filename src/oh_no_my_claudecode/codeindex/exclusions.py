"""Deterministic exclusion rules for the code index.

A file is excluded when it:

1. Lives under a vendor / generated / cache / VCS directory.
2. Has an extension that indicates a binary, lock, or generated artefact.
3. Matches a path-pattern that suggests private credentials or keys.
4. Contains a content pattern that looks like a bare secret (e.g. a hard-coded
   API key or password assignment).  This heuristic uses a simple regex scan of
   up to the first 4 KiB — it never loads the full file for this check.

All rules are fully deterministic: the same file always produces the same
decision given the same content on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Directory-level exclusions
# ---------------------------------------------------------------------------

EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        # VCS
        ".git",
        # Python / Node venvs and caches
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        # onmc own state dir
        ".onmc",
        # JS / Node deps
        "node_modules",
        # Build output
        "build",
        "dist",
        ".eggs",
        "site-packages",
        # Vendor / generated
        "vendor",
        "third_party",
        "generated",
        "auto_generated",
        "__generated__",
        # Common CI / tooling
        ".terraform",
        ".serverless",
        "coverage",
        ".coverage",
    }
)

# ---------------------------------------------------------------------------
# Extension-level exclusions (binary / lock / generated)
# ---------------------------------------------------------------------------

EXCLUDE_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Binary / media
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".o",
        ".a",
        ".lib",
        ".whl",
        ".egg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".svg",
        ".pdf",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        # Lock / large generated
        ".lock",            # e.g. poetry.lock, package-lock.json
        ".min.js",          # handled as suffix below
        ".bundle.js",
        # Key / cert material
        ".pem",
        ".crt",
        ".cer",
        ".p12",
        ".pfx",
        ".jks",
    }
)

# Suffixes (multi-dot) that should be excluded — checked on the full filename.
EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".min.js",
    ".min.css",
    ".bundle.js",
    ".pb.py",
    "_pb2.py",
    "_pb2_grpc.py",
    ".snap",        # jest snapshots (machine-generated)
)

# ---------------------------------------------------------------------------
# Path-pattern exclusions (secret / credential files by name)
# ---------------------------------------------------------------------------

# Basename patterns that indicate key/credential material.
_SECRET_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(^|[\W_])(secret|password|credential|private[_\-]?key|api[_\-]?key|auth[_\-]?token)"),
    re.compile(r"(?i)^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"(?i)^\.env(\..+)?$"),       # .env, .env.local, .env.production
    re.compile(r"(?i)^\.npmrc$"),             # often contains auth tokens
    re.compile(r"(?i)^\.pypirc$"),
    re.compile(r"(?i)^netrc$|^\.netrc$"),
)

# ---------------------------------------------------------------------------
# Content-level secret heuristic
# ---------------------------------------------------------------------------

# Look for bare assignment of a long alphanumeric literal on RHS.
# Matches: api_key = "abc123...", PASSWORD = 'xyz...', token="..."
_SECRET_CONTENT_RE = re.compile(
    r"""(?ix)
    (?:api[_\-]?key|password|passwd|secret|token|private[_\-]?key|auth[_\-]?key|
       aws[_\-]?access|aws[_\-]?secret|stripe[_\-]?secret|
       github[_\-]?token|gh[_\-]?token)
    \s*[:=]\s*
    ['"`]([A-Za-z0-9+/=_\-]{20,})['"`]
    """,
    re.VERBOSE,
)

# Maximum bytes to scan for content-based secret detection.
_SECRET_SCAN_BYTES = 4096

# Placeholder substituted for redacted secret material.
REDACTION_PLACEHOLDER = "***redacted-secret***"

# Standalone high-signal credential token shapes (provider key prefixes, JWTs).
# Conservative: each shape is specific enough that false positives on ordinary
# code are rare.
_SECRET_TOKEN_RE = re.compile(
    r"""(?x)
    (
        sk-[A-Za-z0-9]{16,}                         # OpenAI-style
      | gh[pousr]_[A-Za-z0-9]{20,}                  # GitHub tokens
      | github_pat_[A-Za-z0-9_]{20,}                # GitHub fine-grained PAT
      | xox[baprs]-[A-Za-z0-9-]{10,}                # Slack tokens
      | AKIA[0-9A-Z]{16}                            # AWS access key id
      | AIza[0-9A-Za-z_\-]{30,}                     # Google API key
      | eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}  # JWT
    )
    """
)

# PEM private-key blocks (redact the whole body, keep the framing readable).
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)


def redact_secrets(text: str) -> tuple[str, int]:
    """Mask secret material in *text*, returning ``(redacted_text, count)``.

    Redacts three shapes without dropping surrounding context:
    - ``key = "value"`` assignments (api_key/password/token/… ) — the *value*
      is replaced, the key name is kept so the context still reads sensibly.
    - Standalone provider tokens / JWTs anywhere in a line.
    - PEM ``PRIVATE KEY`` blocks (body replaced by the placeholder).

    Deterministic and side-effect free. ``count`` is the number of redactions
    applied (0 when the text is clean).
    """
    count = 0

    def _assign_sub(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return match.group(0).replace(match.group(1), REDACTION_PLACEHOLDER)

    redacted = _SECRET_CONTENT_RE.sub(_assign_sub, text)

    def _token_sub(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return REDACTION_PLACEHOLDER

    redacted = _SECRET_TOKEN_RE.sub(_token_sub, redacted)

    def _pem_sub(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f"-----BEGIN PRIVATE KEY-----\n{REDACTION_PLACEHOLDER}\n-----END PRIVATE KEY-----"

    redacted = _PEM_BLOCK_RE.sub(_pem_sub, redacted)
    return redacted, count


def is_excluded_dir(dirname: str) -> bool:
    """Return True if a directory name should never be walked."""
    return dirname in EXCLUDE_DIRS or dirname.startswith(".git")


def is_excluded_path(rel_path: str) -> bool:
    """Return True if *rel_path* should be excluded from the index.

    Checks directory components, extension, multi-dot suffixes, and
    secret-pattern basenames.  Never reads file content — purely path-based.
    """
    p = Path(rel_path)

    # Directory component check
    for part in p.parts[:-1]:
        if part in EXCLUDE_DIRS or part.startswith(".git"):
            return True

    name_lower = p.name.lower()
    suffix_lower = p.suffix.lower()

    # Extension check
    if suffix_lower in EXCLUDE_EXTENSIONS:
        return True

    # Multi-dot suffix check
    for suffix in EXCLUDE_SUFFIXES:
        if name_lower.endswith(suffix):
            return True

    # Secret/credential basename
    return any(pattern.search(p.name) for pattern in _SECRET_NAME_PATTERNS)


def is_secret_content(file_path: Path) -> bool:
    """Return True if the first 4 KiB of *file_path* looks like a secret store.

    Scans only a small prefix — never loads the full file into memory.  Returns
    False on any read error so a transient permission issue never crashes the
    index.
    """
    try:
        with file_path.open("rb") as fh:
            head = fh.read(_SECRET_SCAN_BYTES)
    except OSError:
        return False

    try:
        text = head.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return False

    return bool(_SECRET_CONTENT_RE.search(text))


def should_index(file_path: Path, repo_root: Path) -> bool:
    """Return True if *file_path* should be included in the index.

    A file is rejected when:
    - Its repo-relative path matches :func:`is_excluded_path`, OR
    - Its content matches the secret heuristic :func:`is_secret_content`.

    Never raises — all errors are treated as "not excluded" (fail-open for
    content checks, so a locked file is still attempted for chunking).
    """
    try:
        rel = file_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False

    if is_excluded_path(rel):
        return False

    return not is_secret_content(file_path)
