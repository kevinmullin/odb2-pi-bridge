#!/usr/bin/env bash
# Continuously ensure BAFX is paired. Safe with no SSH / no home Wi-Fi.
# Once paired, idles and re-checks; if device.env cleared, scans again.
# Writes status.env + events.log for the PiTFT activity stream.
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
export STATUS_DIR

mkdir -p "${STATUS_DIR}" "${OBD_BRIDGE_ETC}"

write_status() {
  local phase="$1"
  local detail="${2:-}"
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

last_pair_reason() {
  # Prefer the real failure, not the trailing "set BT_MAC" hint.
  local blob="$1"
  local line
  line="$(printf '%s\n' "${blob}" | grep -E 'ERROR: No Bluetooth device matched' | tail -n 1 | sed 's/.*ERROR: //' || true)"
  if [[ -n "${line}" ]]; then
    printf '%s\n' "${line}"
    return
  fi
  line="$(printf '%s\n' "${blob}" | grep -E 'ERROR: Nearby BT:' | tail -n 1 | sed 's/.*ERROR: //' || true)"
  if [[ -n "${line}" ]]; then
    printf '%s\n' "${line}"
    return
  fi
  line="$(printf '%s\n' "${blob}" | grep -E 'ERROR:' | grep -v 'set BT_MAC' | grep -v 're-run pair' | grep -v 'Power the BAFX' | tail -n 1 | sed 's/.*ERROR: //' || true)"
  if [[ -n "${line}" ]]; then
    printf '%s\n' "${line}"
    return
  fi
  printf '%s\n' "pair failed"
}

append_event "autopair started (retry ${RETRY_SECONDS}s)"
log "Autopair supervisor started (retry=${RETRY_SECONDS}s)."
write_status "starting" "Autopair starting…"

while true; do
  read_device
  if [[ -n "${BT_MAC:-}" ]]; then
    write_status "paired" "Paired ${BT_MAC}"
    append_event "paired ${BT_MAC} — idle ${IDLE_SECONDS}s"
    sleep "${IDLE_SECONDS}"
    continue
  fi

  if ! bt_adapter_ready; then
    write_status "bt-down" "Bluetooth adapter not ready"
    append_event "BT adapter not ready — wait"
    sleep "${RETRY_SECONDS}"
    continue
  fi

  bluetoothctl power on >/dev/null 2>&1 || true
  bluetoothctl pairable on >/dev/null 2>&1 || true

  write_status "waiting" "Ignition ON + BAFX LED on"
  append_event "no MAC yet — need BAFX + ignition"
  log "No BT_MAC yet — scanning/pairing…"

  write_status "scanning" "Scan ${BT_SCAN_SECONDS}s /${BT_NAME_REGEX}/"
  append_event "scanning ${BT_SCAN_SECONDS}s for /${BT_NAME_REGEX}/"

  set +e
  pair_out="$("${SCRIPT_DIR}/pair-bafx.sh" 2>&1)"
  rc=$?
  set -e
  if [[ -n "${pair_out}" ]]; then
    log "pair-bafx: $(printf '%s' "${pair_out}" | tr '\n' ' ' | cut -c1-200)"
  fi

  if [[ "${rc}" -eq 0 ]]; then
    read_device
    write_status "paired" "Paired ${BT_MAC:-ok}"
    append_event "PAIR OK ${BT_MAC:-}"
    log "Paired ${BT_MAC:-}. Restarting RFCOMM/live."
    systemctl restart obd-bridge-rfcomm.service 2>/dev/null || true
    systemctl restart obd-bridge-live.service 2>/dev/null || true
    systemctl restart obd-bridge-proxy.service 2>/dev/null || true
    sleep "${IDLE_SECONDS}"
    continue
  fi

  reason="$(last_pair_reason "${pair_out}")"
  # Keep DETAIL short for status.env; full reason also in events.log
  short="${reason}"
  if [[ ${#short} -gt 48 ]]; then
    short="${short:0:45}…"
  fi
  write_status "retry" "${short}"
  append_event "FAIL: ${reason}"
  append_event "retry in ${RETRY_SECONDS}s"
  log "Pair attempt failed (rc=${rc}): ${reason}; sleep ${RETRY_SECONDS}s"
  sleep "${RETRY_SECONDS}"
done
