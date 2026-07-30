#!/usr/bin/env python3
"""Minimal ELM327-over-TCP ECU simulator for Car Scanner / OBD app visuals.

Profiles: generic | subaru | nissan — standard Mode 01 PIDs with animated temps.
No proprietary SSM/Consult streams.
"""

from __future__ import annotations

import math
import os
import socket
import socketserver
import threading
import time

HOST = os.environ.get("ELM_HOST", "0.0.0.0")
PORT = int(os.environ.get("ELM_TCP_PORT", "35000"))
PROFILE = os.environ.get("PROFILE", "generic").strip().lower()

# Profile: (coolant_base, oil_base, iat_base, ambient_base, cat_base_C)
PROFILES = {
    "generic": (90.0, 100.0, 30.0, 22.0, 450.0),
    "subaru": (93.0, 105.0, 28.0, 20.0, 470.0),
    "nissan": (88.0, 98.0, 32.0, 24.0, 440.0),
}


def temp_c_to_a(celsius: float) -> int:
    """OBD Mode 01 single-byte temp: A - 40 = °C."""
    return max(0, min(255, int(round(celsius + 40))))


def cat_temp_to_ab(celsius: float) -> tuple[int, int]:
    """PID 013C: ((A*256)+B)/10 - 40 = °C."""
    raw = int(round((celsius + 40) * 10))
    raw = max(0, min(65535, raw))
    return (raw >> 8) & 0xFF, raw & 0xFF


class EcuState:
    def __init__(self, profile: str) -> None:
        if profile not in PROFILES:
            raise SystemExit(f"Unknown PROFILE={profile!r}; use generic|subaru|nissan")
        self.profile = profile
        self.bases = PROFILES[profile]
        self.t0 = time.monotonic()
        self.echo = True
        self.headers = False
        self.spaces = True
        self.linefeeds = False
        self.protocol = "0"

    def anim(self, base: float, amp: float, period: float, phase: float = 0.0) -> float:
        t = time.monotonic() - self.t0
        return base + amp * math.sin(2 * math.pi * t / period + phase)

    def coolant(self) -> float:
        return self.anim(self.bases[0], 4.0, 45.0)

    def oil(self) -> float:
        return self.anim(self.bases[1], 5.0, 60.0, 0.5)

    def iat(self) -> float:
        return self.anim(self.bases[2], 6.0, 35.0, 1.0)

    def ambient(self) -> float:
        return self.anim(self.bases[3], 3.0, 80.0, 1.5)

    def catalyst(self) -> float:
        return self.anim(self.bases[4], 25.0, 50.0, 0.2)

    def rpm(self) -> int:
        return int(self.anim(1800, 400, 8.0))

    def speed(self) -> int:
        return max(0, int(self.anim(45, 20, 12.0)))


STATE = EcuState(PROFILE)


def format_payload(bytes_list: list[int]) -> str:
    if STATE.spaces:
        return " ".join(f"{b:02X}" for b in bytes_list)
    return "".join(f"{b:02X}" for b in bytes_list)


def respond_data(mode: int, pid: int, data: list[int]) -> str:
    # Response service = mode + 0x40
    payload = [mode + 0x40, pid] + data
    body = format_payload(payload)
    if STATE.headers:
        # Minimal fake header: 7E8
        body = f"7E8 {body}"
    return body


def handle_pid(mode: int, pid: int) -> str | None:
    if mode != 0x01:
        return None

    # Capability bitmaps — claim a useful set of PIDs including temps
    if pid == 0x00:
        # PIDs 01-20 supported bits (big-endian). Claim 04,05,0C,0D,0F,11,13C later via 0120
        return respond_data(mode, pid, [0xBE, 0x3E, 0xB8, 0x13])
    if pid == 0x20:
        # 21-40: claim 2F? keep simple — support 2F not needed; claim nothing critical
        return respond_data(mode, pid, [0x80, 0x00, 0x00, 0x01])  # + bit for 40
    if pid == 0x40:
        # 41-60: ambient 46, oil 5C
        return respond_data(mode, pid, [0x7A, 0x00, 0x00, 0x10])

    if pid == 0x05:  # coolant
        return respond_data(mode, pid, [temp_c_to_a(STATE.coolant())])
    if pid == 0x0F:  # IAT
        return respond_data(mode, pid, [temp_c_to_a(STATE.iat())])
    if pid == 0x46:  # ambient
        return respond_data(mode, pid, [temp_c_to_a(STATE.ambient())])
    if pid == 0x5C:  # oil
        return respond_data(mode, pid, [temp_c_to_a(STATE.oil())])
    if pid == 0x3C:  # catalyst B1S1
        a, b = cat_temp_to_ab(STATE.catalyst())
        return respond_data(mode, pid, [a, b])
    if pid == 0x3D:  # catalyst B1S2
        a, b = cat_temp_to_ab(STATE.catalyst() - 15)
        return respond_data(mode, pid, [a, b])
    if pid == 0x0C:  # RPM
        rpm = STATE.rpm()
        raw = rpm * 4
        return respond_data(mode, pid, [(raw >> 8) & 0xFF, raw & 0xFF])
    if pid == 0x0D:  # speed
        return respond_data(mode, pid, [STATE.speed() & 0xFF])
    if pid == 0x04:  # engine load
        return respond_data(mode, pid, [int(STATE.anim(100, 40, 7.0)) & 0xFF])
    if pid == 0x11:  # throttle
        return respond_data(mode, pid, [int(STATE.anim(80, 30, 6.0)) & 0xFF])

    return None


def handle_mode09(pid: int) -> str | None:
    if pid == 0x00:
        return respond_data(0x09, pid, [0x55, 0x00, 0x00, 0x00])  # VIN + calid-ish
    if pid == 0x02:  # VIN
        vin = f"SIM{PROFILE.upper()[:3]}OBD2BRIDGE00001"[:17].ljust(17)
        # Mode 09 VIN format simplified: 49 02 01 + ASCII
        data = [0x01] + [ord(c) for c in vin]
        return respond_data(0x09, pid, data)
    return None


def process_command(raw: str) -> str:
    cmd = raw.strip().upper().replace(" ", "")
    if not cmd:
        return ""

    # AT commands
    if cmd.startswith("AT"):
        at = cmd[2:]
        if at in ("Z", "WS"):
            return "ELM327 v1.5"
        if at == "I":
            return "ELM327 v1.5"
        if at.startswith("E") and len(at) == 2 and at[1] in "01":
            STATE.echo = at[1] == "1"
            return "OK"
        if at.startswith("H") and len(at) == 2 and at[1] in "01":
            STATE.headers = at[1] == "1"
            return "OK"
        if at.startswith("S") and len(at) == 2 and at[1] in "01":
            STATE.spaces = at[1] == "1"
            return "OK"
        if at.startswith("L") and len(at) == 2 and at[1] in "01":
            STATE.linefeeds = at[1] == "1"
            return "OK"
        if at.startswith("SP") and len(at) >= 3:
            STATE.protocol = at[2:]
            return "OK"
        if at == "DP":
            return "AUTO"
        if at == "DPN":
            return "A"
        if at in ("RV", "@1"):
            return "12.6V" if at == "RV" else "OBD-BRIDGE-SIM"
        if at == "DESC" or at == "@2":
            return f"obd-bridge sim ({STATE.profile})"
        # Accept most other AT as OK for app init
        return "OK"

    # OBD hex requests
    try:
        if len(cmd) >= 2 and all(c in "0123456789ABCDEF" for c in cmd):
            mode = int(cmd[0:2], 16)
            if mode == 0x03:
                return "NO DATA"
            if mode == 0x04:
                return "OK"
            if mode == 0x09 and len(cmd) >= 4:
                pid = int(cmd[2:4], 16)
                out = handle_mode09(pid)
                return out if out is not None else "NO DATA"
            if len(cmd) >= 4:
                pid = int(cmd[2:4], 16)
                out = handle_pid(mode, pid)
                return out if out is not None else "NO DATA"
            if mode == 0x01 and len(cmd) == 2:
                return "NO DATA"
    except ValueError:
        return "?"

    return "?"


class ElmHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        peer = self.client_address[0]
        print(f"client connected: {peer}", flush=True)
        buf = ""
        self.wfile.write(b"\r\n>")
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
                        self.wfile.write(b"\r>")
                        continue
                    if STATE.echo:
                        self.wfile.write((line + "\r").encode("latin-1"))
                    resp = process_command(line)
                    if resp:
                        ending = "\r\n" if STATE.linefeeds else "\r"
                        self.wfile.write((resp + ending).encode("latin-1"))
                    self.wfile.write(b">")
                else:
                    buf += ch
                    if len(buf) > 256:
                        buf = ""
        finally:
            print(f"client disconnected: {peer}", flush=True)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    print(f"ELM327 simulator PROFILE={STATE.profile} on {HOST}:{PORT}", flush=True)
    with ThreadedTCPServer((HOST, PORT), ElmHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
