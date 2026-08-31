"""X (Twitter) + LinkedIn sources — zero-API-key social monitoring.

Strategy:
  * Discovery via RSS search endpoints that need no auth:
      - Google News RSS   (supports site: filters, fresh index)
      - Bing search RSS   (site: filter support)
      - Nitter RSS mirrors (native X search fallback)
  * A hit is a candidate "founder announced YC/Speedrun" post.
  * Enrichment for X: cdn.syndication.twimg.com returns full tweet JSON for a
    known tweet id without any auth.

Everything degrades gracefully: if one endpoint is blocked, the others still
produce results; if all fail, the source simply yields nothing this cycle.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")

NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://lightbrd.com",
]

YC_QUERY_GROUPS = [
    '"got into yc"',
    '"accepted into yc"',
    '"accepted to yc"',
    '"backed by y combinator"',
    '"yc s26" OR "yc w26" OR "yc f26" OR "speedrun batch"',
]


def _get(url: str, timeout: float = 15.0) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": UA,
                                       "Accept": "*/*"}, timeout=timeout)
        if r.status_code == 200 and r.text:
            return r.text
    except requests.RequestException:
        pass
    return None


def _parse_rss(xml_text: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        desc = html.unescape(re.sub("<[^>]+>", "", item.findtext("description") or "")).strip()
        pub = (item.findtext("pubDate") or "").strip()
        out.append({"title": title, "link": link, "description": desc, "published": pub})
    return out


# ---------------------------------------------------------------- discovery

def google_news_hits(query: str, when: str = "7d") -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}+when:{when}&hl=en-US&gl=US&ceid=US:en"
    return _parse_rss(_get(url) or "")


def bing_hits(query: str) -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"https://www.bing.com/search?q={q}&format=rss"
    return _parse_rss(_get(url) or "")


def nitter_hits(query: str, mirror: str | None = None) -> list[dict]:
    mirrors = [mirror] if mirror else NITTER_MIRRORS
    q = urllib.parse.quote(query)
    for base in mirrors:
        xml_text = _get(f"{base}/search/rss?f=tweets&q={q}", timeout=10.0)
        if xml_text:
            items = _parse_rss(xml_text)
            if items:
                for it in items:
                    it["link"] = it["link"].replace(base + "/", "https://x.com/") \
                        if "/status/" in it["link"] else it["link"]
                return items
    return []


def discover_social_posts(platform: str) -> list[dict]:
    """platform: 'x' | 'linkedin'. Returns deduped candidate posts."""
    site = "x.com" if platform == "x" else "linkedin.com"
    results: dict[str, dict] = {}
    for kw in YC_QUERY_GROUPS:
        queries = [
            f'site:{site}/posts {kw}' if platform == "linkedin" else f'site:{site} {kw}',
        ]
        for q in queries:
            # Google News RSS is the most reliable unauthed discovery endpoint;
            # its redirect links are resolved to real post URLs by the decoder.
            for hit in google_news_hits(q):
                key = _normalize_url(hit["link"]) or ("gnews:" + hit["title"][:100])
                if not key:
                    continue
                if key not in results:
                    hit["link"] = key if key.startswith("http") else hit["link"]
                    hit["platform"] = platform
                    results[key] = hit
        # native X search fallback
        if platform == "x":
            for hit in nitter_hits(kw):
                key = _normalize_url(hit["link"])
                if key and key not in results:
                    hit["link"] = key
                    hit["platform"] = "x"
                    results[key] = hit
    resolved = {}
    for key, hit in results.items():
        # NB: resolution of gnews redirects is done lazily in monitor.poll_social_sources
        # (only for unseen items) so steady-state scans stay fast.
        resolved[key] = hit
    # keep only candidate post items, freshest first, hard cap
    keep = {}
    for key, hit in resolved.items():
        link = hit.get("link") or ""
        if platform == "x" and not (re.search(r"/status/\d+", link) or "news.google.com" in link):
            continue
        if platform == "linkedin" and not ("/posts/" in link or "/feed/" in link or "news.google.com" in link):
            continue
        keep[key] = hit
        if len(keep) >= 40:
            break
    return list(keep.values())


# ---------------------------------------------------------------- link resolve

_gnews_cache: dict[str, str | None] = {}


def resolve_gnews_link(url: str) -> str | None:
    """Resolve a news.google.com/rss/articles/... redirect to the real post URL."""
    if "news.google.com/rss/articles/" not in url:
        return url if url.startswith("http") else None
    if url in _gnews_cache:
        return _gnews_cache[url]
    real = None
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url)
        if isinstance(res, dict) and res.get("status") and res.get("decoded_url"):
            real = res["decoded_url"]
    except Exception:
        real = None
    _gnews_cache[url] = real
    return real


def _normalize_url(link: str) -> str | None:
    """Canonicalize to a status/post URL so dedup is stable across feeds."""
    link = re.sub(r"^https?://(www\.)?", "https://", html.unescape(link))
    link = re.sub(r"https://x\.com", "https://twitter.com", link)  # legacy ids
    m = re.search(r"(https://(?:twitter|x)\.com/[^/\s]+/status/\d+)", link)
    if m:
        return m.group(1)
    m = re.search(r"(https://(?:[a-z]{2,3}\.)?linkedin\.com/posts/[^?\s]+)", link)
    if m:
        return re.sub(r"https://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", m.group(1))
    return None


# ---------------------------------------------------------------- enrichment

def enrich_tweet(status_url: str) -> dict | None:
    """Fetch full tweet JSON via the public syndication endpoint."""
    m = re.search(r"/status/(\d+)", status_url)
    if not m:
        return None
    tweet_id = m.group(1)
    for token in ("x", "a", "1"):
        data = _get(f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token={token}&lang=en",
                    timeout=10.0)
        if data:
            try:
                j = json.loads(data)
                if j.get("text"):
                    return {
                        "id": tweet_id,
                        "text": j.get("text", ""),
                        "author_name": (j.get("user") or {}).get("name", ""),
                        "author_handle": (j.get("user") or {}).get("screen_name", ""),
                        "created_at": j.get("created_at", ""),
                        "url": f"https://x.com/{(j.get('user') or {}).get('screen_name', 'i')}/status/{tweet_id}",
                    }
            except (json.JSONDecodeError, AttributeError):
                continue
    return None


def post_age_hours(published: str) -> float | None:
    """Best-effort parse of RFC822 pubDate into age hours."""
    from email.utils import parsedate_to_datetime
    if not published:
        return None
    try:
        dt = parsedate_to_datetime(published)
        return max(0.0, (time.time() - dt.timestamp()) / 3600.0)
    except Exception:
        return None
