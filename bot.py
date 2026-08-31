#!/usr/bin/env python3
"""YC Launch Monitor — entrypoint.

  python bot.py            # continuous loop, scans every POLL_INTERVAL_HOURS
  python bot.py --once     # single scan, then exit
  python bot.py --baseline # mark current directory as seen WITHOUT alerting
  python bot.py --agent    # run the Pond agent HTTP server instead
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import config
import monitor
import slack_alert


def _setup_baseline() -> None:
    """First run: record everything currently visible as already-seen,
    so the first alert window only contains genuinely new items."""
    from sources.yc_algolia import YCAlgolia
    with YCAlgolia() as yc:
        companies = yc.recent_companies(hits=200)
        for c in companies:
            uid = str(c.get("slug") or c.get("id") or c.get("objectID"))
            if uid:
                monitor.state.mark_seen("company", uid, {"name": c.get("name")}, alerted=False)
        try:
            launches = yc.recent_launches(hits=60)
            for l in launches:
                comp = l.get("company") or {}
                uid = str(l.get("objectID") or l.get("id") or comp.get("slug", "?"))
                if uid:
                    monitor.state.mark_seen("launch", uid, {}, alerted=False)
        except Exception as e:
            print(f"[baseline] launches skipped: {e}")
        # seed social sources too so the first real scan isn't a flood
        monitor.poll_social_sources(yc, alert=False)
    print(f"[baseline] marked {monitor.state.count('company')} companies + "
          f"{monitor.state.count('launch')} launches as pre-seen")


def _run_once(alert: bool, lookback: float | None) -> dict:
    res = monitor.run_cycle(alert=alert, lookback_hours=lookback)
    print(json.dumps({k: v for k, v in res.items() if k != "errors"}, indent=2, default=str))
    for e in res.get("errors", []):
        print(f"[error] {e}", file=sys.stderr)
    return res


def _loop() -> None:
    interval = max(0.05, config.POLL_INTERVAL_HOURS) * 3600
    print(f"[bot] starting continuous monitor — every {config.POLL_INTERVAL_HOURS}h "
          f"(alerts -> {config.SLACK_ALERT_CHANNEL or 'DRY-RUN'})")
    while True:
        t0 = time.time()
        try:
            _run_once(alert=True, lookback=None)
        except Exception as e:
            print(f"[fatal-cycle] {e}", file=sys.stderr)
        sleep_s = max(60, interval - (time.time() - t0))
        print(f"[bot] next scan in {sleep_s / 3600:.1f}h")
        time.sleep(sleep_s)


def main() -> None:
    ap = argparse.ArgumentParser(description="YC Launch Monitor Slack Bot")
    ap.add_argument("--once", action="store_true", help="single scan then exit")
    ap.add_argument("--baseline", action="store_true",
                    help="pre-seen current directory, no alerts")
    ap.add_argument("--agent", action="store_true", help="run Pond agent HTTP server")
    ap.add_argument("--no-alert", action="store_true", help="scan without Slack alerts")
    args = ap.parse_args()

    if args.agent:
        config.die_if_missing(need_slack=False)
        import uvicorn
        from agent_server import app
        uvicorn.run(app, host="127.0.0.1", port=config.AGENT_PORT)
        return

    if args.baseline:
        _setup_baseline()
        return

    config.die_if_missing(need_slack=not args.no_alert)
    if args.once:
        _run_once(alert=not args.no_alert, lookback=None)
    else:
        _loop()


if __name__ == "__main__":
    main()
