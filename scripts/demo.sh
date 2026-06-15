#!/usr/bin/env bash
# scripts/demo.sh — Two Agents, One Brain
#
# Runs the cross-agent shared-memory demo end-to-end in throwaway temp repos.
# All onmc state is isolated to the temp directories; nothing touches your real
# repos or ~/.onmc.
#
# Usage:
#   bash scripts/demo.sh
#   ONMC=path/to/onmc bash scripts/demo.sh
#
# Requirements:
#   - onmc on PATH (or set ONMC= env var)
#   - git
#   - bash >= 3.2

set -euo pipefail

ONMC="${ONMC:-onmc}"

# ── helpers ─────────────────────────────────────────────────────────────────

header() { echo; echo "── $* ──"; echo; }
step()   { echo "  \$ $*"; }

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "ERROR: '$1' not found. Install it and retry." >&2
        exit 1
    fi
}

# ── preflight ────────────────────────────────────────────────────────────────

require_cmd git
require_cmd "$ONMC"

AGENT_A_DIR=$(mktemp -d)
CLONE_DIR=$(mktemp -d)
AGENT_B_DIR="$CLONE_DIR/myapi-agent-b"

echo "onmc demo: Two Agents, One Brain"
echo "onmc version: $("$ONMC" --version 2>/dev/null || echo 'unknown')"
echo "Agent A repo: $AGENT_A_DIR"
echo "Agent B repo: $AGENT_B_DIR"

# ── Agent A: build a small project ─────────────────────────────────────────

header "AGENT A — build project + git history"

cd "$AGENT_A_DIR"
git init -b main -q
git config user.email "agent-a@example.com"
git config user.name "Agent A"

mkdir -p src/api src/auth

cat > src/auth/token.py << 'PYEOF'
"""Token management for the API."""
import hashlib, secrets

def generate_token() -> str:
    return secrets.token_hex(32)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

TOKEN_EXPIRY = 3600  # seconds
PYEOF

cat > src/api/middleware.py << 'PYEOF'
"""API middleware stack."""
from typing import Any

def rate_limit(requests_per_minute: int = 60) -> Any:
    """Rate limiting middleware."""
    pass

def auth_required(func: Any) -> Any:
    """Authentication decorator (placeholder — not yet implemented)."""
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)
    return wrapper
PYEOF

cat > src/api/routes.py << 'PYEOF'
"""API route definitions."""
from src.api.middleware import auth_required

@auth_required
def get_user(user_id: str) -> dict:
    return {"id": user_id}
PYEOF

cat > pyproject.toml << 'TOMLEOF'
[project]
name = "myapi"
version = "0.1.0"
requires-python = ">=3.11"
TOMLEOF

echo "# myapi" > README.md

git add . && git commit -q -m "feat: initial project scaffold"
git add src/api/middleware.py && git commit -q --allow-empty -m "docs: add rate limiting note to middleware" 2>/dev/null || true

echo "Git log:"
git log --oneline

# ── Agent A: onmc init + ingest ──────────────────────────────────────────────

header "AGENT A — onmc init + ingest"

step "onmc init"
"$ONMC" init

step "onmc ingest --no-llm"
"$ONMC" ingest --no-llm

# ── Agent A: create task + record dead-end ───────────────────────────────────

header "AGENT A — start task, record dead-end"

step "onmc task start ..."
TASK_OUTPUT=$("$ONMC" task start \
    --title "Add JWT authentication to API endpoints" \
    --description "Replace the placeholder auth_required decorator with real JWT verification using PyJWT" \
    2>&1)
echo "$TASK_OUTPUT"

TASK_ID=$(echo "$TASK_OUTPUT" | grep -oE 'task-[a-f0-9]+' | head -1)
echo "  (task id: $TASK_ID)"

step "onmc memory add $TASK_ID --type did_not_work ..."
"$ONMC" memory add "$TASK_ID" \
    --type did_not_work \
    --title "PyJWT HS256 secret from env fails under Firebase Functions" \
    --summary "Tried loading the JWT secret from os.environ inside the auth_required decorator at import time. Firebase Functions sets environment variables lazily — the variable is None at module load, causing every token verification to fail with 'Invalid signature'. Spent 3 hours debugging; the secret simply isn't available until the first request hits the function." \
    --why-it-matters "Any approach that reads JWT secrets at module/decorator definition time will silently fail in Firebase Functions. The secret MUST be read inside the request handler, not at import time." \
    --apply-when "Adding JWT verification to any endpoint deployed as a Firebase Function" \
    --evidence "jwt.exceptions.InvalidSignatureError observed in staging logs; root-caused to None secret at module load by adding debug print at startup" \
    --file "src/api/middleware.py" \
    --module "src.api.middleware" \
    --confidence 0.95

step "onmc task end $TASK_ID --status abandoned ..."
"$ONMC" task end "$TASK_ID" \
    --status abandoned \
    --summary "JWT approach abandoned; secret env-var not available at import time in Firebase Functions."

# Seed a failed_approach memory entry so onmc guard can surface it.
#
# Background: `memory add --type did_not_work` creates a task-scoped artifact
# record (used by `onmc why` and `onmc memory list`). The `onmc guard` command
# separately searches the memory store for entries with kind=failed_approach.
# In production these get populated automatically by `onmc ingest` (LLM mode)
# when commit diffs mention dead-ends, or by `onmc mine` from session
# transcripts. Here we seed one directly via the Python API so the demo is
# runnable without a live LLM provider.
header "AGENT A — seed failed_approach memory for guard"
echo "  (seeding failed_approach entry via onmc Python API — equivalent to what"
echo "   'onmc ingest' or 'onmc mine' produces automatically with an LLM provider)"

ONMC_SRC=$(dirname "$(dirname "$(command -v "$ONMC")")")/lib/python*/site-packages
# Prefer the onmc package from the same venv as the CLI
VENV_PYTHON=$(dirname "$(command -v "$ONMC")")/python3
if [ ! -x "$VENV_PYTHON" ]; then
    VENV_PYTHON=$(dirname "$(command -v "$ONMC")")/python
fi

DB_PATH="$AGENT_A_DIR/.onmc/memory.db"
TITLE="PyJWT HS256 secret from env fails under Firebase Functions"

"$VENV_PYTHON" - << PYEOF
import sys, hashlib
from pathlib import Path
from datetime import datetime, timezone
from oh_no_my_claudecode.storage import SQLiteStorage
from oh_no_my_claudecode.models import MemoryEntry, MemoryKind, SourceType

db = SQLiteStorage(Path("$DB_PATH"))
db.initialize()
now = datetime.now(timezone.utc)
title = "$TITLE"
mem_id = "failed_approach-" + hashlib.md5(title.encode()).hexdigest()[:10]
entry = MemoryEntry(
    id=mem_id, kind=MemoryKind.FAILED_APPROACH, title=title,
    summary="Reading JWT secret from os.environ at module/decorator import time fails in Firebase Functions because env vars are loaded lazily. The secret is None at import time, causing every jwt.decode() call to raise InvalidSignatureError.",
    details="Evidence: jwt.exceptions.InvalidSignatureError in staging logs. Root-caused to None secret at module load. The secret MUST be read inside the request handler, not at import time. Related: src/api/middleware.py",
    source_type=SourceType.MANUAL, source_ref="task:$TASK_ID",
    tags=["jwt", "firebase", "auth", "middleware", "environment", "secret", "pyjwt"],
    confidence=0.95, created_at=now, updated_at=now,
)
db.upsert_memories([entry])
print("  failed_approach memory seeded:", mem_id)
PYEOF

# ── Agent A: sync --commit + git commit ──────────────────────────────────────

header "AGENT A — sync to git"

step "onmc sync --commit"
"$ONMC" sync --commit

echo ""
echo "  .agent-memory/ contents:"
find .agent-memory/ -type f | sort | sed 's/^/    /'

step "git add .agent-memory && git commit"
git add .agent-memory/ .gitignore 2>/dev/null || git add .agent-memory/
git commit -q -m "chore: sync agent memory — JWT dead-end recorded"
git log --oneline

# ── Agent B: clone + restore ─────────────────────────────────────────────────

header "AGENT B — clone repo + restore brain"

step "git clone $AGENT_A_DIR $AGENT_B_DIR"
git clone "$AGENT_A_DIR" "$AGENT_B_DIR" 2>&1

cd "$AGENT_B_DIR"
git config user.email "agent-b@example.com"
git config user.name "Agent B"

step "onmc init"
"$ONMC" init

step "onmc sync --restore"
"$ONMC" sync --restore

# ── Agent B: guard fires ──────────────────────────────────────────────────────

header "AGENT B — guard check before touching middleware"

step 'onmc guard --task "Add JWT token verification using PyJWT, load the secret from environment variables in the auth_required decorator"'
"$ONMC" guard \
    --task "Add JWT token verification using PyJWT, load the secret from environment variables in the auth_required decorator"

# ── Agent B: why on the dangerous file ───────────────────────────────────────

header "AGENT B — onmc why on the file it was about to edit"

step "onmc why src/api/middleware.py --no-llm"
"$ONMC" why src/api/middleware.py --no-llm

# ── statusline ───────────────────────────────────────────────────────────────

header "AGENT B — statusline"
step "onmc statusline"
"$ONMC" statusline

echo ""
echo "Demo complete."
echo "Agent A repo: $AGENT_A_DIR"
echo "Agent B repo: $AGENT_B_DIR"
echo "(temp dirs left in place — remove manually when done)"
