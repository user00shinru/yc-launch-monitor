#!/usr/bin/env python3
"""Check which channel the bot posts to + list all channels the bot can see."""
import json
import pathlib
import urllib.request

env = {}
for line in (pathlib.Path(__file__).parent / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

TOK = env["SLACK_BOT_TOKEN"]
HDR = {"Authorization": "Bearer " + TOK}

def api(method, params=""):
    url = f"https://slack.com/api/{method}" + ("?" + params if params else "")
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

target = env.get("SLACK_ALERT_CHANNEL", "")
info = api("conversations.info", "channel=" + target)
name = info.get("channel", {}).get("name") if info.get("ok") else "?"
print("SLACK_ALERT_CHANNEL =", target, "->", "#" + str(name))

lst = api("conversations.list", "limit=100&types=public_channel,private_channel")
print("channels visible to bot:")
for ch in lst.get("channels", []):
    print("  -", ch["id"], "#" + ch["name"], "(bot member)" if ch.get("is_member") else "")
