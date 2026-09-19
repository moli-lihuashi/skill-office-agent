#!/usr/bin/env python3
"""Capture desktop GUI screenshot for docs."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "screenshots"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PY = os.environ.get("MIMO_PYTHON") or sys.executable


def main() -> int:
    proc = subprocess.Popen([PY, str(ROOT / "run_desktop.py")], cwd=str(ROOT))
    time.sleep(4.0)
    try:
        from PIL import ImageGrab
        user32 = ctypes.windll.user32
        found = []

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _l):
            length = user32.GetWindowTextLengthW(h)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(h, buf, length + 1)
            if "Skill Office Agent" in buf.value:
                found.append(h)
                try:
                    user32.ShowWindow(h, 9)  # SW_RESTORE
                    user32.SetForegroundWindow(h)
                except Exception:
                    pass
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        time.sleep(1.0)
        out = OUT_DIR / "desktop-gui.png"
        if found:
            rect = wintypes.RECT()
            user32.GetWindowRect(found[0], ctypes.byref(rect))
            box = (max(rect.left, 0), max(rect.top, 0), rect.right, rect.bottom)
            img = ImageGrab.grab(bbox=box, all_screens=True)
        else:
            print("window title not found; grab primary screen region")
            img = ImageGrab.grab()
            # keep a reasonable crop for docs
            img = img.crop((0, 0, min(img.width, 1280), min(img.height, 860)))
        img.save(out)
        print("saved", out, img.size)
        return 0
    except Exception as e:
        print("screenshot failed:", e)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
