#!/usr/bin/env python3
"""ELM327-over-TCP ECU simulator tuned for Car Scanner / similar apps.

Profiles: generic | subaru | nissan — standard Mode 01 PIDs with animated temps.
Simulates ignition-on CAN ECU (protocol 6) so apps get past 'no car' checks.
"""

from __future__ import annotations

import math
import os
import socketserver
import time

HOST = os.environ.get("ELM_HOST", "0.0.0.0")
PORT = int(os.environ.get("ELM_TCP_PORT", "35000"))
PROFILE = os.environ.get("PROFILE", "generic").strip().lower()
SCENARIO = os.environ.get("SCENARIO", "normal").strip().lower()

# Profile: (coolant_base, oil_base, iat_base, ambient_base, cat_base_C)
PROFILES = {
    "generic": (90.0, 100.0, 30.0, 22.0, 450.0),
    "subaru": (93.0, 105.0, 28.0, 20.0, 470.0),
    "nissan": (88.0, 98.0, 32.0, 24.0, 440.0),
}

SCENARIOS = ("normal", "overheat")
# Process start — overheat ramp continues across Car Scanner reconnects
SCENARIO_T0 = time.monotonic()


def temp_c_to_a(celsius: float) -> int:
    return max(0, min(255, int(round(celsius + 40))))


def cat_temp_to_ab(celsius: float) -> tuple[int, int]:
    raw = int(round((celsius + 40) * 10))
    raw = max(0, min(65535, raw))
    return (raw >> 8) & 0xFF, raw & 0xFF


class EcuState:
    def __init__(self, profile: str, scenario: str) -> None:
        if profile not in PROFILES:
            raise SystemExit(f"Unknown PROFILE={profile!r}; use generic|subaru|nissan")
        if scenario not in SCENARIOS:
            raise SystemExit(f"Unknown SCENARIO={scenario!r}; use normal|overheat")
        self.profile = profile
        self.scenario = scenario
        self.bases = PROFILES[profile]
        self.reset()

    def reset(self) -> None:
        self.t0 = time.monotonic()
        self.echo = True
        self.headers = False
        self.spaces = True
        self.linefeeds = False
        # 0 = auto (will resolve to CAN 6 on first OBD reply)
        self.protocol = "0"
        self.resolved_protocol = "6"
        self.need_searching = True
        self.ignition_on = True

    def anim(self, base: float, amp: float, period: float, phase: float = 0.0) -> float:
        t = time.monotonic() - self.t0
        return base + amp * math.sin(2 * math.pi * t / period + phase)

    def _overheat_progress(self) -> float:
        """0 → 1 over ~75s from process start, then hold at 1."""
        elapsed = time.monotonic() - SCENARIO_T0
        return max(0.0, min(1.0, elapsed / 75.0))

    def coolant(self) -> float:
        if self.scenario == "overheat":
            # Climb ~90°C → ~128°C (well into red / overheat territory)
            p = self._overheat_progress()
            return 90.0 + 38.0 * p + 1.5 * math.sin(time.monotonic() / 3.0)
        return self.anim(self.bases[0], 4.0, 45.0)

    def oil(self) -> float:
        if self.scenario == "overheat":
            p = self._overheat_progress()
            return 100.0 + 35.0 * p + 2.0 * math.sin(time.monotonic() / 4.0)
        return self.anim(self.bases[1], 5.0, 60.0, 0.5)

    def iat(self) -> float:
        if self.scenario == "overheat":
            p = self._overheat_progress()
            return self.bases[2] + 25.0 * p
        return self.anim(self.bases[2], 6.0, 35.0, 1.0)

    def ambient(self) -> float:
        return self.anim(self.bases[3], 3.0, 80.0, 1.5)

    def catalyst(self) -> float:
        if self.scenario == "overheat":
            p = self._overheat_progress()
            return self.bases[4] + 120.0 * p
        return self.anim(self.bases[4], 25.0, 50.0, 0.2)

    def rpm(self) -> int:
        if self.scenario == "overheat" and self._overheat_progress() > 0.7:
            # Slightly elevated / unstable idle once hot
            return int(self.anim(1100, 150, 2.5))
        return int(self.anim(850, 80, 4.0))

    def speed(self) -> int:
        return 0

    def voltage(self) -> str:
        return "13.8V"

    def has_overheat_dtc(self) -> bool:
        return self.scenario == "overheat" and self._overheat_progress() >= 0.85


STATE = EcuState(PROFILE, SCENARIO)

def fmt_bytes(data: list[int]) -> str:
    if STATE.spaces:
        return " ".join(f"{b:02X}" for b in data)
    return "".join(f"{b:02X}" for b in data)


def respond_obd(payload: list[int]) -> str:
    """Build ELM response; optional CAN header 7E8 + PCI length."""
    if STATE.headers:
        pci = len(payload)
        if STATE.spaces:
            return f"7E8 {pci:02X} " + fmt_bytes(payload)
        return f"7E8{pci:02X}" + fmt_bytes(payload)
    return fmt_bytes(payload)


def with_searching(body: str) -> str:
    if STATE.need_searching and STATE.protocol in ("0", "A", "AT"):
        STATE.need_searching = False
        STATE.protocol = STATE.resolved_protocol
        # Real ELM prints SEARCHING... then the response
        return f"SEARCHING...\r{body}"
    return body


def handle_pid(mode: int, pid: int) -> str | None:
    if mode != 0x01:
        return None

    # Capability bitmaps — claim temps + common live data
    if pid == 0x00:
        # 01-20: 01,04,05,0C,0D,0F,11,13 + more
        return respond_obd([0x41, 0x00, 0xBE, 0x3E, 0xB8, 0x11])
    if pid == 0x20:
        # 21-40: include 3C/3D catalyst and continue bit for 40
        return respond_obd([0x41, 0x20, 0x80, 0x00, 0x00, 0x01])
    if pid == 0x40:
        # 41-60: 42,45,46,5C …
        return respond_obd([0x41, 0x40, 0x7A, 0x00, 0x00, 0x10])
    if pid == 0x60:
        return respond_obd([0x41, 0x60, 0x00, 0x00, 0x00, 0x00])

    if pid == 0x01:  # monitor status since DTCs cleared
        # Bit7 of A = MIL on when overheat DTC is active
        a = 0x80 if STATE.has_overheat_dtc() else 0x00
        return respond_obd([0x41, 0x01, a, 0x07, 0xE5, 0xE5])
    if pid == 0x04:
        return respond_obd([0x41, 0x04, int(STATE.anim(100, 40, 7.0)) & 0xFF])
    if pid == 0x05:
        return respond_obd([0x41, 0x05, temp_c_to_a(STATE.coolant())])
    if pid == 0x0B:  # MAP
        return respond_obd([0x41, 0x0B, int(STATE.anim(100, 20, 5.0)) & 0xFF])
    if pid == 0x0C:
        raw = STATE.rpm() * 4
        return respond_obd([0x41, 0x0C, (raw >> 8) & 0xFF, raw & 0xFF])
    if pid == 0x0D:
        return respond_obd([0x41, 0x0D, STATE.speed() & 0xFF])
    if pid == 0x0F:
        return respond_obd([0x41, 0x0F, temp_c_to_a(STATE.iat())])
    if pid == 0x11:
        return respond_obd([0x41, 0x11, int(STATE.anim(40, 20, 6.0)) & 0xFF])
    if pid == 0x13:
        return respond_obd([0x41, 0x13, 0x03])
    if pid == 0x1C:  # OBD standard
        return respond_obd([0x41, 0x1C, 0x06])  # CAN EOBD
    if pid == 0x3C:
        a, b = cat_temp_to_ab(STATE.catalyst())
        return respond_obd([0x41, 0x3C, a, b])
    if pid == 0x3D:
        a, b = cat_temp_to_ab(STATE.catalyst() - 15)
        return respond_obd([0x41, 0x3D, a, b])
    if pid == 0x42:  # control module voltage
        # A*256+B / 1000 = V → 13.8V = 13800
        raw = 13800
        return respond_obd([0x41, 0x42, (raw >> 8) & 0xFF, raw & 0xFF])
    if pid == 0x46:
        return respond_obd([0x41, 0x46, temp_c_to_a(STATE.ambient())])
    if pid == 0x5C:
        return respond_obd([0x41, 0x5C, temp_c_to_a(STATE.oil())])

    return None


def handle_mode09(pid: int) -> str | None:
    if pid == 0x00:
        return respond_obd([0x49, 0x00, 0x55, 0x00, 0x00, 0x00])
    if pid == 0x02:
        vin = f"1N4SIM{PROFILE[:3].upper()}OBDBRIDGE"[:17].ljust(17)
        # Single-frame style many apps accept: 49 02 01 + ASCII
        return respond_obd([0x49, 0x02, 0x01] + [ord(c) for c in vin])
    if pid == 0x0A:  # ECU name
        name = f"OBD-SIM-{STATE.profile.upper()}"[:20].ljust(20)
        return respond_obd([0x49, 0x0A, 0x01] + [ord(c) for c in name])
    return None


def process_at(at: str) -> str:
    if at in ("Z", "WS"):
        STATE.reset()
        return "ELM327 v2.1"
    if at == "I":
        return "ELM327 v2.1"
    if len(at) == 2 and at[0] == "E" and at[1] in "01":
        STATE.echo = at[1] == "1"
        return "OK"
    if len(at) == 2 and at[0] == "H" and at[1] in "01":
        STATE.headers = at[1] == "1"
        return "OK"
    if len(at) == 2 and at[0] == "S" and at[1] in "01":
        STATE.spaces = at[1] == "1"
        return "OK"
    if len(at) == 2 and at[0] == "L" and at[1] in "01":
        STATE.linefeeds = at[1] == "1"
        return "OK"
    if at.startswith("SP"):
        # ATSP0 / ATSP00 / ATSPA / ATSP6 …
        arg = at[2:] or "0"
        STATE.protocol = arg.lstrip("0") or "0"
        if arg in ("0", "00", "A"):
            STATE.protocol = "0"
            STATE.need_searching = True
        else:
            STATE.resolved_protocol = arg[-1] if arg else "6"
            STATE.protocol = STATE.resolved_protocol
            STATE.need_searching = False
        return "OK"
    if at == "DP":
        if STATE.protocol == "0":
            return "AUTO"
        return "ISO 15765-4 (CAN 11/500)"
    if at == "DPN":
        # A = auto, 6 = ISO 15765-4 CAN (11 bit, 500 kbaud)
        if STATE.protocol == "0" and STATE.need_searching:
            return "A"
        return f"A{STATE.resolved_protocol}" if STATE.protocol == "0" else STATE.resolved_protocol
    if at in ("RV", "RVR"):
        return STATE.voltage()
    if at in ("@1", "DESC"):
        return "OBD-BRIDGE-SIM"
    if at == "@2":
        return f"sim-{STATE.profile}"
    if at.startswith("CAF") or at.startswith("CFC") or at.startswith("AL"):
        return "OK"
    if at.startswith("ST") or at.startswith("AT") or at.startswith("TA"):
        return "OK"
    if at.startswith("CRA") or at.startswith("CRA"):
        return "OK"
    # Ignition / adaptive / misc — accept so init never dies on '?'
    return "OK"


def process_command(raw: str) -> str:
    cmd = raw.strip().upper().replace(" ", "")
    if not cmd:
        return ""

    print(f"CMD {cmd!r}", flush=True)

    if cmd.startswith("AT"):
        return process_at(cmd[2:])

    try:
        if len(cmd) < 2 or any(c not in "0123456789ABCDEF" for c in cmd):
            return "?"

        mode = int(cmd[0:2], 16)

        if mode == 0x03:
            if STATE.has_overheat_dtc():
                # P0217 Engine Coolant Over-Temperature
                return with_searching(respond_obd([0x43, 0x01, 0x02, 0x17]))
            return with_searching("NO DATA")
        if mode == 0x04:
            return "OK"
        if mode == 0x07:
            if STATE.has_overheat_dtc():
                return with_searching(respond_obd([0x47, 0x01, 0x02, 0x17]))
            return with_searching("NO DATA")

        if mode == 0x09 and len(cmd) >= 4:
            out = handle_mode09(int(cmd[2:4], 16))
            body = out if out is not None else "NO DATA"
            return with_searching(body)

        if len(cmd) >= 4:
            out = handle_pid(mode, int(cmd[2:4], 16))
            body = out if out is not None else "NO DATA"
            return with_searching(body)

        return "NO DATA"
    except ValueError:
        return "?"


class ElmHandler(socketserver.StreamRequestHandler):
    def _send(self, data: bytes) -> None:
        self.wfile.write(data)
        self.wfile.flush()

    def handle(self) -> None:
        peer = self.client_address[0]
        print(f"client connected: {peer}", flush=True)
        # Fresh session state per connection (Car Scanner reconnects often)
        STATE.reset()
        buf = ""
        self._send(b"\r\n>")
        try:
            while True:
                data = self.rfile.read(1)
                if not data:
                    break
                ch = data.decode("latin-1", errors="ignore")
                if ch in ("\r", "\n"):
                    line = buf
                    buf = ""
                    if not line.strip():
                        self._send(b"\r>")
                        continue
                    if STATE.echo:
                        self._send((line + "\r").encode("latin-1"))
                    resp = process_command(line)
                    if resp:
                        # SEARCHING... already embeds \r before body
                        if STATE.linefeeds:
                            out = resp.replace("\r", "\r\n") + "\r\n"
                        else:
                            out = resp + "\r"
                        self._send(out.encode("latin-1"))
                    self._send(b">")
                else:
                    buf += ch
                    if len(buf) > 512:
                        buf = ""
        finally:
            print(f"client disconnected: {peer}", flush=True)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    print(
        f"ELM327 simulator PROFILE={STATE.profile} SCENARIO={STATE.scenario} "
        f"ignition=ON CAN/proto6 on {HOST}:{PORT}",
        flush=True,
    )
    if STATE.scenario == "overheat":
        print("Overheat: coolant climbs ~90→128°C over ~75s; DTC P0217 near the end", flush=True)
    with ThreadedTCPServer((HOST, PORT), ElmHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
