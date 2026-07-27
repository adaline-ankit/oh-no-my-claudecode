#!/bin/sh
# install.sh — oh-my-zsh-style one-line installer for oh-no-my-claudecode (onmc)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/adaline-ankit/oh-no-my-claudecode/main/install.sh | bash
#   ONMC_NO_INTEGRATE=1 bash install.sh   # install only, skip setup
#
# Flags:
#   --help    Print usage and exit
#
# Env overrides:
#   ONMC_NO_INTEGRATE=1   Skip the post-install integration step (runs onmc setup --yes)
#
# Never requires elevated privileges. Fails loudly with a non-zero exit code on any error.

set -eu

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOLD=""
RESET=""
GREEN=""
CYAN=""
YELLOW=""
RED=""

# Enable colours only when stdout is a terminal (safe for pipe installs)
if [ -t 1 ]; then
  BOLD="\033[1m"
  RESET="\033[0m"
  GREEN="\033[32m"
  CYAN="\033[36m"
  YELLOW="\033[33m"
  RED="\033[31m"
fi

info()    { printf "%b[onmc]%b %s\n" "${CYAN}" "${RESET}" "$*"; }
success() { printf "%b[onmc]%b %s\n" "${GREEN}" "${RESET}" "$*"; }
warn()    { printf "%b[onmc warn]%b %s\n" "${YELLOW}" "${RESET}" "$*" >&2; }
fatal()   { printf "%b[onmc error]%b %s\n" "${RED}" "${RESET}" "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  cat <<'EOF'
install.sh — one-line installer for oh-no-my-claudecode (onmc)

USAGE
  curl -fsSL https://raw.githubusercontent.com/adaline-ankit/oh-no-my-claudecode/main/install.sh | bash
  ONMC_NO_INTEGRATE=1 bash install.sh   # install only, no integration

OPTIONS
  --help   Print this message and exit.

ENV
  ONMC_NO_INTEGRATE=1   Skip the post-install integration step.

Never requires elevated privileges. Exits non-zero on failure.
EOF
  exit 0
fi

# ---------------------------------------------------------------------------
# Step 1: detect installer (uv → pipx → pip)
# ---------------------------------------------------------------------------

info "Detecting Python package manager …"

INSTALLER=""
INSTALL_CMD=""

if command -v uv >/dev/null 2>&1; then
  INSTALLER="uv"
  INSTALL_CMD="uv tool install --force oh-no-my-claudecode"
elif command -v pipx >/dev/null 2>&1; then
  INSTALLER="pipx"
  INSTALL_CMD="pipx install --force oh-no-my-claudecode"
elif command -v pip >/dev/null 2>&1; then
  INSTALLER="pip"
  INSTALL_CMD="pip install --user --upgrade oh-no-my-claudecode"
elif command -v pip3 >/dev/null 2>&1; then
  INSTALLER="pip3"
  INSTALL_CMD="pip3 install --user --upgrade oh-no-my-claudecode"
else
  fatal "No Python package manager found (tried: uv, pipx, pip, pip3).
Install one of:
  uv   -> https://docs.astral.sh/uv/getting-started/installation/
  pipx -> https://pipx.pypa.io/stable/installation/
  pip  -> https://pip.pypa.io/en/stable/installation/
Then re-run this installer."
fi

info "Using ${INSTALLER} to install oh-no-my-claudecode …"

# ---------------------------------------------------------------------------
# Step 2: run the install command
# ---------------------------------------------------------------------------

if ! $INSTALL_CMD; then
  fatal "Installation via '${INSTALL_CMD}' failed (see error above)."
fi

# Verify the binary is available
if ! command -v onmc >/dev/null 2>&1; then
  warn "'onmc' not found in PATH after install."
  warn "You may need to add the tool install directory to your PATH:"
  warn "  uv:   add \$(uv tool dir)/bin to PATH"
  warn "  pipx: run 'pipx ensurepath'"
  warn "  pip:  add \$(python -m site --user-base)/bin to PATH"
  warn "Then restart your shell and re-run the integration step."
  exit 1
fi

success "oh-no-my-claudecode installed successfully ($(onmc --version 2>/dev/null || echo 'onmc'))."

# ---------------------------------------------------------------------------
# Step 3: configure ONMC through the canonical setup path
# ---------------------------------------------------------------------------

ONMC_NO_INTEGRATE="${ONMC_NO_INTEGRATE:-0}"

if [ "${ONMC_NO_INTEGRATE}" = "1" ]; then
  info "ONMC_NO_INTEGRATE=1 — skipping integration step."
else
  info "Integrating onmc with Claude Code …"

  # Determine CWD: prefer git root if inside a repo, else PWD
  INTEGRATE_DIR="$(pwd)"
  GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [ -n "${GIT_ROOT}" ]; then
    INTEGRATE_DIR="${GIT_ROOT}"
  fi

  info "Running integration in: ${INTEGRATE_DIR}"

  # Redirect stdin so a curl|bash pipe cannot feed the setup wizard.
  SETUP_CMD="onmc setup --yes"

  # Intentional word-splitting for SETUP_CMD arguments.
  # shellcheck disable=SC2086
  if ! (cd "${INTEGRATE_DIR}" && ${SETUP_CMD}) </dev/null; then
    warn "Integration step ('${SETUP_CMD}') exited non-zero."
    warn "Run it manually later: onmc setup"
  else
    success "Integration complete."
  fi
fi

# ---------------------------------------------------------------------------
# Step 4: friendly success banner
# ---------------------------------------------------------------------------

printf "\n"
printf "%b===========================================================%b\n" "${BOLD}${GREEN}" "${RESET}"
printf "%b  onmc is ready!%b\n" "${BOLD}${GREEN}" "${RESET}"
printf "%b===========================================================%b\n" "${BOLD}${GREEN}" "${RESET}"
printf "\n"
printf "Day-1 commands to try:\n"
printf "  %bonmc run%b %b\"your task\"%b -- preview the canonical runtime contract\n" "${BOLD}" "${RESET}" "${CYAN}" "${RESET}"
printf "  %bonmc status%b           -- check repository and ONMC readiness\n" "${BOLD}" "${RESET}"
printf "  %bonmc missioncontrol%b   -- inspect durable run and proof state\n" "${BOLD}" "${RESET}"
printf "  %bonmc ui%b               -- visual Mission Control\n" "${BOLD}" "${RESET}"
printf "\n"
printf "Docs: https://github.com/adaline-ankit/oh-no-my-claudecode\n"
printf "\n"
