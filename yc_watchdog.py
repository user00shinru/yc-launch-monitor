#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YC agent keep-alive watchdog (pure stdlib, silent-when-healthy).

Checks every run:
  1. Agent server responding on 127.0.0.1:8001 (spawns `py -3.10 agent_server.py` if dead)
  2. cloudflared quick-tunnel process alive (spawns + re-extracts URL if dead/unreachable)
  3. Pinned URL still serves /manifest 200 (restarts tunnel if not)

Prints ONLY when something was fixed or the public URL changed (watchdog pattern).
URL source of truth: C:/Users/Bisma/yc_monitor/current_url.txt
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

BASE = r"C:\Users\Bisma\yc_monitor"  # fixed — script may run from hermes/scripts/ via cron
URL_FILE = os.path.join(BASE, "current_url.txt")
TUNNEL_LOG = os.path.join(BASE, "tunnel.log")
SERVER_LOG = os.path.join(BASE, "server.log")
LOCK_FILE = os.path.join(BASE, ".watchdog.lock")
CF = r"C:\Users\Bisma\vmos-bitccoin\cloudflared.exe"
PORT = 8001
DETACHED = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PGROUP | NO_WINDOW

_CLEAN_KEYS = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
               "TEMP", "TMP", "USERNAME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
               "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "PROGRAMFILES")


def clean_env():
    env = {k: os.environ[k] for k in _CLEAN_KEYS if k in os.environ}
    env.setdefault("SYSTEMROOT", r"C:\Windows")
    env.setdefault("TEMP", os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\Bisma\AppData\Local"), "Temp"))
    env.setdefault("TMP", env["TEMP"])
    return env


def locked_recently(seconds=240):
    try:
        if time.time() - os.path.getmtime(LOCK_FILE) < seconds:
            return True
    except OSError:
        pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(time.time()))
    return False


def port_open(port):
    import socket
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wmic_pids(query):
    try:
        out = subprocess.run(f'wmic process where "{query}" get processid',
                             capture_output=True, text=True, shell=True, timeout=20).stdout
        return re.findall(r"\b\d{2,}\b", out)
    except Exception:
        return []


def http_ok(url, timeout=12):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    log = open(SERVER_LOG, "ab")
    subprocess.Popen(["py", "-3.10", "agent_server.py"], cwd=BASE, env=clean_env(),
                     creationflags=DETACHED, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(10):
        time.sleep(2)
        if port_open(PORT):
            return True
    return False


def start_tunnel():
    # rotate log so the extracted URL is guaranteed to be the CURRENT tunnel's
    if os.path.exists(TUNNEL_LOG):
        try:
            shutil.move(TUNNEL_LOG, TUNNEL_LOG + ".prev")
        except OSError:
            pass
    log = open(TUNNEL_LOG, "wb")
    subprocess.Popen([CF, "tunnel", "--url", "http://localhost:8001"], cwd=BASE,
                     env=clean_env(), creationflags=DETACHED,
                     stdout=log, stderr=subprocess.STDOUT)
    for _ in range(10):
        time.sleep(3)
        try:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",
                          open(TUNNEL_LOG, "r", errors="ignore").read())
            if m:
                return m.group(0)
        except OSError:
            pass
    return None


def kill_cloudflared():
    for pid in wmic_pids("name='cloudflared.exe'"):
        subprocess.run(f"wmic process where processid={pid} delete",
                       capture_output=True, shell=True, timeout=20)
    time.sleep(2)


def main():
    if locked_recently():
        sys.exit(0)
    msgs = []

    # 1) agent server
    if not port_open(PORT):
        ok = start_server()
        msgs.append("YC agent server MATI → di-restart " + ("OK (port 8001 up)" if ok else "GAGAL — cek server.log"))
    else:
        # make sure it actually answers
        if not http_ok("http://127.0.0.1:8001/manifest", 8):
            msgs.append("YC agent server port 8001 up tapi /manifest gagal — CEK server.log")

    # 2+3) tunnel alive AND serving
    url = None
    pids = wmic_pids("name='cloudflared.exe'")
    if pids:
        try:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com",
                          open(TUNNEL_LOG, "r", errors="ignore").read())
            url = m.group(0) if m else None
        except OSError:
            pass
        if url and not http_ok(url + "/manifest"):
            kill_cloudflared()
            url = None
            msgs.append("Tunnel hidup tapi /manifest unreachable → restart tunnel")

    if not url:
        url = start_tunnel()
        if url:
            msgs.append("Tunnel cloudflared di-restart")
        else:
            msgs.append("TUNNEL GAGAL START — tidak ada URL di tunnel.log")

    if url:
        ok = http_ok(url + "/manifest")
        prev = None
        if os.path.exists(URL_FILE):
            try:
                prev = open(URL_FILE).read().strip()
            except OSError:
                pass
        if url != prev:
            with open(URL_FILE, "w") as f:
                f.write(url)
            msgs.append(f"URL PUBLIK POND: {url}" + (" (BERUBAH dari " + prev + ")" if prev else " (pinned)"))
        if not ok:
            msgs.append(f"URL {url} masih GAGAL /manifest — cek tunnel.log")

    if msgs:
        print("🛰 YC Launch Monitor keep-alive\n" + "\n".join("• " + m for m in msgs))


if __name__ == "__main__":
    main()
