#!/usr/bin/env python3
"""Mock /run/obd-bridge/live.env (+ status.env) for PiTFT desk testing.

Does not touch Bluetooth. Stop obd-bridge-live while this runs so it is not
overwritten, then restart live when finished.
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import time
from pathlib import Path

RUN_DIR = Path(os.environ.get("STATUS_DIR", "/run/obd-bridge"))
LIVE_FILE = RUN_DIR / "live.env"
STATUS_FILE = RUN_DIR / "status.env"

STOP = False


def on_signal(_sig: int, _frame: object) -> None:
    global STOP
    STOP = True


def write_live(
    *,
    coolant: int,
    oil: int,
    iat: int,
    ambient: int,
    rpm: int,
    ok: str,
    detail: str,
) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    LIVE_FILE.write_text(
        "\n".join(
            [
                f"COOLANT_C={coolant}",
                f"OIL_C={oil}",
                f"IAT_C={iat}",
                f"AMBIENT_C={ambient}",
                f"RPM={rpm}",
                f"OK={ok}",
                f"DETAIL={detail}",
                f"UPDATED={time.strftime('%Y-%m-%dT%H:%M:%S')}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def write_status(*, phase: str, detail: str) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    # Keep AP fields if a real status file already exists
    existing: dict[str, str] = {}
    if STATUS_FILE.is_file():
        for line in STATUS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    ssid = existing.get("SSID", os.environ.get("AP_SSID", "obd-bridge"))
    ap_pass = existing.get("AP_PASS", os.environ.get("AP_PASS", "obdbridge1"))
    ap_ip = existing.get("AP_IP", os.environ.get("AP_IP", "192.168.4.1"))
    port = existing.get("ELM_TCP_PORT", os.environ.get("ELM_TCP_PORT", "35000"))
    mac = existing.get("BT_MAC", os.environ.get("BT_MAC", "AA:BB:CC:DD:EE:FF"))

    STATUS_FILE.write_text(
        "\n".join(
            [
                f"PHASE={phase}",
                f"DETAIL={detail}",
                f"SSID={ssid}",
                f"AP_PASS={ap_pass}",
                f"AP_IP={ap_ip}",
                f"ELM_TCP_PORT={port}",
                f"BT_MAC={mac}",
                f"UPDATED={time.strftime('%Y-%m-%dT%H:%M:%S')}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    events = RUN_DIR / "events.log"
    with events.open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} mock {phase}: {detail}\n")



def scenario_values(name: str, t: float) -> tuple[int, int, int, int, int, str, str, str]:
    """Return coolant, oil, iat, ambient, rpm, ok, live_detail, phase."""
    if name == "overheat":
        # Climb from ~85 → 118 over ~75s, then hold hot
        climb = min(1.0, t / 75.0)
        coolant = int(85 + climb * 33)
        oil = int(95 + climb * 30)
        rpm = 2200 + int(climb * 800)
        phase = "paired"
        detail = "mock overheat" if coolant < 105 else "mock HOT"
        return coolant, oil, 35, 28, rpm, "1", detail, phase

    if name == "waiting":
        return 0, 0, 0, 0, 0, "0", "mock waiting for ECU", "scanning"

    # idle / normal: gentle sine so numbers visibly change
    coolant = int(88 + 4 * math.sin(t / 8.0))
    oil = int(98 + 3 * math.sin(t / 10.0 + 1))
    iat = int(32 + 2 * math.sin(t / 12.0))
    ambient = 24
    rpm = int(750 + 40 * math.sin(t / 5.0))
    return coolant, oil, iat, ambient, rpm, "1", "mock live", "paired"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock OBD live.env for PiTFT testing")
    parser.add_argument(
        "--scenario",
        choices=("normal", "overheat", "waiting"),
        default="normal",
        help="normal=LIVE temps, overheat=climb to red, waiting=WAIT badge",
    )
    parser.add_argument("--interval", type=float, default=0.5, help="Update period seconds")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write one snapshot and exit (no loop)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    print(
        f"mock-live: writing {LIVE_FILE} scenario={args.scenario} "
        f"(Ctrl-C to stop; then: sudo systemctl start obd-bridge-live)",
        flush=True,
    )

    t0 = time.time()
    while not STOP:
        elapsed = time.time() - t0
        coolant, oil, iat, ambient, rpm, ok, detail, phase = scenario_values(
            args.scenario, elapsed
        )
        if args.scenario == "waiting":
            # Empty strings → TFT shows "--"
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            LIVE_FILE.write_text(
                "\n".join(
                    [
                        "COOLANT_C=",
                        "OIL_C=",
                        "IAT_C=",
                        "AMBIENT_C=",
                        "RPM=",
                        "OK=0",
                        f"DETAIL={detail}",
                        f"UPDATED={time.strftime('%Y-%m-%dT%H:%M:%S')}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
        else:
            write_live(
                coolant=coolant,
                oil=oil,
                iat=iat,
                ambient=ambient,
                rpm=rpm,
                ok=ok,
                detail=detail,
            )

        write_status(phase=phase, detail=detail)
        if args.once:
            print(f"wrote snapshot ok={ok} coolant={coolant} phase={phase}", flush=True)
            return
        time.sleep(args.interval)

    print("mock-live: stopped", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"mock-live failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
