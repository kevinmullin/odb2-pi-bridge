#!/usr/bin/env bash
# Continuously ensure BAFX is paired. Safe with no SSH / no home Wi-Fi.
# Once paired, idles and re-checks; if device.env cleared (TFT re-pair), scans again.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

load_config
require_root

RETRY_SECONDS="${AUTOPAIR_RETRY_SECONDS:-15}"
IDLE_SECONDS="${AUTOPAIR_IDLE_SECONDS:-60}"
STATUS_DIR="${STATUS_DIR:-/run/obd-bridge}"
STATUS_FILE="${STATUS_DIR}/status.env"

mkdir -p "${STATUS_DIR}" "${OBD_BRIDGE_ETC}"

write_status() {
  local phase="$1"
  local detail="${2:-}"
  # Refresh config-derived fields each write
  load_config || true
  cat >"${STATUS_FILE}" <<EOF
PHASE=${phase}
DETAIL=${detail}
SSID=${AP_SSID:-obd-bridge}
AP_PASS=${AP_PASS:-}
AP_IP=${AP_IP:-192.168.4.1}
ELM_TCP_PORT=${ELM_TCP_PORT:-35000}
BT_MAC=${BT_MAC:-}
UPDATED=$(date -Iseconds 2>/dev/null || date)
EOF
}

read_device() {
  BT_MAC=""
  if [[ -f "${DEVICE_ENV}" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck disable=SC1090
    source "${DEVICE_ENV}"
    set +a
  fi
}

log "Autopair supervisor started (retry=${RETRY_SECONDS}s)."

while true; do
  read_device
  if [[ -n "${BT_MAC:-}" ]]; then
    write_status "paired" "${BT_MAC}"
    sleep "${IDLE_SECONDS}"
    continue
  fi

  write_status "waiting" "Ignition ON + plug BAFX"
  log "No BT_MAC yet — scanning/pairing…"
  write_status "scanning" "Looking for ELM/BAFX…"
  set +e
  "${SCRIPT_DIR}/pair-bafx.sh"
  rc=$?
  set -e
  if [[ "${rc}" -eq 0 ]]; then
    read_device
    write_status "paired" "${BT_MAC:-ok}"
    log "Paired ${BT_MAC:-}. Restarting RFCOMM/proxy."
    systemctl restart obd-bridge-rfcomm.service 2>/dev/null || true
    systemctl restart obd-bridge-proxy.service 2>/dev/null || true
    sleep "${IDLE_SECONDS}"
    continue
  fi
  write_status "retry" "Pair failed; retry in ${RETRY_SECONDS}s"
  log "Pair attempt failed (rc=${rc}); sleep ${RETRY_SECONDS}s"
  sleep "${RETRY_SECONDS}"
done
