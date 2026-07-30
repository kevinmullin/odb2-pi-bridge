# Getting started

Do this first. You only need **Docker** on your Mac and **Car Scanner ELM OBD2** on your iPhone. No car, no BAFX, no Pi yet.

## What you will see

1. Terminal smoke test passes (`ELM327`, coolant PID).
2. Car Scanner connects over Wi‑Fi to your Mac.
3. Live gauges move (normal or overheat scenario).

```mermaid
flowchart LR
  Docker["make simulate"] --> TCP["TCP :35000"]
  TCP --> App["Car Scanner on iPhone"]
```

## Step 1 — Start the fake ECU

```bash
cd /path/to/odb2-pi-bridge   # or: cd ~/workspace/obd2
make simulate
```

Leave that terminal open. Example:

```text
Simulator: PROFILE=generic SCENARIO=normal on 0.0.0.0:35000
Car Scanner → Wi-Fi → <this-machine-LAN-IP> port 35000
```

## Step 2 — Smoke-test on the Mac

**Do not use bare `nc`.** On macOS it often shows only `>` even when the sim works.

```bash
make simulate-test
```

Expected:

```text
...
ELM327 v2.1
...
OK
...
41 05 ...
OK
```

## Step 3 — Find your Mac’s LAN IP

```bash
ipconfig getifaddr en0
```

Example: `192.168.1.13` (yours will differ on other networks).

## Step 4 — Connect Car Scanner

1. iPhone on the **same Wi‑Fi** as the Mac (not hotspot-only / cellular).
2. Open **Car Scanner ELM OBD2**.
3. Add adapter → **Wi‑Fi**:
   - **IP:** your Mac LAN IP (e.g. `192.168.1.13`)
   - **Port:** `35000`
4. Connect.

![Car Scanner Wi-Fi settings (illustration)](images/car-scanner-wifi-settings.png)

*Illustration — match IP/port to your Mac; UI labels vary by app version.*

## Step 5 — Add gauges

Add coolant, oil, IAT, RPM. Values should update continuously.

### Optional: simulate overheating

Restart the sim with the overheat scenario, then reconnect in the app:

```bash
make simulate SCENARIO=overheat
```

Coolant climbs ~90°C → ~128°C over ~75 seconds. Near the end, DTC **P0217** may appear.

![Overheat gauges (illustration)](images/car-scanner-overheat-gauges.png)

## Stop the simulator

```bash
make simulate-stop
```

## Next steps

| Goal | Guide |
|------|--------|
| Profiles / scenarios detail | [SIMULATOR.md](SIMULATOR.md) |
| Real Bluetooth BAFX on Mac | [MACOS.md](MACOS.md) |
| Pi in the car | [PI.md](PI.md) |
| App says “no car” / ignition | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

## Vehicles (omni)

The bridge and simulator are **brand-agnostic**. Examples: Subaru Crosstrek, Nissan Kicks, other OBD-II cars. Enhanced manufacturer PIDs need Car Scanner’s vehicle profiles on a **real** car.
