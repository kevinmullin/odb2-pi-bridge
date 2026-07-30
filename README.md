# OBD Bridge (omni) — Pi · Mac · Simulator

Vehicle-agnostic **ELM327 bridge**: turn an Android-only classic Bluetooth OBD adapter (e.g. BAFX) into a **Wi‑Fi ELM327** on TCP `:35000` for **Car Scanner** / OBD Fusion on iPhone.

Works with **any typical OBD-II car within reason** (US 1996+), including:

- Subaru Crosstrek  
- Nissan Kicks  
- Other ELM327-compatible gas / light trucks  

Brand extras (CVT ATF, etc.) come from **Car Scanner manufacturer profiles** on a real car — not from this bridge.

```
Car ECU → BAFX (classic BT) → Pi or Mac → TCP :35000 → iPhone app
          or: make simulate (fake ECU) ──────────────────↗
```

## Quick paths

### 1) See gauges before the car (recommended first)

Requires Docker:

```bash
git clone https://github.com/kevinmullin/odb2-pi-bridge.git
cd odb2-pi-bridge
make simulate                 # PROFILE=generic
# make simulate PROFILE=subaru
# make simulate PROFILE=nissan
```

iPhone on the same Wi‑Fi → Car Scanner → Wi‑Fi → **your computer’s LAN IP** port **35000**.

Details: [simulator/README.md](simulator/README.md)

### 2) MacBook hardware connection test

```bash
make macos-setup
# 12V on OBD pin 16 → pair BAFX in System Settings → Bluetooth
obd-bridge-mac start
```

Docs: [macos/README.md](macos/README.md)

### 3) Raspberry Pi in-car deploy

```bash
sudo ./install.sh
```

Pi creates Wi‑Fi AP **`obd-bridge`** (password `obdbridge1` by default) at `192.168.4.1:35000`.

## Make / Docker

| Target | Purpose |
|--------|---------|
| `make build` / `make ci` | Lint in Docker (`bash -n`, ShellCheck, systemd units) |
| `make simulate` | ELM/ECU simulator on `:35000` |
| `make simulate-stop` | Stop simulator |
| `make macos-setup` | Host socat + LaunchAgent (macOS) |
| `make clean` | Remove project images/containers |

Bluetooth bridging is **not** run inside Docker (especially on Mac). Simulator and lint are containerized.

## Pi install (car)

1. Flash Raspberry Pi OS Lite (Pi 3 recommended), SSH, set Wi‑Fi country.  
2. Prefer **ethernet** during first install (`wlan0` becomes the AP).  
3. Clone repo, optional edit [`config.env`](config.env), then `sudo ./install.sh`.  
4. Ignition ON for pairing (or `sudo obd-bridge pair` later).  
5. iPhone → join **`obd-bridge`** → Car Scanner Wi‑Fi `192.168.4.1:35000`.  
6. Enable Subaru / Nissan / generic profile sensors in the app as needed.

```bash
obd-bridge status
sudo obd-bridge doctor
```

## Config (`config.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `AP_SSID` | `obd-bridge` | Pi access point name |
| `AP_PASS` | `obdbridge1` | WPA2 password (change it) |
| `AP_IP` | `192.168.4.1` | Pi address / ELM host |
| `ELM_TCP_PORT` | `35000` | Standard Wi‑Fi ELM327 port |
| `BT_PIN` | `1234` | Typical ELM327 PIN |
| `BT_NAME_REGEX` | `OBDII\|ELM327\|…` | Discovery name filter |
| `BT_MAC` | *(empty)* | Skip discovery if set |

Installed copy: `/etc/obd-bridge/config.env`

## Commands (Pi)

| Command | Purpose |
|---------|---------|
| `sudo ./install.sh` | Idempotent full setup |
| `sudo ./uninstall.sh` | Remove services |
| `sudo ./uninstall.sh --purge` | Also delete `/etc/obd-bridge` |
| `obd-bridge status` / `doctor` / `pair` | Operator helpers |

`SKIP_PAIR=1 sudo ./install.sh` skips Bluetooth pairing during install.

## Standard vs enhanced data

| Source | What you get |
|--------|----------------|
| Bridge + standard Mode 01 | Coolant, IAT, ambient, oil, catalyst (if ECU supports) |
| Car Scanner Subaru/Nissan profiles | Brand sensors (e.g. CVT fluid) on a **real** car |
| `make simulate` | Fake animated standard temps for UI dry-run |

## Validation

- [ ] `make build` passes  
- [ ] `make simulate` + Car Scanner shows moving temps  
- [ ] (Optional) Mac + 12V BAFX: `ATZ` via `nc`  
- [ ] Pi + car: live coolant/IAT; cold-start reconnect without SSH  

## Why no Bluetooth-in-Docker?

Docker Desktop on Mac cannot pass classic Bluetooth RFCOMM to Linux containers. On a Pi, host systemd is simpler and more reliable than privileged BlueZ-in-Docker. See [macos/README.md](macos/README.md).

## License

MIT
