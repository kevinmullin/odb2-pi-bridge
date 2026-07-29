# OBD Bridge (Pi → iPhone)

Turn an **Android-only classic Bluetooth** ELM327 / BAFX adapter into a **Wi‑Fi ELM327** on a Raspberry Pi so **Car Scanner** (or OBD Fusion) on iPhone can read live data — including temps on a Subaru Crosstrek.

```
Car ECU → BAFX (classic BT) → Raspberry Pi 3 → Wi-Fi AP + TCP :35000 → iPhone app
```

Target board for testing: **Raspberry Pi 3** (works on other Pi boards with classic Bluetooth).

## What is automated

After Raspberry Pi OS is on the SD card and the Pi has network **once** for `apt`:

```bash
sudo ./install.sh
```

That installs packages, Wi‑Fi AP, Bluetooth pairing (if the adapter is powered), systemd services, and enables boot/ignition reconnect. No SSH needed for normal car use after that.

## Still manual

1. Flash **Raspberry Pi OS Lite**, enable SSH, set Wi‑Fi country (`raspi-config`).
2. Plug in BAFX + power the Pi (physical).
3. Prefer **ethernet** during first install (AP mode takes over `wlan0`).
4. iPhone: install **Car Scanner ELM OBD2**, join the Pi SSID, set Wi‑Fi adapter IP/port once.

## Quick start

1. Clone on the Pi (with internet):

   ```bash
   git clone https://github.com/kevinmullin/odb2-pi-bridge.git
   cd odb2-pi-bridge
   # optional: edit config.env (SSID / password / BT_MAC)
   sudo ./install.sh
   ```

2. Ignition **ON** so the BAFX is powered during install (or run `sudo obd-bridge pair` later).

3. On iPhone:
   - Join Wi‑Fi **`crosstrek-obd`** / password **`obdbridge1`** (defaults in `config.env`)
   - Car Scanner → connection **Wi‑Fi** → **`192.168.4.1`** port **`35000`**
   - Add gauges (coolant, IAT, ambient, oil, catalyst) and any **Subaru** profile sensors for CVT/ATF temps

4. Check health:

   ```bash
   obd-bridge status
   sudo obd-bridge doctor
   ```

## Config (`config.env`)

| Variable | Default | Meaning |
|----------|---------|---------|
| `AP_SSID` | `crosstrek-obd` | Pi access point name |
| `AP_PASS` | `obdbridge1` | WPA2 password (change it) |
| `AP_IP` | `192.168.4.1` | Pi address / ELM host |
| `ELM_TCP_PORT` | `35000` | Standard Wi‑Fi ELM327 port |
| `BT_PIN` | `1234` | Typical ELM327 PIN |
| `BT_NAME_REGEX` | `OBDII\|ELM327\|…` | Discovery name filter |
| `BT_MAC` | *(empty)* | Skip discovery if set |

Installed copy: `/etc/obd-bridge/config.env`  
Paired adapter: `/etc/obd-bridge/device.env`

## Commands

| Command | Purpose |
|---------|---------|
| `sudo ./install.sh` | Idempotent full setup |
| `sudo ./uninstall.sh` | Remove services (keeps `/etc/obd-bridge`) |
| `sudo ./uninstall.sh --purge` | Also delete config/device env |
| `obd-bridge status` | AP / BT / RFCOMM / TCP |
| `obd-bridge doctor` | Actionable failures |
| `sudo obd-bridge pair` | Re-discover / pair BAFX |

Skip pairing during install: `sudo SKIP_PAIR=1 ./install.sh`

## Runtime behavior

- **`obd-bridge-rfcomm`**: reconnects classic Bluetooth SPP whenever the adapter appears (ignition ON).
- **`obd-bridge-proxy`**: `socat` TCP `:35000` ↔ `/dev/rfcomm0` (Wi‑Fi ELM327 compatible).
- **`obd-bridge-health.timer`**: periodic journal status lines.

## Validation checklist

- [ ] `sudo ./install.sh` with BAFX powered → `obd-bridge doctor` mostly OK
- [ ] Reboot Pi with car off → AP still up; services retry without crashing
- [ ] Ignition ON → within ~60s, from a client on the AP:  
      `printf 'ATZ\r' | nc 192.168.4.1 35000`
- [ ] Car Scanner shows live coolant + IAT; cold-start reconnect works without SSH

## Uninstall

```bash
sudo ./uninstall.sh          # keep /etc/obd-bridge
sudo ./uninstall.sh --purge  # remove everything bridge-related
```

`hostapd` / `dnsmasq` packages remain installed.

## CI

GitHub Actions runs `bash -n` and ShellCheck on scripts (no hardware Bluetooth/AP test on hosted runners).

## License

MIT
