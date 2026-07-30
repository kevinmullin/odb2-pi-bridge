#!/usr/bin/env bash
# Bridge TCP :ELM_TCP_PORT <-> Bluetooth serial /dev/cu.* (Wi-Fi ELM327 style).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config.env"

log() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date)" "$*"; }

if ! command -v socat >/dev/null 2>&1; then
  echo "socat not found — run: make macos-setup" >&2
  exit 1
fi

FIND="${ROOT}/scripts/find-cu.sh"
PORT="${ELM_TCP_PORT:-35000}"
BAUD="${BT_BAUD:-115200}"
WAIT="${PROXY_WAIT_SECONDS:-2}"

log "Waiting for Bluetooth serial device…"
DEV=""
while true; do
  if DEV="$("${FIND}" 2>/dev/null)"; then
    break
  fi
  sleep "${WAIT}"
done

log "Bridging TCP :${PORT} <-> ${DEV} (baud ${BAUD})"
exec socat -d -d \
  "TCP-LISTEN:${PORT},bind=0.0.0.0,reuseaddr,keepalive" \
  "FILE:${DEV},b${BAUD},raw,echo=0"
