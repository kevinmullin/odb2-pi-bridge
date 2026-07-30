#!/usr/bin/env bash
# Install Homebrew socat and optional LaunchAgent for the macOS bridge.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "${ROOT}/.." && pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup is for macOS only." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh" >&2
  exit 1
fi

brew list socat >/dev/null 2>&1 || brew install socat

mkdir -p "${HOME}/Library/LaunchAgents"
PLIST_SRC="${ROOT}/launchd/com.obdbridge.proxy.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/com.obdbridge.proxy.plist"

# Render absolute paths into the installed plist
SOCAT_PROXY="${ROOT}/scripts/proxy.sh"
sed \
  -e "s|@PROXY_SCRIPT@|${SOCAT_PROXY}|g" \
  -e "s|@REPO_ROOT@|${REPO_ROOT}|g" \
  -e "s|@HOME@|${HOME}|g" \
  "${PLIST_SRC}" >"${PLIST_DST}"

launchctl bootout "gui/$(id -u)/com.obdbridge.proxy" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${PLIST_DST}" 2>/dev/null || launchctl load "${PLIST_DST}" 2>/dev/null || true

chmod +x "${ROOT}/bin/obd-bridge-mac" "${ROOT}/scripts/"*.sh

# Symlink CLI if not already on PATH via repo
mkdir -p "${HOME}/.local/bin"
ln -sfn "${ROOT}/bin/obd-bridge-mac" "${HOME}/.local/bin/obd-bridge-mac"

cat <<EOF
macOS setup complete.

  socat: $(command -v socat)
  CLI:   ${HOME}/.local/bin/obd-bridge-mac  (ensure ~/.local/bin is on PATH)
  Agent: ${PLIST_DST} (loaded; starts proxy when you log in)

Next:
  1. Power BAFX (12V OBD pin 16) and pair in System Settings → Bluetooth (PIN 1234)
  2. obd-bridge-mac find-device
  3. obd-bridge-mac start   # or rely on LaunchAgent
  4. Car Scanner → Wi-Fi → <Mac LAN IP>:35000

For visuals without hardware: from repo root run  make simulate
EOF
