# macOS bench bridge

Use a MacBook as classic-Bluetooth → TCP `:35000` for **connection** testing with a real BAFX/ELM dongle.

> Bluetooth does **not** run inside Docker on Mac. Use Docker for `make simulate` / `make build` only.

## When to use this

| Need | Use |
|------|-----|
| See gauges / overheat demo | [`GETTING_STARTED.md`](GETTING_STARTED.md) + `make simulate` |
| Prove BAFX pairs and `ATZ` works | This guide |
| Daily driver in the car | [`PI.md`](PI.md) |

## Bench power (no car)

BAFX needs **~12V on OBD pin 16**, not USB:

| Pin | Wire |
|-----|------|
| 16 | +12V wall wart |
| 4 and/or 5 | Ground |

Female OBD breakout / “OBD power supply” cable. LED on = ready to pair.

Without an ECU you get ELM `ATZ`/`ATI`. Live PIDs need a car or the simulator.

## Setup

```bash
make macos-setup
```

Installs Homebrew `socat`, LaunchAgent, and `obd-bridge-mac` → `~/.local/bin`.

1. Power the adapter (12V).
2. **System Settings → Bluetooth** → pair (PIN often `1234`).
3. Confirm serial device:

```bash
obd-bridge-mac find-device
obd-bridge-mac start
obd-bridge-mac doctor
```

4. Car Scanner → Wi‑Fi → **Mac LAN IP** port **35000** (same as simulator).

```bash
ipconfig getifaddr en0
```

## Commands

| Command | Purpose |
|---------|---------|
| `obd-bridge-mac find-device` | Show `/dev/cu.*` match |
| `obd-bridge-mac start` / `stop` | Background proxy |
| `obd-bridge-mac status` / `doctor` | Health |
| `make macos-setup` | Dependencies + LaunchAgent |

If multiple `cu.*` match, set `BT_CU_DEVICE` in [`macos/config.env`](../macos/config.env).

## Files

See [`macos/README.md`](../macos/README.md) for the short operator copy.
