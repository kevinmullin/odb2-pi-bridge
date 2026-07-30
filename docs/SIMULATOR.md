# ELM327 / ECU simulator

Dockerized fake Wi‑Fi ELM327 on TCP **35000** for Car Scanner visuals without a vehicle.

## Quick commands

```bash
make simulate                          # normal, PROFILE=generic
make simulate PROFILE=subaru
make simulate PROFILE=nissan
make simulate SCENARIO=overheat        # coolant climb + P0217
make simulate-test                     # reliable ATZ / 0105 check
make simulate-stop
```

## Architecture

```mermaid
flowchart LR
  Phone[Car Scanner] -->|"Wi-Fi TCP MacIP:35000"| Ctn[obd-elm-sim container]
  Ctn --> PIDs[Mode 01 temps RPM voltage]
```

- Speaks ELM AT commands + OBD Mode 01/03/04/07/09.
- Defaults to **ignition ON**, **CAN protocol 6**, `SEARCHING...` on first OBD request, battery **13.8V**.
- Not a full Subaru SSM / Nissan Consult emulator.

## Profiles (`PROFILE=`)

| Profile | Coolant / oil “feel” |
|---------|----------------------|
| `generic` | Mid passenger-car baselines |
| `subaru` | Slightly warmer steady temps |
| `nissan` | Compact crossover ambient/IAT bias |

## Scenarios (`SCENARIO=`)

| Scenario | Behavior |
|----------|----------|
| `normal` | Gentle sine animation around baselines |
| `overheat` | Coolant ~90→128°C over ~75s; oil/IAT/catalyst rise; late **MIL** + **P0217** |

Timer starts when the container starts (survives Car Scanner reconnects). Restart the container to reset the ramp:

```bash
make simulate SCENARIO=overheat
```

![Overheat demo illustration](images/car-scanner-overheat-gauges.png)

## Supported live PIDs (high level)

| PID | Signal |
|-----|--------|
| `0105` | Coolant |
| `010F` | IAT |
| `0146` | Ambient |
| `015C` | Oil |
| `013C` / `013D` | Catalyst |
| `010C` / `010D` | RPM / speed |
| `0104` / `0111` | Load / throttle |
| `0142` | Module voltage |
| `ATRV` | Adapter voltage string |

Plus capability bitmaps (`0100` / `0120` / `0140`), VIN-ish Mode 09, and DTC read for overheat.

## Smoke test (preferred)

macOS `/usr/bin/nc` often **looks** blank because ELM uses `\r` without `\n`, and pipes close too fast.

```bash
make simulate-test
```

Or:

```bash
python3 simulator/smoke_test.py ATZ
python3 simulator/smoke_test.py 0105
```

If you must use `nc`:

```bash
(printf 'ATZ\r'; sleep 1) | nc 127.0.0.1 35000 | cat -v
```

## Files

| Path | Role |
|------|------|
| [`simulator/elm327_server.py`](../simulator/elm327_server.py) | TCP ELM/ECU server |
| [`simulator/Dockerfile`](../simulator/Dockerfile) | Image |
| [`simulator/smoke_test.py`](../simulator/smoke_test.py) | Host-side smoke test |
| [`simulator/README.md`](../simulator/README.md) | Short reference |

## Car Scanner connection

![Wi-Fi adapter settings illustration](images/car-scanner-wifi-settings.png)

IP = Mac LAN address from `ipconfig getifaddr en0`, port **35000**.
