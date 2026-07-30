#!/usr/bin/env bash
# Resolve a Bluetooth serial callout device for the ELM/BAFX adapter.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT}/config.env"

if [[ -n "${BT_CU_DEVICE:-}" ]]; then
  if [[ -e "${BT_CU_DEVICE}" ]]; then
    printf '%s\n' "${BT_CU_DEVICE}"
    exit 0
  fi
  echo "BT_CU_DEVICE=${BT_CU_DEVICE} not present" >&2
  exit 1
fi

shopt -s nullglob
candidates=(/dev/cu.*)
matches=()
for d in "${candidates[@]}"; do
  base="$(basename "${d}")"
  # Skip common non-OBD callouts
  case "${base}" in
    cu.Bluetooth-Incoming-Port|cu.Debug*|cu.debug*|cu.wlan*|cu.usbmodem*) continue ;;
  esac
  if echo "${base}" | grep -Eiq "${BT_CU_REGEX}"; then
    matches+=("${d}")
  fi
done

if [[ "${#matches[@]}" -eq 0 ]]; then
  echo "No /dev/cu.* matched /${BT_CU_REGEX}/" >&2
  echo "Pair the adapter in System Settings → Bluetooth, then retry." >&2
  echo "Available callouts:" >&2
  for d in /dev/cu.*; do
    [[ -e "${d}" ]] || continue
    printf '  %s\n' "${d}" >&2
  done
  exit 1
fi

if [[ "${#matches[@]}" -gt 1 ]]; then
  echo "Multiple matches; set BT_CU_DEVICE in macos/config.env:" >&2
  printf '  %s\n' "${matches[@]}" >&2
  exit 1
fi

printf '%s\n' "${matches[0]}"
