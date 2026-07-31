#!/usr/bin/env bash
# Idempotent install for OBD Bridge on Raspberry Pi OS (Pi 3+).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib.sh
source "${REPO_ROOT}/scripts/lib.sh"

OBD_BRIDGE_ETC="/etc/obd-bridge"
OBD_BRIDGE_LIB="/usr/local/lib/obd-bridge"
export REPO_ROOT OBD_BRIDGE_ETC OBD_BRIDGE_LIB

require_root
load_config

SKIP_PAIR="${SKIP_PAIR:-0}"
PAIR_ON_INSTALL="${PAIR_ON_INSTALL:-1}"
ENABLE_PITFT="${ENABLE_PITFT:-1}"

apt_install() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y --no-install-recommends \
    bluetooth bluez bluez-tools \
    hostapd dnsmasq socat rfkill \
    iproute2 iptables expect \
    net-tools python3 python3-pygame python3-serial \
    libegl1 libgbm1
}

unblock_radios() {
  rfkill unblock wifi || true
  rfkill unblock bluetooth || true
}

install_files() {
  mkdir -p "${OBD_BRIDGE_ETC}" "${OBD_BRIDGE_LIB}" /usr/local/bin

  install -m 0644 "${REPO_ROOT}/config.env" "${OBD_BRIDGE_ETC}/config.env"
  # Preserve existing device.env
  if [[ ! -f "${OBD_BRIDGE_ETC}/device.env" ]]; then
    touch "${OBD_BRIDGE_ETC}/device.env"
  fi

  install -m 0755 "${REPO_ROOT}/scripts/lib.sh" "${OBD_BRIDGE_LIB}/lib.sh"
  install -m 0755 "${REPO_ROOT}/scripts/pair-bafx.sh" "${OBD_BRIDGE_LIB}/pair-bafx.sh"
  install -m 0755 "${REPO_ROOT}/scripts/auto-pair.sh" "${OBD_BRIDGE_LIB}/auto-pair.sh"
  install -m 0755 "${REPO_ROOT}/scripts/rfcomm-bind.sh" "${OBD_BRIDGE_LIB}/rfcomm-bind.sh"
  install -m 0755 "${REPO_ROOT}/scripts/proxy.sh" "${OBD_BRIDGE_LIB}/proxy.sh"
  install -m 0755 "${REPO_ROOT}/scripts/healthcheck.sh" "${OBD_BRIDGE_LIB}/healthcheck.sh"
  install -m 0755 "${REPO_ROOT}/scripts/live_temps.py" "${OBD_BRIDGE_LIB}/live_temps.py"
  install -m 0755 "${REPO_ROOT}/pitft/ui.py" "${OBD_BRIDGE_LIB}/pitft_ui.py"
  install -m 0755 "${REPO_ROOT}/bin/obd-bridge" /usr/local/bin/obd-bridge

  # Reload config from installed copy
  CONFIG_ENV="${OBD_BRIDGE_ETC}/config.env"
  # shellcheck disable=SC1090
  set -a
  # shellcheck disable=SC1090
  source "${CONFIG_ENV}"
  set +a
}

render_ap_configs() {
  local hostapd_out="/etc/hostapd/obd-bridge.conf"
  local dnsmasq_out="/etc/dnsmasq.d/obd-bridge.conf"

  mkdir -p /etc/hostapd /etc/dnsmasq.d

  sed \
    -e "s/AP_IFACE/${AP_IFACE}/g" \
    -e "s/AP_SSID/${AP_SSID}/g" \
    -e "s/AP_PASS/${AP_PASS}/g" \
    "${REPO_ROOT}/hostapd/obd-bridge.conf" >"${hostapd_out}"

  sed \
    -e "s/AP_IFACE/${AP_IFACE}/g" \
    -e "s/AP_DHCP_START/${AP_DHCP_START}/g" \
    -e "s/AP_DHCP_END/${AP_DHCP_END}/g" \
    -e "s/AP_IP/${AP_IP}/g" \
    "${REPO_ROOT}/dnsmasq/obd-bridge.conf" >"${dnsmasq_out}"

  chmod 600 "${hostapd_out}"
  chmod 644 "${dnsmasq_out}"

  # Point hostapd at our config
  if [[ -f /etc/default/hostapd ]]; then
    if grep -q '^DAEMON_CONF=' /etc/default/hostapd; then
      sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/obd-bridge.conf"|' /etc/default/hostapd
    else
      echo 'DAEMON_CONF="/etc/hostapd/obd-bridge.conf"' >>/etc/default/hostapd
    fi
  else
    echo 'DAEMON_CONF="/etc/hostapd/obd-bridge.conf"' >/etc/default/hostapd
  fi

  # Ensure hostapd unit uses our config file
  mkdir -p /etc/systemd/system/hostapd.service.d
  cat >/etc/systemd/system/hostapd.service.d/override.conf <<EOF
[Unit]
After=sys-subsystem-net-devices-${AP_IFACE}.device
[Service]
ExecStart=
ExecStart=/usr/sbin/hostapd /etc/hostapd/obd-bridge.conf
EOF
}

configure_ap_interface() {
  # Stop client Wi-Fi on AP iface to avoid conflicts
  systemctl stop wpa_supplicant 2>/dev/null || true
  if systemctl list-unit-files 2>/dev/null | grep -q 'wpa_supplicant@'; then
    systemctl disable "wpa_supplicant@${AP_IFACE}" 2>/dev/null || true
    systemctl stop "wpa_supplicant@${AP_IFACE}" 2>/dev/null || true
  fi

  # NetworkManager: set unmanaged if present
  if command -v nmcli >/dev/null 2>&1; then
    mkdir -p /etc/NetworkManager/conf.d
    cat >/etc/NetworkManager/conf.d/99-obd-bridge-unmanaged.conf <<EOF
[keyfile]
unmanaged-devices=interface-name:${AP_IFACE}
EOF
    systemctl reload NetworkManager 2>/dev/null || true
  fi

  # dhcpcd: deny AP iface
  if [[ -f /etc/dhcpcd.conf ]]; then
    if ! grep -q "denyinterfaces ${AP_IFACE}" /etc/dhcpcd.conf; then
      echo "denyinterfaces ${AP_IFACE}" >>/etc/dhcpcd.conf
    fi
  fi

  ip link set "${AP_IFACE}" down || true
  ip addr flush dev "${AP_IFACE}" || true
  ip addr add "${AP_IP}/${AP_CIDR}" dev "${AP_IFACE}" || true
  ip link set "${AP_IFACE}" up || true

  # Persist static address via systemd network or rc if dhcpcd/NM unmanaged
  mkdir -p /etc/systemd/network
  cat >/etc/systemd/network/10-obd-bridge-ap.network <<EOF
[Match]
Name=${AP_IFACE}

[Network]
Address=${AP_IP}/${AP_CIDR}
IPForward=no
EOF
  systemctl enable systemd-networkd 2>/dev/null || true
}

configure_dnsmasq() {
  # Avoid conflict with systemd-resolved on some images
  if systemctl is-active systemd-resolved >/dev/null 2>&1; then
    mkdir -p /etc/systemd/resolved.conf.d
    cat >/etc/systemd/resolved.conf.d/obd-bridge.conf <<EOF
[Resolve]
DNSStubListener=no
EOF
    systemctl restart systemd-resolved 2>/dev/null || true
  fi

  # Ensure main dnsmasq doesn't bind everything conflicting; our snippet is enough
  if [[ -f /etc/dnsmasq.conf ]]; then
    if ! grep -q 'conf-dir=/etc/dnsmasq.d' /etc/dnsmasq.conf; then
      echo 'conf-dir=/etc/dnsmasq.d/,*.conf' >>/etc/dnsmasq.conf
    fi
  fi
}

install_systemd_units() {
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-rfcomm.service" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-proxy.service" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-health.service" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-health.timer" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-autopair.service" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-live.service" /etc/systemd/system/
  install -m 0644 "${REPO_ROOT}/systemd/obd-bridge-pitft.service" /etc/systemd/system/

  systemctl daemon-reload
  systemctl unmask hostapd 2>/dev/null || true
  systemctl enable hostapd dnsmasq
  systemctl enable obd-bridge-rfcomm.service
  systemctl enable obd-bridge-live.service
  systemctl enable obd-bridge-health.timer
  systemctl enable obd-bridge-autopair.service
  # Live hub replaces socat proxy (still installed for manual use)
  systemctl disable obd-bridge-proxy.service 2>/dev/null || true

  if [[ "${ENABLE_PITFT}" == "1" ]]; then
    systemctl enable obd-bridge-pitft.service
    log "PiTFT UI enabled (temps on screen; needs /dev/fb1 from Adafruit 28r)."
  fi

  systemctl restart hostapd || {
    err "hostapd failed to start — check Wi-Fi country code (raspi-config) and ${AP_IFACE}"
    journalctl -u hostapd -n 30 --no-pager || true
  }
  systemctl restart dnsmasq || {
    err "dnsmasq failed to start"
    journalctl -u dnsmasq -n 30 --no-pager || true
  }
}

maybe_pair() {
  if [[ "${SKIP_PAIR}" == "1" || "${PAIR_ON_INSTALL}" != "1" ]]; then
    log "Skipping Bluetooth pairing (SKIP_PAIR/PAIR_ON_INSTALL)."
    return 0
  fi
  if [[ -n "${BT_MAC:-}" ]] && [[ -f "${OBD_BRIDGE_ETC}/device.env" ]] && grep -q '^BT_MAC=.' "${OBD_BRIDGE_ETC}/device.env"; then
    log "device.env already has BT_MAC; refreshing trust…"
  fi
  if ! "${OBD_BRIDGE_LIB}/pair-bafx.sh"; then
    err "Pairing failed or adapter offline. AP/services are installed."
    err "In the car: ignition ON — autopair keeps retrying (no Wi-Fi needed)."
    err "Or: sudo obd-bridge pair   /   touch Pair on the PiTFT"
    return 0
  fi
}

start_bridge_services() {
  systemctl stop obd-bridge-proxy.service 2>/dev/null || true
  systemctl restart obd-bridge-autopair.service || true
  systemctl restart obd-bridge-rfcomm.service || true
  systemctl restart obd-bridge-live.service || true
  systemctl start obd-bridge-health.timer || true
  if [[ "${ENABLE_PITFT}" == "1" ]]; then
    systemctl restart obd-bridge-pitft.service || true
  fi
}

main() {
  log "Installing OBD Bridge from ${REPO_ROOT}"
  apt_install
  unblock_radios
  install_files
  render_ap_configs
  configure_ap_interface
  configure_dnsmasq
  install_systemd_units
  maybe_pair
  start_bridge_services

  log "Running doctor…"
  /usr/local/bin/obd-bridge doctor || true

  cat <<EOF

Install complete.

  Wi-Fi SSID: ${AP_SSID}
  Password:   ${AP_PASS}
  ELM TCP:    ${AP_IP}:${ELM_TCP_PORT}

iPhone: join the SSID, open Car Scanner → Wi-Fi adapter → ${AP_IP} port ${ELM_TCP_PORT}

Autopair retries in the background until BAFX is seen (ignition ON).
PiTFT (Adafruit 2.8 resistive): install display first, then this package — UI on /dev/fb1.

Commands: obd-bridge status | doctor | pair
EOF
}

main "$@"
