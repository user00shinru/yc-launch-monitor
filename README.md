# YC Launch Monitor — Slack Bot

Persistent Slack bot that monitors **4 sources** for new Y Combinator / YC Speedrun
company launches and posts alerts — including **early founder announcements**
detected on X (Twitter) and LinkedIn **before** the company appears in the
official YC directory.

Built for the [Pond task "Build a YC Launch Monitor Slack Bot"](https://joinpond.ai/tasks/detail/e6523796-5350-4110-966e-0c3219f5e959).

## What it does

| # | Source | What it detects | How |
|---|--------|-----------------|-----|
| 1 | **YC Directory** | New companies in ycombinator.com/companies | Headless-browser queries of YC's own Algolia index (`YCCompany_By_Launch_Date_production`), newest-launch-first |
| 2 | **Launch YC posts** | Official launch announcements (`/launches`) | Same technique, `Launches_by_date_production` index — the page's own API key is captured at runtime |
| 3 | **X (Twitter)** | Founder "we got into YC / YC S26 / Speedrun" posts | Google News RSS `site:x.com` discovery + public redirect decoder + tweet enrichment via the open syndication endpoint |
| 4 | **LinkedIn** | Founder / company launch posts | Google News RSS `site:linkedin.com/posts` discovery + redirect decoder |

**Early-detection logic** — a post that matches acceptance keywords
("got into YC", "accepted into YC", "backed by Y Combinator", "Speedrun batch", …)
is cross-checked against the YC directory by author/company name. The alert
tells you whether the company is already officially listed (`in_directory`)
or still unannounced — i.e. a true *early* signal.

**Persistent & stateful** — every company, launch post, and social post is
recorded in SQLite (`data/seen.db`). Alerts fire exactly once. A first-run
`--baseline` pass pre-seeds the current directory so your first alert window
contains only genuinely new items. Poll cadence defaults to **every 8 hours**
(`POLL_INTERVAL_HOURS`).

## Quick start

```bash
# 1. Install (Python 3.10+)
pip install -r requirements.txt
playwright install chromium

# 2. Configure Slack
cp .env.example .env
#    -> create a Slack app: https://api.slack.com/apps (From scratch)
#    -> OAuth & Permissions: add bot scope chat:write
#    -> Install to workspace, copy the Bot User OAuth Token (xoxb-...)
#    -> put SLACK_BOT_TOKEN + SLACK_ALERT_CHANNEL (e.g. #yc-launches) in .env
#    -> /invite @YourBot into the channel

# 3. Baseline pass (no alerts) — records what exists today
python bot.py --baseline

# 4. Run continuously (alerts every new company/post, scans every 8h)
python bot.py

# single scan instead of the loop:
python bot.py --once
```

## Slack alert format

* **Official** — `🚀 N new YC company/ies detected` with name, batch, location,
  one-liner, industry, launch timestamp and a link per company (Block Kit sections).
* **Early** — `🕵️ EARLY SIGNAL [𝕏|in] — possible new YC company` with author,
  handle, post text, and a link to the original post.

## Pond agent integration

The monitor exposes a Pond-Protocol-V1 compatible HTTP agent
(`agent_server.py`) so the work can be reviewed, verified, and health-checked
by Pond:

```bash
python bot.py --agent          # serves /manifest + /runs + /tasks on :8001
```

| Endpoint | Auth | Purpose |
|----------|------|---------|
| `GET /manifest` | public | Agent metadata + 3 actions |
| `POST /runs` → `health_check` | Bearer | Monitor status, counters, last cycle result |
| `POST /runs` → `latest_alerts` | Bearer | Recent detections (early + official) |
| `POST /runs` → `force_scan` | Bearer | Trigger a full 4-source scan now (async task, poll via `GET /tasks/{id}`) |

Set `POND_ACCESS_KEY` in `.env`; requests must send
`Authorization: Bearer <key>`. Auth failures return 401; unknown actions 400.

## Project layout

```
bot.py               entrypoint: --loop (default) | --once | --baseline | --agent
monitor.py           scan orchestration + early-detection cross-check
config.py            env config (Slack, cadence, keywords, batches)
state.py             SQLite persistence (dedup, alert history, health counters)
slack_alert.py       Block Kit alert formatting + WebClient
sources/
  yc_algolia.py      headless-browser Algolia queries (YC directory + Launch YC)
  social.py          Google News RSS discovery, gnews URL decoder, tweet enrich
agent_server.py      Pond Protocol V1 FastAPI agent
test_agent.py        e2e test of the agent server
```

## Extending to new platforms

Add a `sources/<platform>.py` that yields `{title, link, description, published}`
items and a discovery call in `monitor.poll_social_sources` — dedup, keyword
matching, cross-checking and alerting are already handled centrally.

## Notes

* All data access is via public, unauthenticated endpoints (YC's own
  client-side Algolia, Google News RSS, the public tweet syndication CDN).
  No paid APIs.
* First social scan resolves redirect links (~30–60s); steady-state scans skip
  already-seen feed entries entirely.
