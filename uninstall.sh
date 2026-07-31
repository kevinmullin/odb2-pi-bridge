#!/usr/bin/env bash
# Remove OBD Bridge services and configs. Keeps device.env unless --purge.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_ROOT}/scripts/lib.sh"

require_root

PURGE=0
if [[ "${1:-}" == "--purge" ]]; then
  PURGE=1
fi

AP_IFACE="${AP_IFACE:-wlan0}"
if [[ -f /etc/obd-bridge/config.env ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1091
  source /etc/obd-bridge/config.env
  set +a
fi

systemctl stop obd-bridge-proxy.service obd-bridge-rfcomm.service \
  obd-bridge-autopair.service obd-bridge-pitft.service \
  obd-bridge-health.timer obd-bridge-health.service 2>/dev/null || true
systemctl disable obd-bridge-proxy.service obd-bridge-rfcomm.service \
  obd-bridge-autopair.service obd-bridge-pitft.service \
  obd-bridge-health.timer 2>/dev/null || true

rm -f /etc/systemd/system/obd-bridge-rfcomm.service
rm -f /etc/systemd/system/obd-bridge-proxy.service
rm -f /etc/systemd/system/obd-bridge-health.service
rm -f /etc/systemd/system/obd-bridge-health.timer
rm -f /etc/systemd/system/obd-bridge-autopair.service
rm -f /etc/systemd/system/obd-bridge-pitft.service
rm -f /etc/systemd/system/hostapd.service.d/override.conf
rmdir /etc/systemd/system/hostapd.service.d 2>/dev/null || true

rm -f /etc/hostapd/obd-bridge.conf
rm -f /etc/dnsmasq.d/obd-bridge.conf
rm -f /etc/systemd/network/10-obd-bridge-ap.network
rm -f /etc/NetworkManager/conf.d/99-obd-bridge-unmanaged.conf
rm -f /etc/systemd/resolved.conf.d/obd-bridge.conf

rm -rf /usr/local/lib/obd-bridge
rm -f /usr/local/bin/obd-bridge

if [[ "${PURGE}" -eq 1 ]]; then
  rm -rf /etc/obd-bridge
  log "Purged /etc/obd-bridge"
else
  log "Kept /etc/obd-bridge (use --purge to remove device.env/config)"
fi

systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true

log "Uninstall complete. hostapd/dnsmasq packages left installed."
