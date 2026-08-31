"""Slack alerts — Block Kit messages for official + early-detection signals."""
from __future__ import annotations

import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config


def _client() -> WebClient | None:
    if not config.SLACK_BOT_TOKEN:
        return None
    return WebClient(token=config.SLACK_BOT_TOKEN)


def _send(channel: str, blocks: list, text: str) -> bool:
    client = _client()
    if client is None:
        print(f"[slack-DRY] -> {channel}: {text[:200]}")
        return True
    for attempt in (channel, f"#{channel.lstrip('#')}"):
        try:
            client.chat_postMessage(channel=attempt, blocks=blocks, text=text)
            return True
        except SlackApiError as e:
            last_err = e
    print(f"[slack-ERR] {getattr(last_err, 'response', {}).get('error', last_err)}")
    return False


def _fmt_company(c: dict) -> dict:
    name = c.get("name") or "Unknown"
    one = c.get("one_liner") or c.get("long_description") or ""
    batch = c.get("batch") or "?"
    slug = c.get("slug") or ""
    url = c.get("website") or f"https://www.ycombinator.com/companies/{slug}"
    loc = c.get("all_locations") or ""
    industry = ", ".join((c.get("tags") or [])[:3]) or (c.get("subindustry") or "")
    team = c.get("team_size")
    la = c.get("launched_at")
    la_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(la)) if isinstance(la, (int, float)) else ""
    text = (f"*<{url}|{name}>*  ·  `{batch}`"
            + (f"  ·  🌍 {loc}" if loc else "")
            + (f"  ·  👥 {team}" if isinstance(team, int) else ""))
    fields = []
    if one:
        fields.append({"type": "mrkdwn", "text": f"{one[:180]}"})
    if industry:
        fields.append({"type": "mrkdwn", "text": f"*Industry:* {industry}"})
    if la_str:
        fields.append({"type": "mrkdwn", "text": f"*Launched:* {la_str}"})
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}, "fields": fields[:3]}


def alert_official_companies(companies: list[dict]) -> int:
    """New companies detected in the YC directory / Launch YC."""
    if not companies:
        return 0
    ch = config.SLACK_ALERT_CHANNEL
    sent = 0
    for group_start in range(0, len(companies), 8):
        chunk = companies[group_start:group_start + 8]
        blocks = [{
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚀 {len(companies)} new YC company{'ies' if len(companies) != 1 else 'y'} detected" if group_start == 0 else "…continued"},
        }]
        for c in chunk:
            blocks.append(_fmt_company(c))
            blocks.append({"type": "divider"})
        text = "New YC companies: " + ", ".join(c.get("name", "?") for c in chunk)
        if _send(ch, blocks[:48], text):
            sent += len(chunk)
    return sent


def alert_early_signals(signals: list[dict]) -> int:
    """Founder posts that hint at a new YC/Speedrun company before official listing."""
    if not signals:
        return 0
    ch = config.SLACK_EARLY_CHANNEL or config.SLACK_ALERT_CHANNEL
    sent = 0
    for s in signals:
        plat = "𝕏" if s.get("platform") == "x" else "in"
        author = s.get("author_name") or s.get("author_handle") or s.get("title", "?")
        handle = f"@{s['author_handle']}" if s.get("author_handle") else ""
        body = s.get("text") or s.get("description") or ""
        url = s.get("url") or s.get("link") or ""
        blocks = [
            {"type": "header", "text": {"type": "plain_text",
             "text": f"🕵️ EARLY SIGNAL [{plat}] — possible new YC company"}},
            {"type": "section", "text": {"type": "mrkdwn",
             "text": f"*{author}* {handle}\n{body[:500]}"}},
            {"type": "context", "elements": [
                {"type": "mrkdwn", "text": f"<{url}|open post> · {s.get('published', '')}"}]},
        ]
        if _send(ch, blocks, f"Early signal: {author} — {body[:120]}"):
            sent += 1
    return sent
