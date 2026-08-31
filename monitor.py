"""Core monitor — polls all 4 sources, dedups, cross-checks, fires alerts."""
from __future__ import annotations

import json
import time
import traceback

import state
import slack_alert
from config import CURRENT_BATCHES, EARLY_KEYWORDS, LOOKBACK_HOURS
from sources.yc_algolia import YCAlgolia
from sources import social

KW_LOWER = [k.lower() for k in EARLY_KEYWORDS]


def _match_keywords(text: str) -> str | None:
    t = (text or "").lower()
    for kw in KW_LOWER:
        if kw in t:
            return kw
    return None


def _is_speedrun(c: dict) -> bool:
    blob = json.dumps({k: c.get(k) for k in ("batch", "tags", "industries", "one_liner",
                                             "long_description", "name")}).lower()
    return "speedrun" in blob


def poll_yc_sources(yc: YCAlgolia, alert: bool, lookback_hours: float) -> dict:
    """Sources 1+2: YC directory & Launch YC official posts. Returns stats."""
    now = time.time()
    stats = {"new_companies": 0, "speedrun": 0, "launches_seen": 0}

    companies = yc.recent_companies(hits=60) or []
    for c in companies:
        uid = str(c.get("slug") or c.get("id") or c.get("objectID"))
        if not uid or state.is_seen("company", uid):
            continue
        la = c.get("launched_at") or 0
        if la and la < now - lookback_hours * 3600:
            state.mark_seen("company", uid, {"name": c.get("name")}, alerted=False)
            continue
        state.mark_seen("company", uid, {"name": c.get("name")}, alerted=alert)
        stats["new_companies"] += 1
        if _is_speedrun(c):
            stats["speedrun"] += 1

    try:
        launches = yc.recent_launches(hits=40) or []
    except Exception as e:
        print(f"[warn] launches source failed: {e}")
        launches = []
    for l in launches:
        comp = l.get("company") or {}
        uid = str(l.get("objectID") or l.get("id") or
                  f"{comp.get('slug','?')}-{l.get('createdAt','')}")
        if not uid or state.is_seen("launch", uid):
            continue
        created = l.get("createdAt") or 0
        if isinstance(created, (int, float)) and created > 1e12:
            created = created / 1000.0
        if created and created < now - lookback_hours * 3600:
            state.mark_seen("launch", uid, {}, alerted=False)
            continue
        state.mark_seen("launch", uid, {"name": comp.get("name")}, alerted=alert)
        stats["launches_seen"] += 1
        if str(l.get("batch") or comp.get("batch") or "").lower().find("speedrun") >= 0:
            stats["speedrun"] += 1

    return stats


def poll_social_sources(yc: YCAlgolia, alert: bool) -> dict:
    """Sources 3+4: X + LinkedIn founder announcements (early detection)."""
    stats = {"x_posts": 0, "linkedin_posts": 0, "early": 0}
    signals: list[dict] = []

    for platform in ("x", "linkedin"):
        posts = social.discover_social_posts(platform)
        fresh = 0
        for p in posts:
            raw_link = p.get("link") or ""
            raw_key = platform + ":gnews:" + raw_link if "news.google.com" in raw_link else None
            if raw_key and state.is_seen(raw_key):
                continue  # already processed via this feed entry
            # resolve Google News redirects lazily — only for items not yet processed
            if raw_key:
                real = social.resolve_gnews_link(raw_link)
                if not real:
                    continue
                p["link"] = real
                key = platform + ":" + real
            else:
                key = platform + ":" + (raw_link or p["title"][:80])
            if state.is_seen("social_post", key):
                if raw_key:
                    state.mark_seen(raw_key)  # cache resolution result
                continue
            # also treat a canonical status URL as the dedup key
            canon = social._normalize_url(p.get("link") or "")
            alt_key = platform + ":" + canon if canon and canon != p["link"] else None
            if alt_key and state.is_seen("social_post", alt_key):
                if raw_key:
                    state.mark_seen(raw_key)
                continue
            # keyword match on title/description/tweet text
            text = " ".join(filter(None, [p.get("title"), p.get("description")]))
            enriched = None
            if platform == "x" and "/status/" in (p.get("link") or ""):
                enriched = social.enrich_tweet(p["link"])
                if enriched:
                    text += " " + enriched["text"]
            kw = _match_keywords(text)
            # only keep the post as unseen if it actually matches a keyword
            state.mark_seen("social_post", key, {"title": p.get("title")}, alerted=bool(kw))
            if alt_key:
                state.mark_seen("social_post", alt_key, {"title": p.get("title")}, alerted=bool(kw))
            if raw_key:
                state.mark_seen(raw_key)  # so future scans skip resolving this feed entry
            if kw:
                fresh += 1
                sig = {
                    "platform": platform,
                    "keyword": kw,
                    "title": p.get("title"),
                    "description": p.get("description"),
                    "link": p.get("link"),
                    "published": p.get("published"),
                    "age_hours": social.post_age_hours(p.get("published") or ""),
                }
                if enriched:
                    sig.update({"text": enriched["text"],
                                "author_name": enriched["author_name"],
                                "author_handle": enriched["author_handle"],
                                "url": enriched["url"]})
                # cross-check against directory: name match?
                sig["in_directory"] = False
                probe = _extract_name(sig) or ""
                if probe:
                    try:
                        hits = yc.search_companies(probe, hits=3)
                        sig["in_directory"] = any(
                            (h.get("name") or "").lower() == probe.lower() for h in hits)
                    except Exception:
                        pass
                signals.append(sig)
        if platform == "x":
            stats["x_posts"] = fresh
        else:
            stats["linkedin_posts"] = fresh

    if signals and alert:
        slack_alert.alert_early_signals(signals)
        for s in signals:
            state.record_alert("early", s.get("author_name") or s.get("title", "?"),
                               (s.get("text") or s.get("description") or "")[:300],
                               s.get("url") or s.get("link") or "")
    stats["early"] = len(signals)
    return stats


def _extract_name(sig: dict) -> str | None:
    """Heuristic: company name from an X post = author display name (founder posts
    usually come from the company/founder account). For LinkedIn, take title."""
    if sig.get("platform") == "x":
        name = sig.get("author_name")
        if name and 2 < len(name) < 60 and "|" not in name:
            return name.strip()
    title = sig.get("title") or ""
    if " on LinkedIn" in title:
        return title.split(" on LinkedIn")[0].strip() or None
    return None


def run_cycle(yc: YCAlgolia | None = None, alert: bool = True,
              lookback_hours: float | None = None) -> dict:
    """One full scan across all sources. Returns combined stats."""
    own = yc is None
    if own:
        yc = YCAlgolia()
    lb = lookback_hours if lookback_hours is not None else LOOKBACK_HOURS
    result = {"ts": time.time(), "ok": True, "errors": []}
    try:
        result["yc"] = poll_yc_sources(yc, alert, lb)
    except Exception:
        result["ok"] = False
        result["errors"].append("yc_sources: " + traceback.format_exc(limit=3))
    try:
        result["social"] = poll_social_sources(yc, alert)
    except Exception:
        result["ok"] = False
        result["errors"].append("social_sources: " + traceback.format_exc(limit=3))
    result["totals"] = {
        "companies_tracked": state.count("company"),
        "launches_tracked": state.count("launch"),
        "social_posts_tracked": state.count("social_post"),
        "alerts_sent": state.alert_count(),
        "last_alert_ts": state.last_alert_time(),
    }
    state.set_meta("last_cycle", json.dumps(
        {"ts": result["ts"], "ok": result["ok"], "stats": result.get("yc"), "social": result.get("social")}))
    if own:
        yc.close()
    return result
