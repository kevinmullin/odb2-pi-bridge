#!/usr/bin/env bash
# Periodic health log for journald (optional timer).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

load_config

status_line() {
  local ap="down" bt="down" rf="missing" port="closed"

  if ip -4 addr show "${AP_IFACE}" 2>/dev/null | grep -q "${AP_IP}"; then
    ap="up"
  fi
  if bt_adapter_ready; then
    bt="up"
  fi
  if [[ -e "${RFCOMM_DEV}" ]]; then
    rf="present"
  fi
  if ss -lnt 2>/dev/null | grep -q ":${ELM_TCP_PORT} "; then
    port="listen"
  elif command -v netstat >/dev/null 2>&1 && netstat -lnt 2>/dev/null | grep -q ":${ELM_TCP_PORT} "; then
    port="listen"
  fi

  log "health ap=${ap} bt=${bt} rfcomm=${rf} tcp=${port} mac=${BT_MAC:-unset}"
}

status_line
