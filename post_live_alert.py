#!/usr/bin/env python3
"""Live-alert demo — posts a REAL company via the bot's REAL Slack pipeline.

--dry : shows what would be posted (no Slack call)
(fire): fetches YC companies live, alerts genuinely-new ones if any,
        otherwise posts the newest company as a live demo alert.
"""
import sys

from sources.yc_algolia import YCAlgolia
import state
from slack_alert import alert_official_companies
import config


def pick():
    with YCAlgolia() as yc:
        fresh = yc.recent_companies(hits=60)
    new = [c for c in fresh if not state.is_seen("company", "company:" + (c.get("slug") or ""))]
    if new:
        return new[:3], True
    return fresh[:1], False


if __name__ == "__main__":
    comps, is_new = pick()
    names = [c.get("name") for c in comps]
    if "--dry" in sys.argv:
        print("would post:", names, "| genuinely-new:", is_new)
        sys.exit(0)
    sent = alert_official_companies(comps)
    print(f"FIRED -> slack channel {config.SLACK_ALERT_CHANNEL}: {names} (alerts_sent={sent})")
