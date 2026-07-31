#!/usr/bin/env python3
"""320x240 PiTFT UI — live temps (default) + status/pair page.

Adafruit PiTFT 2.8\" resistive. Prefers /dev/fb1 (legacy), then KMS/DRM
(Bookworm tinydrm / --install-type=drivers).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

STATUS_FILE = Path("/run/obd-bridge/status.env")
LIVE_FILE = Path("/run/obd-bridge/live.env")
DEVICE_ENV = Path("/etc/obd-bridge/device.env")
CONFIG_ENV = Path("/etc/obd-bridge/config.env")
W, H = 320, 240


def _pick_touch_device() -> None:
    for candidate in (
        "/dev/input/touchscreen",
        "/dev/input/event0",
        "/dev/input/event1",
        "/dev/input/event2",
    ):
        if Path(candidate).exists():
            os.environ.setdefault("SDL_MOUSEDEV", candidate)
            break
    os.environ.setdefault("SDL_NOMOUSE", "0")


def _try_set_mode(driver: str, env: dict[str, str]):
    """Initialize pygame with a video driver; return surface or raise."""
    import pygame

    for key in ("SDL_VIDEODRIVER", "SDL_FBDEV", "SDL_KMSDRM_DEVICE_INDEX"):
        os.environ.pop(key, None)
    os.environ["SDL_VIDEODRIVER"] = driver
    os.environ.update(env)
    _pick_touch_device()

    # Fresh init each attempt — leftover state breaks driver switches.
    try:
        pygame.quit()
    except Exception:
        pass
    pygame.init()
    screen = pygame.display.set_mode((W, H))
    return screen


def init_display():
    """Open the PiTFT; try framebuffer then KMS/DRM."""
    import pygame

    forced = os.environ.get("TFT_DRIVER", "").strip().lower()
    fb = os.environ.get("TFT_FB", "/dev/fb1")
    errors: list[str] = []

    attempts: list[tuple[str, dict[str, str]]] = []
    if forced == "kmsdrm" or forced == "kms":
        for idx in (
            os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "1"),
            "0",
            "1",
            "2",
        ):
            attempts.append(("kmsdrm", {"SDL_KMSDRM_DEVICE_INDEX": idx}))
    elif forced in ("fbcon", "fb", "framebuffer"):
        attempts.append(("fbcon", {"SDL_FBDEV": fb}))
    else:
        if Path(fb).exists():
            attempts.append(("fbcon", {"SDL_FBDEV": fb}))
        # Bookworm + Adafruit --install-type=drivers (tinydrm): SPI is often card1
        for idx in (
            os.environ.get("SDL_KMSDRM_DEVICE_INDEX", ""),
            "1",
            "0",
            "2",
        ):
            if not idx:
                continue
            attempts.append(("kmsdrm", {"SDL_KMSDRM_DEVICE_INDEX": idx}))

    # De-dupe while preserving order
    seen: set[tuple[str, tuple[tuple[str, str], ...]]] = set()
    unique: list[tuple[str, dict[str, str]]] = []
    for driver, env in attempts:
        key = (driver, tuple(sorted(env.items())))
        if key in seen:
            continue
        seen.add(key)
        unique.append((driver, env))

    for driver, env in unique:
        try:
            screen = _try_set_mode(driver, env)
            print(
                f"pitft_ui: display ok driver={driver} env={env} size={screen.get_size()}",
                flush=True,
            )
            return pygame, screen
        except Exception as exc:  # noqa: BLE001 — try next backend
            errors.append(f"{driver} {env}: {exc}")
            try:
                pygame.quit()
            except Exception:
                pass

    msg = "pitft_ui: no usable display\n" + "\n".join(errors)
    print(msg, file=sys.stderr, flush=True)
    raise SystemExit(1)


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
    live = load_env_file(LIVE_FILE)
    out = {
        "SSID": cfg.get("AP_SSID", st.get("SSID", "obd-bridge")),
        "AP_PASS": cfg.get("AP_PASS", st.get("AP_PASS", "")),
        "AP_IP": cfg.get("AP_IP", st.get("AP_IP", "192.168.4.1")),
        "PORT": cfg.get("ELM_TCP_PORT", st.get("ELM_TCP_PORT", "35000")),
        "BT_MAC": dev.get("BT_MAC", st.get("BT_MAC", "")),
        "PHASE": st.get("PHASE", "unknown"),
        "DETAIL": live.get("DETAIL", st.get("DETAIL", "")),
        "COOLANT_C": live.get("COOLANT_C", ""),
        "OIL_C": live.get("OIL_C", ""),
        "IAT_C": live.get("IAT_C", ""),
        "AMBIENT_C": live.get("AMBIENT_C", ""),
        "RPM": live.get("RPM", ""),
        "LIVE_OK": live.get("OK", "0"),
    }
    out["RFCOMM"] = "up" if Path(cfg.get("RFCOMM_DEV", "/dev/rfcomm0")).exists() else "down"
    return out


def trigger_pair() -> None:
    if DEVICE_ENV.is_file():
        DEVICE_ENV.write_text("# cleared by TFT UI for re-pair\n", encoding="utf-8")
    subprocess.run(["systemctl", "restart", "obd-bridge-autopair.service"], check=False)


def temp_color(celsius: str, hot_at: int = 105) -> tuple[int, int, int]:
    if not celsius:
        return (120, 120, 120)
    try:
        v = int(celsius)
    except ValueError:
        return (120, 120, 120)
    if v >= hot_at:
        return (220, 60, 50)
    if v >= hot_at - 10:
        return (220, 150, 40)
    return (80, 200, 120)


def draw_temps(screen, font_lg, font, info: dict[str, str]) -> None:
    rows = [
        ("Coolant", info.get("COOLANT_C", ""), "C", 105),
        ("Oil", info.get("OIL_C", ""), "C", 120),
        ("IAT", info.get("IAT_C", ""), "C", 60),
        ("Ambient", info.get("AMBIENT_C", ""), "C", 45),
        ("RPM", info.get("RPM", ""), "", 0),
    ]
    y = 36
    for label, val, unit, hot in rows:
        color = temp_color(val, hot) if unit == "C" else (220, 220, 220)
        display = f"{val}°{unit}" if unit and val else (val or "--")
        screen.blit(font.render(label, True, (180, 180, 180)), (16, y + 6))
        screen.blit(font_lg.render(display, True, color), (130, y))
        y += 28

    detail = info.get("DETAIL", "")[:36]
    if detail:
        screen.blit(font.render(detail, True, (160, 160, 160)), (16, 168))


def draw_status(screen, font, font_sm, info: dict[str, str]) -> None:
    lines = [
        f"WiFi: {info['SSID']}",
        f"Pass: {info['AP_PASS']}",
        f"ELM:  {info['AP_IP']}:{info['PORT']}",
        f"BT:   {info['BT_MAC'] or '(not paired)'}",
        f"Link: rfcomm={info['RFCOMM']}",
        info.get("DETAIL", "")[:40],
    ]
    y = 40
    for line in lines:
        screen.blit(font.render(line, True, (220, 220, 220)), (12, y))
        y += 22


def main() -> None:
    pygame, screen = init_display()
    pygame.mouse.set_visible(True)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("dejavusans", 16)
    font_sm = pygame.font.SysFont("dejavusans", 13)
    font_lg = pygame.font.SysFont("dejavusans", 26, bold=True)
    font_title = pygame.font.SysFont("dejavusans", 18, bold=True)

    mode = "temps"  # or status
    btn_left = pygame.Rect(12, 192, 96, 40)
    btn_mid = pygame.Rect(116, 192, 96, 40)
    btn_right = pygame.Rect(220, 192, 88, 40)
    last_refresh = 0.0
    info = gather()

    running = True
    while running:
        now = time.time()
        if now - last_refresh > 0.5:
            info = gather()
            last_refresh = now

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if btn_left.collidepoint(event.pos):
                    mode = "temps" if mode == "status" else "status"
                elif btn_mid.collidepoint(event.pos):
                    trigger_pair()
                    info["PHASE"] = "scanning"
                    info["DETAIL"] = "Pair requested…"
                elif btn_right.collidepoint(event.pos):
                    subprocess.run(
                        [
                            "systemctl",
                            "restart",
                            "obd-bridge-rfcomm",
                            "obd-bridge-live",
                        ],
                        check=False,
                    )
                    info["DETAIL"] = "Services restarted"

        screen.fill((20, 22, 28))
        title = "Temps" if mode == "temps" else "Status"
        screen.blit(font_title.render(f"OBD · {title}", True, (240, 240, 240)), (12, 6))

        live_ok = info.get("LIVE_OK") == "1"
        badge = (40, 160, 70) if live_ok else (200, 140, 20)
        pygame.draw.rect(screen, badge, pygame.Rect(230, 6, 78, 22), border_radius=4)
        screen.blit(font_sm.render("LIVE" if live_ok else "WAIT", True, (255, 255, 255)), (246, 9))

        if mode == "temps":
            draw_temps(screen, font_lg, font, info)
        else:
            draw_status(screen, font, font_sm, info)

        pygame.draw.rect(screen, (60, 90, 140), btn_left, border_radius=6)
        screen.blit(font_sm.render("Temps/Stat", True, (255, 255, 255)), (18, 204))
        pygame.draw.rect(screen, (50, 110, 200), btn_mid, border_radius=6)
        screen.blit(font_sm.render("Pair", True, (255, 255, 255)), (148, 204))
        pygame.draw.rect(screen, (80, 80, 90), btn_right, border_radius=6)
        screen.blit(font_sm.render("Restart", True, (255, 255, 255)), (234, 204))

        pygame.display.flip()
        clock.tick(15)

    pygame.quit()


if __name__ == "__main__":
    main()
