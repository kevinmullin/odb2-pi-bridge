# ELM327 / ECU simulator

Fake Wi‑Fi ELM327 on TCP **35000** for Car Scanner (and similar) visuals — no car, no BAFX.

## Run

```bash
make simulate                 # PROFILE=generic
make simulate PROFILE=subaru
make simulate PROFILE=nissan
make simulate-stop
```

On iPhone (same Wi‑Fi as the machine running Docker):

1. Install **Car Scanner ELM OBD2**
2. Connection type **Wi‑Fi**, IP = your Mac/PC LAN address, port **35000**
3. Add gauges: coolant, IAT, ambient, oil, catalyst, RPM, speed

## Profiles

| Profile | Feel |
|---------|------|
| `generic` | Mid passenger-car temp ranges |
| `subaru` | Slightly warmer coolant/oil (boxer-ish) |
| `nissan` | Compact crossover ambient/IAT bias |

All profiles use **standard Mode 01** PIDs only. Proprietary Subaru SSM / Nissan Consult are **not** simulated — use Car Scanner manufacturer profiles on a real vehicle for those.

## Supported PIDs (animated)

| PID | Signal |
|-----|--------|
| `0105` | Coolant temp |
| `010F` | Intake air temp |
| `0146` | Ambient air temp |
| `015C` | Engine oil temp |
| `013C` / `013D` | Catalyst temps |
| `010C` | RPM |
| `010D` | Vehicle speed |
| `0104` / `0111` | Load / throttle |

Plus ELM `AT*` handshake and Mode 01 capability bitmaps (`0100`, `0120`, `0140`).

## Manual test

```bash
printf 'ATZ\r' | nc 127.0.0.1 35000
printf '0105\r' | nc 127.0.0.1 35000
```
