# Adafruit PiTFT 2.8" resistive (320×240)

Use the **resistive** PiTFT (`--display=28r`) as a local status panel: live temps, SSID/password, pair state, and **Pair / Re-pair** without SSH or home Wi‑Fi.

## Important: which Adafruit install type

| Adafruit `--install-type` | What you see | Use with OBD UI? |
|---------------------------|--------------|------------------|
| **`drivers`** (preferred) | TFT stays black until our app draws | **Yes** — HDMI keeps the login CLI |
| `console` | Login / CLI on the TFT | No — CLI owns the panel; UI never appears |
| `mirror` / `fbcp` | TFT copies HDMI | No — mirror fights pygame |

Do **not** use `console` or `mirror` for this project.

## Install order (home, with ethernet)

1. Flash Raspberry Pi OS Lite, SSH user/pass, Wi‑Fi country, ethernet.
2. Seat the PiTFT on the GPIO header (power off while attaching).
3. Install Adafruit drivers (**resistive**, **drivers only**):

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-venv
python3 -m venv ~/pitft-venv
source ~/pitft-venv/bin/activate
pip install --upgrade adafruit-python-shell click
git clone https://github.com/adafruit/Raspberry-Pi-Installer-Scripts.git
cd Raspberry-Pi-Installer-Scripts
# Prefer drivers-only (latest script). If click rejects "drivers", run
# interactively and answer No to console and No to HDMI mirror.
sudo -E env PATH=$PATH python3 adafruit-pitft.py \
  --display=28r --rotation=270 --install-type=drivers --reboot=yes
```

4. After reboot, confirm a display path exists:

```bash
ls -l /dev/fb1 /dev/dri/card* 2>/dev/null
```

Either `/dev/fb1` or a DRM card under `/dev/dri/` is enough.

5. Install OBD bridge (enables autopair + PiTFT UI by default):

```bash
cd ~
git clone https://github.com/kevinmullin/odb2-pi-bridge.git
cd odb2-pi-bridge
# optional: SKIP_PAIR=1 if BAFX not powered at the desk
sudo SKIP_PAIR=1 ./install.sh
sudo reboot
```

After reboot the TFT should show the **Temps** UI (not a text login).

## Already installed with console / mirror?

That matches “TFT only shows CLI / mirrors HDMI.” Fix:

```bash
cd ~/Raspberry-Pi-Installer-Scripts
git pull
source ~/pitft-venv/bin/activate   # if you used a venv
sudo -E env PATH=$PATH python3 adafruit-pitft.py \
  --display=28r --rotation=270 --install-type=drivers --reboot=yes
```

Then refresh the bridge UI:

```bash
cd ~/odb2-pi-bridge
git pull
sudo ./install.sh
sudo systemctl restart obd-bridge-pitft
sudo journalctl -u obd-bridge-pitft -n 40 --no-pager
```

You want a log line like `pitft_ui: display ok driver=…`.

Quick checks while diagnosing:

```bash
systemctl status obd-bridge-pitft --no-pager
ps aux | grep -E 'fbcp|con2fbmap|pitft' | grep -v grep
# If fbcp is running, stop it:
sudo systemctl disable --now fbcp.service 2>/dev/null || true
sudo pkill -x fbcp || true
```

## What the screen shows

**Temps page (default)** — no phone required:

- Coolant / Oil / IAT / Ambient (°C)
- RPM
- LIVE / WAIT badge (turns LIVE when coolant PID responds)
- Values turn yellow/red when hot

**Status page** (tap **Temps/Stat**):

- Wi‑Fi SSID + password
- ELM `192.168.4.1:35000`
- BT MAC / pair phase

Buttons: **Temps/Stat** · **Pair** · **Restart**

Live data comes from `obd-bridge-live` (polls the car over Bluetooth). Phone apps can still use `:35000` if you want; the PiTFT does not need them.

## Car use (no home Wi‑Fi)

1. Power Pi + BAFX in OBD port, ignition ON.  
2. Screen should move waiting → scanning → paired.  
3. iPhone joins `obd-bridge` → Car Scanner → `192.168.4.1:35000`.

Autopair keeps retrying until the adapter is found — no SSH required.

## Survives reboot?

Yes. `install.sh` enables `obd-bridge-pitft` (and `obd-bridge-live`) under systemd. After reboot the UI starts again once `/dev/fb1` (or DRM) is present. `/run/obd-bridge/*.env` is tmpfs and is rewritten by the live/autopair services.

## Desk test without the car (mock temps)

Feeds fake coolant/oil/IAT/RPM into the same files the TFT reads:

```bash
# after git pull + sudo SKIP_PAIR=1 ./install.sh
sudo obd-bridge mock-live                 # normal LIVE temps (values drift)
# other terminal / later:
sudo obd-bridge mock-live --scenario overheat   # climb into yellow/red
sudo obd-bridge mock-live --scenario waiting    # WAIT badge / blanks

# when finished:
sudo obd-bridge mock-stop                 # restores real live polling
```

While mock runs, tap **Temps/Stat**, **Pair**, **Restart** on the panel. Pair/Restart still hit real systemd units (safe on the desk).

## Disable UI

In `/etc/obd-bridge/config.env` (or repo `config.env` before install):

```bash
ENABLE_PITFT=0
```

Then `sudo systemctl disable --now obd-bridge-pitft`.

## Troubleshooting

| Issue | Check |
|-------|--------|
| TFT shows only CLI / HDMI mirror | Re-run Adafruit with `--install-type=drivers` (not `console` / `mirror`) |
| Black screen + `fbcon not available` | Normal on Bookworm — UI falls back to direct `/dev/fb1` blit. `git pull` + reinstall. Optional: add `,drm` to the `pitft28-resistive` dtoverlay and reboot for KMS |
| `EGL not initialized` | `sudo apt install libegl1 libgbm1` then restart the service |
| Black screen | `journalctl -u obd-bridge-pitft`; look for `display ok backend=` |
| UI not starting | Needs `/dev/fb1` or `/dev/dri/card*` |
| Wrong DRM card | Set `SDL_KMSDRM_DEVICE_INDEX=0` (or `1`/`2`) in the unit / `config.env` |
| No touch | Resistive needs firm press; `ls /dev/input/event*` |
| Pair never completes | Ignition ON, LED on, `journalctl -u obd-bridge-autopair -f` |

Official Adafruit guide: [PiTFT 2.8" resistive Easy Install](https://learn.adafruit.com/adafruit-pitft-28-inch-resistive-touchscreen-display-raspberry-pi/easy-install-2)
