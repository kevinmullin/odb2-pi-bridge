#!/usr/bin/env bash
# Shared helpers for obd-bridge scripts.
# shellcheck disable=SC2034

set -euo pipefail

OBD_BRIDGE_ETC="${OBD_BRIDGE_ETC:-/etc/obd-bridge}"
OBD_BRIDGE_LIB="${OBD_BRIDGE_LIB:-/usr/local/lib/obd-bridge}"
DEVICE_ENV="${OBD_BRIDGE_ETC}/device.env"
CONFIG_ENV="${OBD_BRIDGE_ETC}/config.env"

log() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date)" "$*"; }
err() { printf '%s ERROR: %s\n' "$(date -Iseconds 2>/dev/null || date)" "$*" >&2; }

# Rolling activity log for the PiTFT (HH:MM:SS message)
append_event() {
  local msg="$1"
  local dir="${STATUS_DIR:-/run/obd-bridge}"
  local file="${dir}/events.log"
  mkdir -p "${dir}"
  printf '%s %s\n' "$(date '+%H:%M:%S')" "${msg}" >>"${file}"
  if [[ -f "${file}" ]]; then
    tail -n 60 "${file}" >"${file}.tmp" && mv "${file}.tmp" "${file}"
  fi
}

# Persistent BT scan dump (survives reboot / bring indoors for SSH)
# Latest: /var/lib/obd-bridge/bt-last-scan.txt
# History: /var/lib/obd-bridge/bt-scan.log
dump_bt_scan() {
  local note="${1:-scan}"
  local dir="${OBD_BRIDGE_STATE:-/var/lib/obd-bridge}"
  local latest="${dir}/bt-last-scan.txt"
  local hist="${dir}/bt-scan.log"
  mkdir -p "${dir}"
  {
    echo "=== ${note} $(date -Iseconds 2>/dev/null || date) ==="
    echo "regex=${BT_NAME_REGEX:-OBDII|ELM327|V-LINK|BAFX|OBD}"
    echo "controller:"
    bluetoothctl show 2>/dev/null | grep -E '^(Controller|Name:|Powered:|Pairable:|Discovering:)' || true
    echo "devices:"
    if bluetoothctl devices 2>/dev/null | grep -q .; then
      bluetoothctl devices 2>/dev/null
    else
      echo "(none)"
    fi
    echo "devices Paired:"
    bluetoothctl devices Paired 2>/dev/null || echo "(none)"
    echo
  } | tee "${latest}" >>"${hist}"
  # Cap history ~2000 lines
  if [[ -f "${hist}" ]]; then
    local lines
    lines="$(wc -l <"${hist}" | tr -d ' ')"
    if [[ "${lines}" -gt 2000 ]]; then
      tail -n 1500 "${hist}" >"${hist}.tmp" && mv "${hist}.tmp" "${hist}"
    fi
  fi
  append_event "BT dump → ${latest}"
}

load_config() {
  local candidates=()
  if [[ -n "${OBD_BRIDGE_CONFIG:-}" ]]; then
    candidates+=("${OBD_BRIDGE_CONFIG}")
  fi
  candidates+=("${CONFIG_ENV}")
  if [[ -n "${REPO_ROOT:-}" ]]; then
    candidates+=("${REPO_ROOT}/config.env")
  fi
  # When sourced from repo scripts before install
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  candidates+=("${here}/config.env")

  local loaded=0 cfg
  for cfg in "${candidates[@]}"; do
    if [[ -f "${cfg}" ]]; then
      # shellcheck disable=SC1090
      set -a
      # shellcheck disable=SC1090
      source "${cfg}"
      set +a
      loaded=1
      break
    fi
  done

  if [[ "${loaded}" -ne 1 ]]; then
    err "No config.env found (tried: ${candidates[*]})"
    return 1
  fi

  if [[ -f "${DEVICE_ENV}" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck disable=SC1090
    source "${DEVICE_ENV}"
    set +a
  fi

  AP_SSID="${AP_SSID:-obd-bridge}"
  AP_PASS="${AP_PASS:-obdbridge1}"
  AP_IP="${AP_IP:-192.168.4.1}"
  AP_CIDR="${AP_CIDR:-24}"
  AP_DHCP_START="${AP_DHCP_START:-192.168.4.50}"
  AP_DHCP_END="${AP_DHCP_END:-192.168.4.150}"
  AP_IFACE="${AP_IFACE:-wlan0}"
  ELM_TCP_PORT="${ELM_TCP_PORT:-35000}"
  RFCOMM_DEV="${RFCOMM_DEV:-/dev/rfcomm0}"
  RFCOMM_CHANNEL="${RFCOMM_CHANNEL:-1}"
  BT_PIN="${BT_PIN:-1234}"
  BT_NAME_REGEX="${BT_NAME_REGEX:-OBDII|ELM327|V-LINK|BAFX|OBD}"
  BT_SCAN_SECONDS="${BT_SCAN_SECONDS:-20}"
  RFCOMM_RETRY_SECONDS="${RFCOMM_RETRY_SECONDS:-5}"
  PROXY_WAIT_SECONDS="${PROXY_WAIT_SECONDS:-2}"
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    err "Run as root (sudo)."
    exit 1
  fi
}

bt_adapter_ready() {
  command -v bluetoothctl >/dev/null 2>&1 || return 1
  bluetoothctl show >/dev/null 2>&1
}
