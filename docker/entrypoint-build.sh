#!/usr/bin/env bash
# Containerized lint suite for obd-bridge (bash -n, shellcheck, systemd sanity).
set -euo pipefail

cd /src

mapfile -t files < <(
  find . -type f \( -name '*.sh' -o -path './bin/*' -o -path './macos/bin/*' \) \
    ! -path './.git/*' ! -path './simulator/.venv/*' \
    | sort
)

if [[ "${#files[@]}" -eq 0 ]]; then
  echo "ERROR: no scripts found" >&2
  exit 1
fi

echo "== scripts (${#files[@]}) =="
printf '  %s\n' "${files[@]}"

echo "== bash -n =="
for f in "${files[@]}"; do
  echo "bash -n $f"
  bash -n "$f"
done

echo "== shellcheck =="
# SC1091: install-time sourced paths
shellcheck -x -e SC1091 "${files[@]}"

echo "== systemd unit sanity =="
shopt -s nullglob
units=(systemd/*.service systemd/*.timer)
if [[ "${#units[@]}" -eq 0 ]]; then
  echo "ERROR: no systemd units" >&2
  exit 1
fi
for u in "${units[@]}"; do
  test -s "$u"
  grep -q '^\[Unit\]' "$u"
  grep -qE '^\[(Service|Timer)\]' "$u"
  echo "OK $u"
done

echo "== build OK =="
