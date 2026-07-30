# Raspberry Pi in-car bridge

Turns an Android-only classic Bluetooth ELM327/BAFX into a Wi‑Fi ELM327 AP for iPhone apps. Vehicle-agnostic (Crosstrek, Kicks, other OBD-II).

```mermaid
flowchart LR
  ECU[Vehicle ECU] --> BAFX[BAFX classic BT]
  BAFX --> Pi[Raspberry Pi 3]
  Pi -->|"AP obd-bridge :35000"| Phone[Car Scanner]
```

## Prerequisites

- Raspberry Pi 3 (recommended) with Raspberry Pi OS Lite
- SSH access; Wi‑Fi country set (`raspi-config`)
- Ethernet for first install (AP takes over `wlan0`)
- BAFX powered (ignition ON) during pairing

## Install

```bash
git clone https://github.com/kevinmullin/odb2-pi-bridge.git
cd odb2-pi-bridge
# optional: edit config.env (SSID / password / BT_MAC)
sudo ./install.sh
```

Defaults:

| Setting | Value |
|---------|--------|
| SSID | `obd-bridge` |
| Password | `obdbridge1` |
| ELM host | `192.168.4.1:35000` |

## iPhone

1. Join Wi‑Fi **`obd-bridge`**.
2. Car Scanner → Wi‑Fi → `192.168.4.1` port `35000`.
3. Enable Subaru / Nissan / generic manufacturer sensors in the app as needed.

![Wi-Fi settings illustration](images/car-scanner-wifi-settings.png)

*Use `192.168.4.1` on the Pi AP (not your home LAN IP).*

## Operator commands

```bash
obd-bridge status
sudo obd-bridge doctor
sudo obd-bridge pair          # if adapter was off during install
```

Skip pairing at install: `SKIP_PAIR=1 sudo ./install.sh`

## Uninstall

```bash
sudo ./uninstall.sh
sudo ./uninstall.sh --purge
```

## Runtime services

- `obd-bridge-rfcomm` — reconnect Bluetooth SPP when ignition returns  
- `obd-bridge-proxy` — `socat` TCP `:35000` ↔ `/dev/rfcomm0`  
- `obd-bridge-health.timer` — journal status  

## Validation

- [ ] `obd-bridge doctor` OK with BAFX powered  
- [ ] Reboot Pi, car off → AP still up  
- [ ] Ignition ON → within ~60s, apps connect  
- [ ] Cold-start reconnect without SSH  
