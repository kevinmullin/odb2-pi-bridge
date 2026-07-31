#!/usr/bin/env python3
"""320x240 status UI for Adafruit PiTFT 2.8\" resistive (fb1).

Shows AP credentials, pair/proxy state, and a Pair / Re-pair touch button.
Requires: python3-pygame, PiTFT installed (Adafruit --display=28r).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

# PiTFT framebuffer + resistive touch (common Adafruit paths)
os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
os.environ.setdefault("SDL_FBDEV", os.environ.get("TFT_FB", "/dev/fb1"))
os.environ.setdefault("SDL_NOMOUSE", "0")
# Prefer tslib touch node if present
for candidate in (
    "/dev/input/touchscreen",
    "/dev/input/event0",
    "/dev/input/event1",
    "/dev/input/event2",
):
    if Path(candidate).exists():
        os.environ.setdefault("SDL_MOUSEDEV", candidate)
        break

import pygame  # noqa: E402

STATUS_FILE = Path("/run/obd-bridge/status.env")
DEVICE_ENV = Path("/etc/obd-bridge/device.env")
CONFIG_ENV = Path("/etc/obd-bridge/config.env")
W, H = 320, 240


def load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip("'\"")
    return data


def gather() -> dict[str, str]:
    cfg = load_env_file(CONFIG_ENV)
    dev = load_env_file(DEVICE_ENV)
    st = load_env_file(STATUS_FILE)
    out = {
        "SSID": cfg.get("AP_SSID", st.get("SSID", "obd-bridge")),
        "AP_PASS": cfg.get("AP_PASS", st.get("AP_PASS", "")),
        "AP_IP": cfg.get("AP_IP", st.get("AP_IP", "192.168.4.1")),
        "PORT": cfg.get("ELM_TCP_PORT", st.get("ELM_TCP_PORT", "35000")),
        "BT_MAC": dev.get("BT_MAC", st.get("BT_MAC", "")),
        "PHASE": st.get("PHASE", "unknown"),
        "DETAIL": st.get("DETAIL", ""),
    }
    # Live service checks
    out["RFCOMM"] = "up" if Path(cfg.get("RFCOMM_DEV", "/dev/rfcomm0")).exists() else "down"
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "obd-bridge-proxy"],
            capture_output=True,
            text=True,
            check=False,
        )
        out["PROXY"] = r.stdout.strip() or "unknown"
    except OSError:
        out["PROXY"] = "?"
    return out


def trigger_pair() -> None:
    """Forget saved MAC and kick autopair + pair script."""
    if DEVICE_ENV.is_file():
        # Clear MAC so autopair runs again
        DEVICE_ENV.write_text("# cleared by TFT UI for re-pair\n", encoding="utf-8")
    subprocess.run(["systemctl", "restart", "obd-bridge-autopair.service"], check=False)
    subprocess.Popen(
        ["/usr/local/lib/obd-bridge/pair-bafx.sh"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def phase_color(phase: str) -> tuple[int, int, int]:
    p = phase.lower()
    if p in ("paired", "ready"):
        return (40, 160, 70)
    if p in ("waiting", "scanning", "retry"):
        return (200, 140, 20)
    return (180, 60, 50)


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    pygame.mouse.set_visible(True)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("dejavusans", 16)
    font_sm = pygame.font.SysFont("dejavusans", 13)
    font_lg = pygame.font.SysFont("dejavusans", 18, bold=True)

    btn = pygame.Rect(20, 190, 130, 40)
    btn2 = pygame.Rect(170, 190, 130, 40)
    last_refresh = 0.0
    info = gather()

    running = True
    while running:
        now = time.time()
        if now - last_refresh > 1.0:
            info = gather()
            last_refresh = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if btn.collidepoint(event.pos):
                    trigger_pair()
                    info["PHASE"] = "scanning"
                    info["DETAIL"] = "Pair requested…"
                elif btn2.collidepoint(event.pos):
                    subprocess.run(
                        ["systemctl", "restart", "obd-bridge-rfcomm", "obd-bridge-proxy"],
                        check=False,
                    )
                    info["DETAIL"] = "Services restarted"

        screen.fill((20, 22, 28))
        title = font_lg.render("OBD Bridge", True, (240, 240, 240))
        screen.blit(title, (12, 8))

        phase = info.get("PHASE", "?")
        pygame.draw.rect(screen, phase_color(phase), pygame.Rect(200, 8, 108, 24), border_radius=4)
        screen.blit(font_sm.render(phase[:12], True, (255, 255, 255)), (208, 12))

        lines = [
            f"WiFi: {info['SSID']}",
            f"Pass: {info['AP_PASS']}",
            f"ELM:  {info['AP_IP']}:{info['PORT']}",
            f"BT:   {info['BT_MAC'] or '(not paired)'}",
            f"Link: rfcomm={info['RFCOMM']}  proxy={info['PROXY']}",
            info.get("DETAIL", "")[:40],
        ]
        y = 40
        for line in lines:
            screen.blit(font.render(line, True, (220, 220, 220)), (12, y))
            y += 22

        pygame.draw.rect(screen, (50, 110, 200), btn, border_radius=6)
        screen.blit(font.render("Pair / Re-pair", True, (255, 255, 255)), (28, 200))
        pygame.draw.rect(screen, (80, 80, 90), btn2, border_radius=6)
        screen.blit(font.render("Restart", True, (255, 255, 255)), (198, 200))

        pygame.display.flip()
        clock.tick(15)

    pygame.quit()


if __name__ == "__main__":
    main()
