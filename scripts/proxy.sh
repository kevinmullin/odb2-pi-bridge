#!/usr/bin/env bash
# Wait for RFCOMM device, then bridge TCP <-> serial (ELM327 Wi-Fi style).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

load_config

DEV="${RFCOMM_DEV}"
PORT="${ELM_TCP_PORT}"

if ! command -v socat >/dev/null 2>&1; then
  err "socat not found"
  exit 1
fi

log "Waiting for ${DEV}…"
while [[ ! -e "${DEV}" ]]; do
  sleep "${PROXY_WAIT_SECONDS}"
done

log "Bridging TCP :${PORT} <-> ${DEV}"
# fork=false: one client at a time (typical for OBD apps). Restart via systemd on exit.
exec socat -d -d \
  "TCP-LISTEN:${PORT},bind=0.0.0.0,reuseaddr,keepalive" \
  "FILE:${DEV},b115200,raw,echo=0"
