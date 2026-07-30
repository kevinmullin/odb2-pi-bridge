#!/usr/bin/env python3
"""Reliable ELM simulator smoke test (macOS nc is flaky with pipes)."""

from __future__ import annotations

import argparse
import socket
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=35000)
    p.add_argument("command", nargs="?", default="ATZ")
    args = p.parse_args()

    cmd = args.command.strip().upper()
    if not cmd.endswith("\r"):
        payload = (cmd + "\r").encode("ascii")
    else:
        payload = cmd.encode("ascii")

    with socket.create_connection((args.host, args.port), timeout=5) as sock:
        sock.settimeout(3)
        banner = sock.recv(64)
        sys.stdout.write(f"banner: {banner!r}\n")
        sock.sendall(payload)
        time.sleep(0.2)
        reply = sock.recv(512)
        sys.stdout.write(f"sent:   {payload!r}\n")
        sys.stdout.write(f"reply:  {reply!r}\n")
        text = reply.decode("latin-1", errors="replace")
        sys.stdout.write(f"text:\n{text.replace(chr(13), chr(10))}\n")

        ok = b"ELM327" in reply or b"41" in reply or b"OK" in reply or b"NO DATA" in reply
        if cmd == "ATZ" and b"ELM327" not in reply:
            sys.stderr.write("FAIL: expected ELM327 in ATZ reply\n")
            return 1
        if not ok and cmd.startswith("01"):
            sys.stderr.write("FAIL: unexpected PID reply\n")
            return 1
        sys.stdout.write("OK\n")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
