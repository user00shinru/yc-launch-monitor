#!/usr/bin/env python3
"""Fully autonomous live-alert demo recorder.
1. Finds the Slack (browser) window, brings it to foreground
2. Starts ffmpeg gdigrab screen capture of that window (20 s)
3. At t=4 s fires alert for 1 new company, at t=9 s for 2 more
   (real YC data through the bot's real Slack pipeline)
4. Marks them seen so the monitor won't double-alert later.
"""
import ctypes
import subprocess
import sys
import time

from ctypes import wintypes

import config
import state
from sources.yc_algolia import YCAlgolia
from slack_alert import alert_official_companies

OUT = "live_alert_demo.mp4"
DUR = 20

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def find_slack_hwnd():
    res = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, lp):
        n = user32.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            t = buf.value
            if "Slack" in t and user32.IsWindowVisible(hwnd):
                res.append((hwnd, t))
        return True

    user32.EnumWindows(CB(cb), 0)
    return res[0] if res else None


def fetch_companies():
    with YCAlgolia() as yc:
        fresh = yc.recent_companies(hits=60)
    new = [c for c in fresh if not state.is_seen("company", "company:" + (c.get("slug") or ""))]
    if len(new) < 3:
        new = fresh[:3]
    return new[:3]


def main():
    hit = find_slack_hwnd()
    if hit:
        hwnd, title = hit
        print("window:", title[:80])
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.8)
        # bypass foreground lock: tap ALT, force top, verify
        for _ in range(3):
            user32.keybd_event(0x12, 0, 0, 0)      # ALT down
            user32.keybd_event(0x12, 0, 2, 0)      # ALT up
            user32.SetForegroundWindow(hwnd)
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)  # HWND_TOP, NOMOVE|NOSIZE|SHOWWINDOW
            time.sleep(0.7)
            if user32.GetForegroundWindow() == hwnd:
                break
        print("foreground ok:", user32.GetForegroundWindow() == hwnd)
        # reload Slack tab so all images load fresh, then wait for render
        user32.keybd_event(0x11, 0, 0, 0)   # CTRL down
        user32.keybd_event(0x52, 0, 0, 0)   # R down
        user32.keybd_event(0x52, 0, 2, 0)   # R up
        user32.keybd_event(0x11, 0, 2, 0)   # CTRL up
        print("reload sent, waiting 9s for full load...")
        time.sleep(9.0)
        # clamp visible rect to desktop (drop shadow margins)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        x = max(0, rect.left)
        y = max(0, rect.top)
        w = min(rect.right, sw) - x
        h = min(rect.bottom, sh) - y
        print(f"capture WINDOW-ONLY region: {x},{y} {w}x{h}")
        # even-align for yuv420p
        w -= w % 2
        h -= h % 2
        geo = ["-video_size", f"{w}x{h}", "-offset_x", str(x), "-offset_y", str(y)]
    else:
        geo = ["-video_size", f"{user32.GetSystemMetrics(0)}x{user32.GetSystemMetrics(1)}",
               "-offset_x", "0", "-offset_y", "0"]
        print("capture: full desktop (fallback)")

    companies = fetch_companies()
    if "--refire" in sys.argv:
        con = state._conn()
        for c in companies:
            con.execute("DELETE FROM seen WHERE uid = ?", ("company:" + (c.get("slug") or ""),))
        con.commit()
        con.close()
        print("seen reset for refire")
    print("companies to fire:", [c.get("name") for c in companies])

    cmd = ["ffmpeg", "-y", "-f", "gdigrab", *geo, "-framerate", "30",
           "-i", "desktop", "-t", str(DUR),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", OUT]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t0 = time.time()
    time.sleep(6.0)
    print("FIRE 1:", alert_official_companies([companies[0]]))
    time.sleep(5.0)
    print("FIRE 2+3:", alert_official_companies(companies[1:]))
    for c in companies:
        state.mark_seen("company", "company:" + (c.get("slug") or ""), c, alerted=True)

    proc.wait(timeout=DUR + 30)
    import os
    sz = os.path.getsize(OUT) if os.path.exists(OUT) else 0
    print(f"RECORDED {OUT}: {sz} bytes, elapsed {time.time()-t0:.1f}s")
    sys.exit(0 if sz > 10000 else 1)


if __name__ == "__main__":
    main()
