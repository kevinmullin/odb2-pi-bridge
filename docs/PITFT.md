# Adafruit PiTFT 2.8" resistive (320×240)

Use the **resistive** PiTFT (`--display=28r`) as a local status panel: SSID/password, pair state, and **Pair / Re-pair** without SSH or home Wi‑Fi.

## Install order (home, with ethernet)

1. Flash Raspberry Pi OS Lite, SSH user/pass, Wi‑Fi country, ethernet.
2. Seat the PiTFT on the GPIO header (power off while attaching).
3. Install Adafruit drivers (**resistive**):

```bash
sudo apt-get update
sudo apt-get install -y git python3-pip
pip3 install --upgrade adafruit-python-shell click
# Bookworm: use a venv if required — see Adafruit PiTFT Easy Install docs
git clone https://github.com/adafruit/Raspberry-Pi-Installer-Scripts.git
cd Raspberry-Pi-Installer-Scripts
sudo -E env PATH=$PATH python3 adafruit-pitft.py --display=28r --rotation=270 --install-type=console
sudo reboot
```

4. Confirm framebuffer:

```bash
ls -l /dev/fb1
```

5. Install OBD bridge (enables autopair + PiTFT UI by default):

```bash
cd ~
git clone https://github.com/kevinmullin/odb2-pi-bridge.git
cd odb2-pi-bridge
# optional: SKIP_PAIR=1 if BAFX not powered at the desk
sudo SKIP_PAIR=1 ./install.sh
sudo reboot
```

## What the screen shows

- Wi‑Fi SSID + password (`obd-bridge` / `obdbridge1` by default)
- ELM address `192.168.4.1:35000`
- BT MAC or “(not paired)”
- Phase: waiting / scanning / paired
- **Pair / Re-pair** — clears saved MAC and kicks autopair
- **Restart** — restarts RFCOMM + proxy

## Car use (no home Wi‑Fi)

1. Power Pi + BAFX in OBD port, ignition ON.  
2. Screen should move waiting → scanning → paired.  
3. iPhone joins `obd-bridge` → Car Scanner → `192.168.4.1:35000`.

Autopair keeps retrying until the adapter is found — no SSH required.

## Disable UI

In `/etc/obd-bridge/config.env` (or repo `config.env` before install):

```bash
ENABLE_PITFT=0
```

Then `sudo systemctl disable --now obd-bridge-pitft`.

## Troubleshooting

| Issue | Check |
|-------|--------|
| Black screen | Adafruit `28r` install, `/dev/fb1`, `journalctl -u obd-bridge-pitft` |
| No touch | Resistive needs firm press; `ls /dev/input/event*` |
| UI not starting | `ConditionPathExists=/dev/fb1` — install PiTFT first |
| Pair never completes | Ignition ON, LED on, `journalctl -u obd-bridge-autopair -f` |

Official Adafruit guide: [PiTFT 2.8" resistive Easy Install](https://learn.adafruit.com/adafruit-pitft-28-inch-resistive-touchscreen-display-raspberry-pi/easy-install-2)
