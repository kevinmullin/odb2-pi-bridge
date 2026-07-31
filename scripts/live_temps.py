#!/usr/bin/env python3
"""Own /dev/rfcomm0: poll live temps for the PiTFT and serve TCP :35000.

Writes /run/obd-bridge/live.env for the TFT UI. Serial access is mutex-locked so
phone apps on :35000 can still work without garbling the bus.
"""

from __future__ import annotations

import os
import re
import socketserver
import threading
import time
from pathlib import Path

try:
    import serial
except ImportError as exc:  # pragma: no cover
    raise SystemExit("python3-serial required (apt install python3-serial)") from exc

RFCOMM = os.environ.get("RFCOMM_DEV", "/dev/rfcomm0")
BAUD = int(os.environ.get("BT_BAUD", "115200"))
PORT = int(os.environ.get("ELM_TCP_PORT", "35000"))
POLL_SECONDS = float(os.environ.get("LIVE_POLL_SECONDS", "1.0"))
RUN_DIR = Path(os.environ.get("STATUS_DIR", "/run/obd-bridge"))
LIVE_FILE = RUN_DIR / "live.env"
ENABLE_TCP = os.environ.get("LIVE_ENABLE_TCP", "1") == "1"

LOCK = threading.RLock()
STATE: dict[str, str] = {
    "coolant_c": "",
    "oil_c": "",
    "iat_c": "",
    "ambient_c": "",
    "rpm": "",
    "ok": "0",
    "detail": "starting",
    "updated": "",
}


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), msg, flush=True)


def wait_for_device(path: str) -> None:
    log(f"Waiting for {path}…")
    while not Path(path).exists():
        STATE["detail"] = "waiting for rfcomm"
        write_live()
        time.sleep(1)


def open_serial() -> "serial.Serial":
    return serial.Serial(RFCOMM, BAUD, timeout=1.5, write_timeout=1.5)


def elm_exchange(ser: "serial.Serial", cmd: str, settle: float = 0.05) -> str:
    while ser.in_waiting:
        ser.read(ser.in_waiting)
    ser.write((cmd.strip() + "\r").encode("ascii"))
    ser.flush()
    time.sleep(settle)
    buf = bytearray()
    deadline = time.time() + 2.5
    while time.time() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf.extend(chunk)
            if b">" in chunk:
                break
        elif buf:
            break
    text = buf.decode("latin-1", errors="replace")
    text = text.replace(cmd.strip(), "")
    text = text.replace(">", " ").replace("\r", " ").replace("\n", " ")
    return " ".join(text.split())


def parse_temp(resp: str, pid: str) -> str:
    m = re.search(rf"41\s*{pid}\s*([0-9A-Fa-f]{{2}})", resp, flags=re.I)
    if not m:
        return ""
    return str(int(m.group(1), 16) - 40)


def parse_rpm(resp: str) -> str:
    m = re.search(r"41\s*0C\s*([0-9A-Fa-f]{2})\s*([0-9A-Fa-f]{2})", resp, flags=re.I)
    if not m:
        return ""
    raw = (int(m.group(1), 16) << 8) + int(m.group(2), 16)
    return str(raw // 4)


def write_live() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    STATE["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LIVE_FILE.write_text(
        "\n".join(f"{k.upper()}={v}" for k, v in STATE.items()) + "\n",
        encoding="utf-8",
    )


def init_elm(ser: "serial.Serial") -> None:
    with LOCK:
        for cmd in ("ATZ", "ATE0", "ATL0", "ATS0", "ATH0", "ATSP0"):
            elm_exchange(ser, cmd, settle=0.2 if cmd == "ATZ" else 0.05)
        elm_exchange(ser, "0100", settle=0.25)


def poll_once(ser: "serial.Serial") -> None:
    with LOCK:
        c = elm_exchange(ser, "0105")
        STATE["coolant_c"] = parse_temp(c, "05") or STATE["coolant_c"]
        o = elm_exchange(ser, "015C")
        STATE["oil_c"] = parse_temp(o, "5C") or STATE["oil_c"]
        i = elm_exchange(ser, "010F")
        STATE["iat_c"] = parse_temp(i, "0F") or STATE["iat_c"]
        a = elm_exchange(ser, "0146")
        STATE["ambient_c"] = parse_temp(a, "46") or STATE["ambient_c"]
        r = elm_exchange(ser, "010C")
        STATE["rpm"] = parse_rpm(r) or STATE["rpm"]
        if STATE["coolant_c"]:
            STATE["ok"] = "1"
            STATE["detail"] = "live"
        else:
            STATE["ok"] = "0"
            STATE["detail"] = "waiting for ECU data"


class ElmTCPHandler(socketserver.StreamRequestHandler):
    ser: "serial.Serial"

    def handle(self) -> None:
        self.wfile.write(b"\r\n>")
        self.wfile.flush()
        buf = ""
        while True:
            data = self.rfile.read(1)
            if not data:
                break
            ch = data.decode("latin-1", errors="ignore")
            if ch in ("\r", "\n"):
                line = buf.strip()
                buf = ""
                if not line:
                    self.wfile.write(b"\r>")
                    self.wfile.flush()
                    continue
                with LOCK:
                    try:
                        resp = elm_exchange(self.ser, line)
                    except (OSError, serial.SerialException) as exc:
                        resp = str(exc)
                self.wfile.write((resp + "\r>").encode("latin-1", errors="replace"))
                self.wfile.flush()
            else:
                buf += ch
                if len(buf) > 256:
                    buf = ""


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def tcp_server_thread(ser: "serial.Serial") -> None:
    ElmTCPHandler.ser = ser
    with ThreadedTCPServer(("0.0.0.0", PORT), ElmTCPHandler) as srv:
        log(f"ELM TCP on :{PORT}")
        srv.serve_forever()


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    write_live()
    wait_for_device(RFCOMM)

    while True:
        try:
            ser = open_serial()
            log(f"Opened {RFCOMM}")
            init_elm(ser)
            STATE["detail"] = "initialized"
            write_live()

            if ENABLE_TCP:
                threading.Thread(target=tcp_server_thread, args=(ser,), daemon=True).start()

            while True:
                poll_once(ser)
                write_live()
                time.sleep(POLL_SECONDS)
        except (OSError, serial.SerialException) as exc:
            STATE["ok"] = "0"
            STATE["detail"] = f"reconnect: {exc}"
            write_live()
            log(f"Serial lost ({exc}); retrying…")
            time.sleep(2)
            wait_for_device(RFCOMM)


if __name__ == "__main__":
    main()
