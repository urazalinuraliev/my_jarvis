#!/usr/bin/env bash
# Install flyctl (the Fly.io CLI) into a cloud / CI / devcontainer environment.
#
# Idempotent: re-running is a no-op once flyctl is on PATH (unless FLYCTL_VERSION
# pins a different version). Safe to call from a container build step, a Claude
# Code cloud-environment setup hook, or by hand on a fresh box.
#
# Env vars:
#   FLYCTL_INSTALL   install prefix (default: $HOME/.fly). Binary lands in $FLYCTL_INSTALL/bin.
#   FLYCTL_VERSION   pin a specific version, e.g. "0.3.0" (default: latest).
#
# After install, flyctl lives at $FLYCTL_INSTALL/bin/flyctl. This script also
# appends the PATH export to your shell profile so new shells pick it up.
#
# Note: this installs the CLI only. Authenticate separately with `flyctl auth login`
# (interactive) or by exporting FLY_API_TOKEN in the environment.

set -euo pipefail

FLYCTL_INSTALL="${FLYCTL_INSTALL:-$HOME/.fly}"
export FLYCTL_INSTALL

bin="$FLYCTL_INSTALL/bin/flyctl"

log() { printf '[setup-flyctl] %s\n' "$*"; }

# Already installed and on PATH? Nothing to do (unless a version is pinned).
if [[ -z "${FLYCTL_VERSION:-}" ]] && command -v flyctl >/dev/null 2>&1; then
  log "flyctl already installed: $(command -v flyctl) ($(flyctl version 2>/dev/null | head -1))"
  exit 0
fi

# The official installer needs curl and sh.
if ! command -v curl >/dev/null 2>&1; then
  log "ERROR: curl is required but not found. Install curl first." >&2
  exit 1
fi

if [[ -n "${FLYCTL_VERSION:-}" ]]; then
  log "Installing flyctl v${FLYCTL_VERSION} into ${FLYCTL_INSTALL} ..."
  curl -fsSL https://fly.io/install.sh | sh -s "$FLYCTL_VERSION"
else
  log "Installing latest flyctl into ${FLYCTL_INSTALL} ..."
  curl -fsSL https://fly.io/install.sh | sh
fi

if [[ ! -x "$bin" ]]; then
  log "ERROR: expected flyctl at $bin after install, but it is missing." >&2
  exit 1
fi

# Persist PATH for future shells. Pick the profile that exists / matches the shell.
profile=""
case "${SHELL:-}" in
  *zsh) profile="$HOME/.zshrc" ;;
  *bash) profile="$HOME/.bashrc" ;;
  *) profile="$HOME/.profile" ;;
esac

path_line="export FLYCTL_INSTALL=\"${FLYCTL_INSTALL}\"; export PATH=\"\$FLYCTL_INSTALL/bin:\$PATH\""
if [[ -n "$profile" ]] && ! grep -qsF "FLYCTL_INSTALL/bin" "$profile" 2>/dev/null; then
  printf '\n# flyctl (added by scripts/setup-flyctl.sh)\n%s\n' "$path_line" >> "$profile"
  log "Added flyctl to PATH in ${profile} (open a new shell or 'source ${profile}')."
fi

# Make it usable in the current shell too.
export PATH="$FLYCTL_INSTALL/bin:$PATH"

log "Installed: $("$bin" version | head -1)"
log "Done. Authenticate with 'flyctl auth login' or export FLY_API_TOKEN."
