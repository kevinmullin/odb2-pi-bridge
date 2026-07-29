#!/usr/bin/env bash
# Bind RFCOMM to the saved BAFX MAC and keep the link alive.
# When the car powers off the adapter, rfcomm exits and we retry.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

load_config

if [[ -z "${BT_MAC:-}" ]]; then
  err "BT_MAC not set. Run: sudo obd-bridge pair"
  exit 1
fi

BT_MAC="$(echo "${BT_MAC}" | tr '[:lower:]' '[:upper:]')"
CHANNEL="${RFCOMM_CHANNEL}"
DEV="${RFCOMM_DEV}"
# rfcomm wants a device number (0 for /dev/rfcomm0)
DEV_NUM="$(basename "${DEV}" | sed 's/rfcomm//')"

cleanup() {
  rfcomm release "${DEV_NUM}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if ! command -v rfcomm >/dev/null 2>&1; then
  err "rfcomm not found (install bluez)"
  exit 1
fi

log "RFCOMM supervisor for ${BT_MAC} -> ${DEV} (channel ${CHANNEL})"

while true; do
  bluetoothctl power on >/dev/null 2>&1 || true
  bluetoothctl connect "${BT_MAC}" >/dev/null 2>&1 || true

  rfcomm release "${DEV_NUM}" >/dev/null 2>&1 || true

  log "Connecting ${DEV}…"
  set +e
  # Blocks while the SPP session is up; creates /dev/rfcommN
  rfcomm connect "${DEV_NUM}" "${BT_MAC}" "${CHANNEL}"
  rc=$?
  set -e

  err "RFCOMM disconnected (rc=${rc}); retrying in ${RFCOMM_RETRY_SECONDS}s"
  rfcomm release "${DEV_NUM}" >/dev/null 2>&1 || true
  sleep "${RFCOMM_RETRY_SECONDS}"
done
