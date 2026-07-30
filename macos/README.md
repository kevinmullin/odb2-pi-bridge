# macOS bench bridge

Use a **MacBook** as a classic-Bluetooth → TCP `:35000` bridge for connection testing (BAFX / ELM327). Vehicle-agnostic — Crosstrek, Nissan Kicks, or any typical OBD-II car.

> **Bluetooth cannot run inside Docker on Mac.** Lint and the ELM **simulator** use Docker; this bridge runs on the host.

## Tier A — visuals (no hardware)

From repo root:

```bash
make simulate                 # or PROFILE=subaru|nissan
```

Car Scanner → Wi‑Fi → **Mac LAN IP** port **35000**. See [../simulator/README.md](../simulator/README.md).

## Tier B — real adapter (no car ECU)

### Power the BAFX without a car

The Bluetooth dongle needs **~12V**, not USB:

| OBD pin | Wire |
|---------|------|
| **16** | +12V (bench wall wart) |
| **4** and/or **5** | Ground |

Use a female OBD-II breakout / “OBD power supply” cable. LED should light and the adapter should advertise Bluetooth.

You can prove the link with `ATZ` / `ATI`. Live PIDs need a vehicle (or `make simulate`).

### Setup

```bash
make macos-setup
# Pair adapter: System Settings → Bluetooth (PIN usually 1234)
obd-bridge-mac find-device
obd-bridge-mac start
obd-bridge-mac doctor
```

Car Scanner → same Wi‑Fi as Mac → Wi‑Fi adapter → **Mac LAN IP**:`35000`.

```bash
printf 'ATZ\r' | nc <mac-lan-ip> 35000
```

### Commands

| Command | Purpose |
|---------|---------|
| `obd-bridge-mac find-device` | Show `/dev/cu.*` match |
| `obd-bridge-mac start` / `stop` | Background socat proxy |
| `obd-bridge-mac status` / `doctor` | Health |
| `make macos-setup` | brew `socat` + LaunchAgent |

Set `BT_CU_DEVICE=/dev/cu.…` in [`config.env`](config.env) if multiple devices match.

## Tier C — in a car

Prefer the **Raspberry Pi** install at repo root for ignition-auto reconnect. Same Car Scanner Wi‑Fi settings; enable **Subaru** / **Nissan** / generic manufacturer profiles inside the app for enhanced sensors.
