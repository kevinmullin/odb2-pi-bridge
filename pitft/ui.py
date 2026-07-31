#!/usr/bin/env python3
"""320x240 PiTFT UI — live temps (default) + status/pair page.

Adafruit PiTFT 2.8\" resistive.

Bookworm SDL2 has no fbcon. Order of backends:
  1. KMS/DRM (overlay must include ,drm — SPI shows up under /sys/class/drm)
  2. Direct RGB565 blit to /dev/fb1 (works with legacy fbtft, no ,drm)
"""

from __future__ import annotations

import array
import mmap
import os
import select
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

STATUS_FILE = Path("/run/obd-bridge/status.env")
LIVE_FILE = Path("/run/obd-bridge/live.env")
DEVICE_ENV = Path("/etc/obd-bridge/device.env")
CONFIG_ENV = Path("/etc/obd-bridge/config.env")
W, H = 320, 240


@dataclass
class Display:
    pygame: Any
    screen: Any
    flip: Callable[[], None]
    poll_clicks: Callable[[], list[tuple[int, int]]]
    close: Callable[[], None]
    backend: str


def _pick_touch_path() -> str | None:
    for candidate in (
        "/dev/input/touchscreen",
        "/dev/input/event0",
        "/dev/input/event1",
        "/dev/input/event2",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _pick_touch_device() -> None:
    path = _pick_touch_path()
    if path:
        os.environ.setdefault("SDL_MOUSEDEV", path)
    os.environ.setdefault("SDL_NOMOUSE", "0")


def _try_kmsdrm(pygame, idx: str):
    for key in ("SDL_VIDEODRIVER", "SDL_FBDEV", "SDL_KMSDRM_DEVICE_INDEX"):
        os.environ.pop(key, None)
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_KMSDRM_DEVICE_INDEX"] = idx
    _pick_touch_device()
    try:
        pygame.quit()
    except Exception:
        pass
    pygame.init()
    screen = pygame.display.set_mode((W, H))

    def flip() -> None:
        pygame.display.flip()

    def poll_clicks() -> list[tuple[int, int]]:
        clicks: list[tuple[int, int]] = []
        for event in pygame.event.get():
            if event.type == pygame.MOUSEBUTTONDOWN:
                clicks.append(event.pos)
            elif event.type == pygame.QUIT:
                raise SystemExit(0)
        return clicks

    def close() -> None:
        pygame.quit()

    return Display(pygame, screen, flip, poll_clicks, close, f"kmsdrm:{idx}")


def _rgb888_to_rgb565(rgb: bytes) -> bytes:
    out = array.array("H")
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        out.append(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))
    return out.tobytes()


class _RawTouch:
    """Minimal ABS touch reader (no python3-evdev required)."""

    EV_SYN = 0x00
    EV_KEY = 0x01
    EV_ABS = 0x03
    ABS_X = 0x00
    ABS_Y = 0x01
    BTN_TOUCH = 0x14A

    def __init__(self, path: str) -> None:
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        # input_event is 24 bytes on 64-bit, 16 on 32-bit
        self.fmt = "llHHi"
        self.size = struct.calcsize(self.fmt)
        if self.size not in (16, 24):
            self.fmt = "QQHHi"
            self.size = struct.calcsize(self.fmt)
        self.x = 0
        self.y = 0
        self.x_min, self.x_max = 0, 4095
        self.y_min, self.y_max = 0, 4095
        self._pressed = False

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass

    def _scale(self, val: int, lo: int, hi: int, out: int) -> int:
        if hi <= lo:
            return 0
        v = max(lo, min(hi, val))
        return int((v - lo) * (out - 1) / (hi - lo))

    def poll(self) -> list[tuple[int, int]]:
        clicks: list[tuple[int, int]] = []
        while True:
            try:
                ready, _, _ = select.select([self.fd], [], [], 0)
            except (ValueError, OSError):
                break
            if not ready:
                break
            try:
                data = os.read(self.fd, self.size)
            except BlockingIOError:
                break
            if len(data) < self.size:
                break
            _s, _us, etype, code, value = struct.unpack(self.fmt, data)
            if etype == self.EV_ABS:
                if code == self.ABS_X:
                    self.x = value
                elif code == self.ABS_Y:
                    self.y = value
            elif etype == self.EV_KEY and code == self.BTN_TOUCH:
                if value == 1:
                    self._pressed = True
                elif value == 0 and self._pressed:
                    self._pressed = False
                    sx = self._scale(self.x, self.x_min, self.x_max, W)
                    sy = self._scale(self.y, self.y_min, self.y_max, H)
                    clicks.append((sx, sy))
            elif etype == self.EV_SYN and self._pressed:
                # some drivers only send ABS without BTN_TOUCH edges every frame;
                # ignore continuous move — require BTN_TOUCH release for a click
                pass
        return clicks


def _try_fb1_direct(pygame, fb_path: str) -> Display:
    fb = Path(fb_path)
    if not fb.exists():
        raise FileNotFoundError(fb)

    sysfb = Path("/sys/class/graphics") / fb.name
    bpp = 16
    if (sysfb / "bits_per_pixel").is_file():
        bpp = int((sysfb / "bits_per_pixel").read_text().strip())
    if bpp not in (16, 32):
        raise RuntimeError(f"unsupported fb bpp={bpp}")

    vs = "320,240"
    if (sysfb / "virtual_size").is_file():
        vs = (sysfb / "virtual_size").read_text().strip()
    width, height = (int(x) for x in vs.split(",")[:2])
    stride = width * (bpp // 8)
    if (sysfb / "stride").is_file():
        stride = int((sysfb / "stride").read_text().strip())

    for key in ("SDL_VIDEODRIVER", "SDL_FBDEV", "SDL_KMSDRM_DEVICE_INDEX"):
        os.environ.pop(key, None)
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    try:
        pygame.quit()
    except Exception:
        pass
    pygame.init()
    pygame.display.set_mode((1, 1))
    screen = pygame.Surface((W, H))

    fb_file = open(fb, "r+b", buffering=0)
    map_size = max(stride * height, width * height * (bpp // 8))
    fb_map = mmap.mmap(fb_file.fileno(), map_size, mmap.MAP_SHARED, mmap.PROT_WRITE | mmap.PROT_READ)

    touch_path = _pick_touch_path()
    touch = _RawTouch(touch_path) if touch_path else None

    def flip() -> None:
        if (width, height) != (W, H):
            scaled = pygame.transform.smoothscale(screen, (width, height))
        else:
            scaled = screen
        if bpp == 16:
            blob = _rgb888_to_rgb565(pygame.image.tobytes(scaled, "RGB"))
        else:
            blob = pygame.image.tobytes(scaled, "RGBX")
        # Handle stride padding (row may be longer than width*bpp/8)
        row_bytes = width * (bpp // 8)
        if stride == row_bytes:
            fb_map.seek(0)
            fb_map.write(blob[:map_size])
        else:
            fb_map.seek(0)
            for y in range(height):
                start = y * row_bytes
                fb_map.write(blob[start : start + row_bytes])
                if stride > row_bytes:
                    fb_map.write(b"\x00" * (stride - row_bytes))

    def poll_clicks() -> list[tuple[int, int]]:
        # Drain dummy pygame events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                raise SystemExit(0)
        if touch is None:
            return []
        return touch.poll()

    def close() -> None:
        if touch is not None:
            touch.close()
        try:
            fb_map.close()
        except Exception:
            pass
        try:
            fb_file.close()
        except Exception:
            pass
        pygame.quit()

    return Display(pygame, screen, flip, poll_clicks, close, f"fb1-direct:{fb}")


def init_display() -> Display:
    import pygame

    forced = os.environ.get("TFT_DRIVER", "").strip().lower()
    fb = os.environ.get("TFT_FB", "/dev/fb1")
    errors: list[str] = []

    # Prefer KMS when SPI DRM exists; otherwise fb1-direct (Bookworm reality).
    kms_idxs: list[str] = []
    if forced in ("kmsdrm", "kms"):
        kms_idxs = [
            os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "1"),
            "0",
            "1",
            "2",
        ]
    elif forced in ("fb", "fb1", "framebuffer", "direct"):
        kms_idxs = []
    else:
        # Only probe KMS indexes that exist as /dev/dri/cardN
        for idx in ("1", "0", "2"):
            if Path(f"/dev/dri/card{idx}").exists():
                kms_idxs.append(idx)
        env_idx = os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "")
        if env_idx and env_idx not in kms_idxs:
            kms_idxs.insert(0, env_idx)

    seen: set[str] = set()
    for idx in kms_idxs:
        if idx in seen:
            continue
        seen.add(idx)
        try:
            disp = _try_kmsdrm(pygame, idx)
            print(f"pitft_ui: display ok backend={disp.backend}", flush=True)
            return disp
        except Exception as exc:  # noqa: BLE001
            errors.append(f"kmsdrm index={idx}: {exc}")
            try:
                pygame.quit()
            except Exception:
                pass

    if forced not in ("kmsdrm", "kms") and Path(fb).exists():
        try:
            disp = _try_fb1_direct(pygame, fb)
            print(f"pitft_ui: display ok backend={disp.backend}", flush=True)
            return disp
        except Exception as exc:  # noqa: BLE001
            errors.append(f"fb1-direct {fb}: {exc}")
            try:
                pygame.quit()
            except Exception:
                pass

    msg = "pitft_ui: no usable display\n" + "\n".join(errors)
    print(msg, file=sys.stderr, flush=True)
    print(
        "hint: legacy overlay needs dtoverlay=...,drm for kmsdrm, "
        "or /dev/fb1 for direct blit; install libegl1 libgbm1 for HDMI/SPI DRM",
        file=sys.stderr,
        flush=True,
    )
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
    disp = init_display()
    pygame = disp.pygame
    screen = disp.screen
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
    try:
        while running:
            now = time.time()
            if now - last_refresh > 0.5:
                info = gather()
                last_refresh = now

            try:
                clicks = disp.poll_clicks()
            except SystemExit:
                running = False
                break

            for pos in clicks:
                if btn_left.collidepoint(pos):
                    mode = "temps" if mode == "status" else "status"
                elif btn_mid.collidepoint(pos):
                    trigger_pair()
                    info["PHASE"] = "scanning"
                    info["DETAIL"] = "Pair requested…"
                elif btn_right.collidepoint(pos):
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
            screen.blit(
                font_sm.render("LIVE" if live_ok else "WAIT", True, (255, 255, 255)),
                (246, 9),
            )

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

            disp.flip()
            clock.tick(15)
    finally:
        disp.close()


if __name__ == "__main__":
    main()
