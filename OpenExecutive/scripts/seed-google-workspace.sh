#!/usr/bin/env bash
# Seed the co-located Google Workspace MCP server's credentials onto an
# Open Executive API install, for either auth mode.
#
#   oauth  (default) — uploads the workspace-mcp OAuth credential file you
#          generated locally (`uvx workspace-mcp auth`) onto the API's
#          /data/google_credentials volume, and sets the OAuth client secrets.
#   service_account — sets the service-account key + delegated user secrets;
#          no file to upload.
#
# Setting secrets rolls the API machine, so the new config takes effect on its
# own. The live gateway config (/data/company/mcp_servers.json) is NOT edited
# here — this script checks it read-only and tells you if it still needs
# repointing at the launcher (see docs/deployment.md).
#
# Usage:
#   export GOOGLE_OAUTH_CLIENT_ID=...            # oauth mode
#   export GOOGLE_OAUTH_CLIENT_SECRET=...
#   export GWORKSPACE_TOKEN_FILE=~/.google_workspace_mcp/credentials/exec%40you.com.json
#   ./scripts/seed-google-workspace.sh
#
#   # — or service account —
#   export GWORKSPACE_AUTH_MODE=service_account
#   export USER_GOOGLE_EMAIL=exec@you.com
#   export GOOGLE_SERVICE_ACCOUNT_KEY_JSON="$(cat sa.json)"
#   ./scripts/seed-google-workspace.sh
#
# Flags via env:  DRY_RUN=1 (print, don't execute) · ASSUME_YES=1 (no prompt)
#                 OPENEXEC_API_APP=... (default openexec-api-dev)
set -euo pipefail

# Values come from your exported environment (this script does NOT source .env,
# so your exports are authoritative). To pull from .env instead, run:
#   set -a; source .env; set +a   # before invoking this script
API_APP="${OPENEXEC_API_APP:-openexec-api-dev}"
MODE="${GWORKSPACE_AUTH_MODE:-oauth}"
CRED_DIR="${WORKSPACE_MCP_CREDENTIALS_DIR:-/data/google_credentials}"  # matches fly.api.toml
DRY_RUN="${DRY_RUN:-0}"
ASSUME_YES="${ASSUME_YES:-0}"

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# Run a NON-secret command, echoing it first. Secret-bearing commands are run
# separately so their values never hit the terminal or `set -x`.
run() {
  printf '   $ %s\n' "$*"
  [[ "$DRY_RUN" == 1 ]] || "$@"
}

command -v fly >/dev/null 2>&1 || die "fly (flyctl) not found on PATH"
[[ "$MODE" == oauth || "$MODE" == service_account ]] \
  || die "GWORKSPACE_AUTH_MODE must be 'oauth' or 'service_account' (got '$MODE')"

# ---------------------------------------------------------------------------
# Validate inputs up front so we never half-apply.
# ---------------------------------------------------------------------------
if [[ "$MODE" == oauth ]]; then
  : "${GOOGLE_OAUTH_CLIENT_ID:?set GOOGLE_OAUTH_CLIENT_ID for oauth mode}"
  : "${GOOGLE_OAUTH_CLIENT_SECRET:?set GOOGLE_OAUTH_CLIENT_SECRET for oauth mode}"
  TOKEN_FILE="${GWORKSPACE_TOKEN_FILE:?set GWORKSPACE_TOKEN_FILE to the local workspace-mcp credential json}"
  [[ -f "$TOKEN_FILE" ]] || die "token file not found: $TOKEN_FILE"
  # workspace-mcp names the file by the (URL-encoded) account email; preserve it
  # so the server finds it. Override with GWORKSPACE_TOKEN_DEST_NAME if needed.
  DEST_NAME="${GWORKSPACE_TOKEN_DEST_NAME:-$(basename "$TOKEN_FILE")}"
  python3 -m json.tool "$TOKEN_FILE" >/dev/null 2>&1 \
    || die "token file is not valid JSON: $TOKEN_FILE"
else
  : "${USER_GOOGLE_EMAIL:?set USER_GOOGLE_EMAIL (delegated user) for service_account mode}"
  [[ -n "${GOOGLE_SERVICE_ACCOUNT_KEY_JSON:-}" || -n "${GOOGLE_SERVICE_ACCOUNT_KEY_FILE:-}" ]] \
    || die "set GOOGLE_SERVICE_ACCOUNT_KEY_JSON or GOOGLE_SERVICE_ACCOUNT_KEY_FILE for service_account mode"
  if [[ -n "${GOOGLE_SERVICE_ACCOUNT_KEY_JSON:-}" ]]; then
    printf '%s' "$GOOGLE_SERVICE_ACCOUNT_KEY_JSON" | python3 -m json.tool >/dev/null 2>&1 \
      || die "GOOGLE_SERVICE_ACCOUNT_KEY_JSON is not valid JSON"
  fi
fi

# ---------------------------------------------------------------------------
# Plan + confirm (this restarts the API).
# ---------------------------------------------------------------------------
say "Plan for app '$API_APP' (mode=$MODE)${DRY_RUN:+, DRY_RUN}"
if [[ "$MODE" == oauth ]]; then
  echo "  • upload $TOKEN_FILE  ->  $CRED_DIR/$DEST_NAME (0600)"
  echo "  • set secrets: GWORKSPACE_AUTH_MODE=oauth, GOOGLE_OAUTH_CLIENT_ID=<set>, GOOGLE_OAUTH_CLIENT_SECRET=<hidden>"
else
  echo "  • set secrets: GWORKSPACE_AUTH_MODE=service_account, USER_GOOGLE_EMAIL=$USER_GOOGLE_EMAIL, GOOGLE_SERVICE_ACCOUNT_KEY_JSON=<hidden>"
fi
echo "  • setting secrets rolls the API machine"
if [[ "$DRY_RUN" != 1 && "$ASSUME_YES" != 1 ]]; then
  read -r -p "Proceed? [y/N] " reply
  [[ "$reply" == [yY] ]] || die "aborted"
fi

# ---------------------------------------------------------------------------
# 1. Upload the OAuth credential file (oauth mode only).
# ---------------------------------------------------------------------------
if [[ "$MODE" == oauth ]]; then
  say "Uploading credential to $CRED_DIR/$DEST_NAME"
  run fly ssh console --app "$API_APP" -C "mkdir -p $CRED_DIR"
  run fly ssh console --app "$API_APP" -C "chmod 700 $CRED_DIR"
  if [[ "$DRY_RUN" == 1 ]]; then
    printf '   $ put %s -> %s/%s (via fly ssh sftp)\n' "$TOKEN_FILE" "$CRED_DIR" "$DEST_NAME"
  else
    printf 'put %s %s/%s\n' "$TOKEN_FILE" "$CRED_DIR" "$DEST_NAME" \
      | fly ssh sftp shell --app "$API_APP"
  fi
  run fly ssh console --app "$API_APP" -C "chmod 600 $CRED_DIR/$DEST_NAME"
fi

# ---------------------------------------------------------------------------
# 2. Set the Google secrets (one `fly secrets set` -> one machine roll).
#    Run directly (not via `run`) so secret values are never echoed.
# ---------------------------------------------------------------------------
say "Setting secrets on $API_APP"
if [[ "$DRY_RUN" == 1 ]]; then
  echo "   (dry-run: would fly secrets set ... for mode=$MODE)"
elif [[ "$MODE" == oauth ]]; then
  fly secrets set --app "$API_APP" \
    GWORKSPACE_AUTH_MODE=oauth \
    GOOGLE_OAUTH_CLIENT_ID="$GOOGLE_OAUTH_CLIENT_ID" \
    GOOGLE_OAUTH_CLIENT_SECRET="$GOOGLE_OAUTH_CLIENT_SECRET"
else
  # Build args as an array so the (spaced / multi-line) service-account JSON is
  # passed as ONE quoted argument, not word-split into broken `fly` args.
  sa_args=(GWORKSPACE_AUTH_MODE=service_account "USER_GOOGLE_EMAIL=$USER_GOOGLE_EMAIL")
  [[ -n "${GOOGLE_SERVICE_ACCOUNT_KEY_JSON:-}" ]] \
    && sa_args+=("GOOGLE_SERVICE_ACCOUNT_KEY_JSON=$GOOGLE_SERVICE_ACCOUNT_KEY_JSON")
  [[ -n "${GOOGLE_SERVICE_ACCOUNT_KEY_FILE:-}" ]] \
    && sa_args+=("GOOGLE_SERVICE_ACCOUNT_KEY_FILE=$GOOGLE_SERVICE_ACCOUNT_KEY_FILE")
  fly secrets set --app "$API_APP" "${sa_args[@]}"
fi

# ---------------------------------------------------------------------------
# 3. Read-only check: is the gateway config already pointed at the launcher?
# ---------------------------------------------------------------------------
say "Checking gateway config (read-only)"
if [[ "$DRY_RUN" == 1 ]]; then
  echo "   (dry-run: would cat /data/company/mcp_servers.json and check google_workspace.command)"
else
  cfg="$(fly ssh console --app "$API_APP" -C "cat /data/company/mcp_servers.json" 2>/dev/null || true)"
  if grep -q "workspace-mcp-launch.sh" <<<"$cfg"; then
    echo "   ✓ google_workspace already points at the co-located launcher"
  else
    warn "google_workspace is NOT pointed at the launcher yet — it's still using the old server."
    echo  "        Edit /data/company/mcp_servers.json so the google_workspace entry's"
    echo  "        \"command\" is \"/usr/local/bin/workspace-mcp-launch.sh\" (see"
    echo  "        packages/core/mcp_servers.json.example), then: fly apps restart $API_APP"
  fi
fi

say "Done. Verify:  fly logs --app $API_APP | grep 'MCPGateway started'"
echo "Then run a calendar/email/drive action through the Executive."
