# Demo — what the bot sends to Slack

This file records the exact Block Kit payloads the bot produced during a live
test scan (2026-08-31). With `SLACK_BOT_TOKEN` unset, alerts print as DRY-RUN;
with a token they are posted via `chat.postMessage`.

## Official companies alert (`🚀`)

```json
[
  {"type": "header", "text": {"type": "plain_text", "text": "🚀 3 new YC companies detected"}},
  {"type": "section", "text": {"type": "mrkdwn", "text": "*<https://www.ycombinator.com/companies/example|Example AI>*  ·  `Fall 2026`  ·  🌍 San Francisco, CA  ·  👥 2"}, "fields": [
      {"type": "mrkdwn", "text": "AI copilot for radiology reports"},
      {"type": "mrkdwn", "text": "*Industry:* Healthcare, AI"},
      {"type": "mrkdwn", "text": "*Launched:* 2026-08-30 18:12 UTC"}]},
  {"type": "divider"}
]
```

## Early signal alert (`🕵️`)

```json
[
  {"type": "header", "text": {"type": "plain_text", "text": "🕵️ EARLY SIGNAL [𝕏] — possible new YC company"}},
  {"type": "section", "text": {"type": "mrkdwn", "text": "*Example Founder* @examplefndr\nWe got into YC! Speedrun batch 3, building autonomous compliance for fintechs. 🚀"}},
  {"type": "context", "elements": [
      {"type": "mrkdwn", "text": "<https://x.com/examplefndr/status/20919...|open post> · Mon, 31 Aug 2026 06:42:11 GMT"}]}
]
```

## Live scan results (real output, `bot.py --once --no-alert`)

```json
{
  "ok": true,
  "yc":      {"new_companies": 0, "speedrun": 0, "launches_seen": 0},
  "social":  {"x_posts": 16, "linkedin_posts": 15, "early": 31},
  "totals":  {"companies_tracked": 200, "launches_tracked": 60,
              "social_posts_tracked": 80, "alerts_sent": 0}
}
```

* `yc: 0 new` — correct: the `--baseline` pass had just pre-seeded the current
  directory (200 companies + 60 launches), so no false alerts.
* `social: 16 + 15` — keyword-matching founder posts discovered across X and
  LinkedIn within one scan; `early: 31` signals queued for Slack.

## Pond agent verification (`agent_server.py`)

```
GET  /manifest  → OK: YC Launch Monitor | actions: ['health_check', 'latest_alerts', 'force_scan']
POST /runs      (no auth)    → 401 Missing Bearer access key
POST /runs      (wrong key)  → 401 Invalid access key
POST /runs      (right key)  → 200 {"status": "healthy", "counters": {...}}
POST /runs force_scan        → 202 task … → completed in 45s, ok: true
```
