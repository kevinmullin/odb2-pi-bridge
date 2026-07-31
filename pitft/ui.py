#!/usr/bin/env python3
"""320x240 PiTFT UI — live temps + autopair activity stream.

Adafruit PiTFT 2.8\" resistive. No touch buttons — pair runs via systemd
autopair; reboot by power-cycling. Activity comes from /run/obd-bridge/events.log.

Bookworm SDL2 has no fbcon. Order of backends:
  1. KMS/DRM (overlay must include ,drm)
  2. Direct RGB565 blit (fb0 without HDMI, fb1 with HDMI)
"""

from __future__ import annotations

import array
import mmap
import os
import select
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

STATUS_FILE = Path("/run/obd-bridge/status.env")
LIVE_FILE = Path("/run/obd-bridge/live.env")
EVENTS_FILE = Path("/run/obd-bridge/events.log")
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


_PITFT_NAME_HINTS = (
    "ili934",
    "st7789",
    "hx8357",
    "fbtft",
    "pitft",
    "fb_ili",
    "fb_st",
    "mi0283",
    "sainsmart",
)
_HDMI_NAME_HINTS = ("vc4", "bcm2708", "bcm2835", "drmfb", "simplefb", "virtio")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _unbind_fb_console() -> None:
    """Stop kernel text console from fighting us on the PiTFT."""
    vt_root = Path("/sys/class/vtconsole")
    if not vt_root.is_dir():
        return
    for bind in sorted(vt_root.glob("vtcon*/bind")):
        name = _read_text(bind.parent / "name").lower()
        # Typical: "frame buffer device" — leave pure VGA/dummy alone if named oddly
        if "frame buffer" in name or "framebuffer" in name or "fbcon" in name:
            try:
                bind.write_text("0\n", encoding="utf-8")
                print(f"pitft_ui: unbound console {bind.parent.name} ({name})", flush=True)
            except OSError as exc:
                print(f"pitft_ui: could not unbind {bind}: {exc}", flush=True)


def detect_pitft_framebuffer() -> str | None:
    """Pick the SPI PiTFT node. With HDMI it is often fb1; without HDMI, fb0."""
    forced = os.environ.get("TFT_FB", "").strip()
    if forced:
        return forced if Path(forced).exists() else None

    graphics = Path("/sys/class/graphics")
    if not graphics.is_dir():
        for fallback in ("/dev/fb1", "/dev/fb0"):
            if Path(fallback).exists():
                return fallback
        return None

    scored: list[tuple[int, str, str, int, int]] = []
    for sysfb in sorted(graphics.glob("fb[0-9]*")):
        dev = Path("/dev") / sysfb.name
        if not dev.exists():
            continue
        name = _read_text(sysfb / "name").lower()
        vs = _read_text(sysfb / "virtual_size") or "0,0"
        try:
            width, height = (int(x) for x in vs.split(",")[:2])
        except ValueError:
            width, height = 0, 0

        score = 0
        if any(h in name for h in _PITFT_NAME_HINTS):
            score += 100
        if (width, height) in ((W, H), (H, W)):
            score += 50
        # Small SPI panels are never full HD
        if 0 < width <= 480 and 0 < height <= 320:
            score += 20
        if any(h in name for h in _HDMI_NAME_HINTS):
            score -= 80
        if width >= 640 or height >= 480:
            score -= 40
        scored.append((score, str(dev), name or "?", width, height))

    if not scored:
        return None

    scored.sort(key=lambda row: (-row[0], row[1]))
    for score, dev, name, width, height in scored:
        print(
            f"pitft_ui: fb candidate {dev} name={name!r} {width}x{height} score={score}",
            flush=True,
        )
    best_score, best_dev, best_name, best_w, best_h = scored[0]
    if best_score <= 0 and len(scored) > 1:
        # Ambiguous — prefer non-HDMI sized panel if any score > HDMI
        return None
    print(
        f"pitft_ui: selected {best_dev} ({best_name} {best_w}x{best_h})",
        flush=True,
    )
    return best_dev


def _try_fb_direct(pygame, fb_path: str) -> Display:
    fb = Path(fb_path)
    if not fb.exists():
        raise FileNotFoundError(fb)

    _unbind_fb_console()

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

    return Display(pygame, screen, flip, poll_clicks, close, f"fb-direct:{fb}")


def init_display() -> Display:
    import pygame

    forced = os.environ.get("TFT_DRIVER", "").strip().lower()
    errors: list[str] = []

    # Prefer KMS when SPI DRM exists; otherwise direct framebuffer blit.
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
        # Prefer non-zero cards first (SPI often card1 when HDMI is card0)
        for idx in ("1", "2", "0"):
            if Path(f"/dev/dri/card{idx}").exists():
                kms_idxs.append(idx)
        env_idx = os.environ.get("SDL_KMSDRM_DEVICE_INDEX", "")
        if env_idx and env_idx not in kms_idxs:
            kms_idxs.insert(0, env_idx)

    # With only HDMI DRM and no SPI drm node, kmsdrm draws on HDMI — skip unless forced.
    spi_drm = any(Path(p).is_dir() and "SPI" in Path(p).name for p in Path("/sys/class/drm").glob("card*-*"))
    if forced not in ("kmsdrm", "kms") and not spi_drm:
        kms_idxs = []

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

    if forced not in ("kmsdrm", "kms"):
        fb = detect_pitft_framebuffer()
        if fb:
            try:
                disp = _try_fb_direct(pygame, fb)
                print(f"pitft_ui: display ok backend={disp.backend}", flush=True)
                return disp
            except Exception as exc:  # noqa: BLE001
                errors.append(f"fb-direct {fb}: {exc}")
                try:
                    pygame.quit()
                except Exception:
                    pass
        else:
            errors.append("no PiTFT framebuffer detected (set TFT_FB=/dev/fbN)")

    msg = "pitft_ui: no usable display\n" + "\n".join(errors)
    print(msg, file=sys.stderr, flush=True)
    print(
        "hint: without HDMI the PiTFT is often /dev/fb0; with HDMI usually /dev/fb1. "
        "Override with TFT_FB=…; optional dtoverlay=…,drm for KMS.",
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


def read_events(max_lines: int = 6) -> list[str]:
    if not EVENTS_FILE.is_file():
        return []
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-max_lines:]


def gather() -> dict[str, str]:
    cfg = load_env_file(CONFIG_ENV)
    dev = load_env_file(DEVICE_ENV)
    st = load_env_file(STATUS_FILE)
    live = load_env_file(LIVE_FILE)
    out = {
        "BT_MAC": dev.get("BT_MAC", st.get("BT_MAC", "")),
        "PHASE": st.get("PHASE", "unknown"),
        "STATUS_DETAIL": st.get("DETAIL", ""),
        "LIVE_DETAIL": live.get("DETAIL", ""),
        "COOLANT_C": live.get("COOLANT_C", ""),
        "OIL_C": live.get("OIL_C", ""),
        "IAT_C": live.get("IAT_C", ""),
        "AMBIENT_C": live.get("AMBIENT_C", ""),
        "RPM": live.get("RPM", ""),
        "LIVE_OK": live.get("OK", "0"),
    }
    out["RFCOMM"] = "up" if Path(cfg.get("RFCOMM_DEV", "/dev/rfcomm0")).exists() else "down"
    return out


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


def phase_color(phase: str) -> tuple[int, int, int]:
    p = (phase or "").lower()
    if p == "paired":
        return (40, 160, 70)
    if p in ("scanning", "waiting", "starting"):
        return (200, 140, 20)
    if p in ("retry", "bt-down"):
        return (220, 80, 60)
    return (140, 140, 140)


def _fmt_temp(val: str, unit: bool = True) -> str:
    if not val:
        return "--"
    return f"{val}°C" if unit else val


def draw_screen(pygame, screen, font_title, font, font_sm, font_mono, info, events) -> None:
    screen.fill((20, 22, 28))

    screen.blit(font_title.render("OBD", True, (240, 240, 240)), (10, 4))
    live_ok = info.get("LIVE_OK") == "1"
    badge = (40, 160, 70) if live_ok else (200, 140, 20)
    pygame.draw.rect(screen, badge, pygame.Rect(250, 4, 60, 18), border_radius=3)
    screen.blit(font_sm.render("LIVE" if live_ok else "WAIT", True, (255, 255, 255)), (260, 6))

    left = [
        ("Cool", info.get("COOLANT_C", ""), 105),
        ("Oil", info.get("OIL_C", ""), 120),
        ("IAT", info.get("IAT_C", ""), 60),
    ]
    right = [
        ("Amb", info.get("AMBIENT_C", ""), 45),
        ("RPM", info.get("RPM", ""), 0),
    ]
    y = 28
    for label, val, hot in left:
        unit = hot > 0
        color = temp_color(val, hot) if unit else (220, 220, 220)
        screen.blit(font_sm.render(label, True, (150, 150, 150)), (10, y + 2))
        screen.blit(font.render(_fmt_temp(val, unit), True, color), (48, y))
        y += 18

    y = 28
    for label, val, hot in right:
        unit = hot > 0
        color = temp_color(val, hot) if unit else (220, 220, 220)
        text = _fmt_temp(val, unit) if unit else (val or "--")
        screen.blit(font_sm.render(label, True, (150, 150, 150)), (170, y + 2))
        screen.blit(font.render(text, True, color), (210, y))
        y += 18

    phase = info.get("PHASE", "?")
    pc = phase_color(phase)
    pygame.draw.rect(screen, pc, pygame.Rect(10, 86, 8, 28), border_radius=2)
    mac = info.get("BT_MAC") or "no MAC"
    if len(mac) > 17:
        mac = mac[:17]
    screen.blit(font_sm.render(f"{phase} · {mac}", True, (230, 230, 230)), (24, 86))
    link = f"rfcomm {info.get('RFCOMM', '?')}"
    live_d = info.get("LIVE_DETAIL") or ""
    status_d = info.get("STATUS_DETAIL") or ""
    headline = status_d if (phase != "paired" or not live_ok) else live_d
    if not headline:
        headline = live_d or status_d or ""
    screen.blit(font_sm.render(f"{link} · {headline}"[:42], True, (170, 170, 170)), (24, 102))

    pygame.draw.line(screen, (50, 55, 65), (10, 120), (310, 120), 1)
    screen.blit(font_sm.render("activity", True, (120, 120, 130)), (10, 124))
    y = 140
    if not events:
        screen.blit(font_mono.render("(waiting for autopair…)", True, (100, 100, 110)), (10, y))
    for line in events:
        text = line if len(line) <= 42 else line[:39] + "…"
        color = (220, 100, 90) if ("FAIL" in line or "ERROR" in line.upper()) else (190, 195, 200)
        if "PAIR OK" in line or "paired " in line:
            color = (90, 200, 120)
        screen.blit(font_mono.render(text, True, color), (10, y))
        y += 14
        if y > H - 8:
            break


def main() -> None:
    disp = init_display()
    pygame = disp.pygame
    screen = disp.screen
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("dejavusans", 16, bold=True)
    font_sm = pygame.font.SysFont("dejavusans", 13)
    font_title = pygame.font.SysFont("dejavusans", 18, bold=True)
    font_mono = pygame.font.SysFont("dejavusansmono", 12) or font_sm

    last_refresh = 0.0
    info = gather()
    events = read_events()

    running = True
    try:
        while running:
            now = time.time()
            if now - last_refresh > 0.4:
                info = gather()
                events = read_events(6)
                last_refresh = now

            try:
                disp.poll_clicks()
            except SystemExit:
                running = False
                break

            draw_screen(pygame, screen, font_title, font, font_sm, font_mono, info, events)
            disp.flip()
            clock.tick(10)
    finally:
        disp.close()


if __name__ == "__main__":
    main()
