"""YC data sources via Algolia, driven through a real browser context.

YC's public directory runs 100% client-side on Algolia (app 45BWZJ1SGC).
Server-side calls with the public search key are rejected (403), but the same
key works from a real browser origin — so we execute the queries in-page via
Playwright and pull structured JSON back out. This mirrors exactly what
ycombinator.com does on every page load.

Indexes:
  - YCCompany_By_Launch_Date_production : every YC company, newest launch first.
  - Launches_by_date_production         : Launch YC launch posts (official announcements).

The company key is static in the page HTML; the launches key is fetched at
runtime by listening for the page's own Algolia request.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

COMPANIES_URL = "https://www.ycombinator.com/companies"
LAUNCHES_URL = "https://www.ycombinator.com/launches"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")


class YCAlgolia:
    """Persistent headless browser executing in-page Algolia queries."""

    def __init__(self, headless: bool = True):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._ctx = self._browser.new_context(user_agent=UA, locale="en-US")
        self._page = self._ctx.new_page()
        self._captures: list[str] = []
        self._company_key: str | None = None
        self._launch_key: str | None = None

    # ---------- internals ----------

    def _goto(self, url: str):
        self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)

    @staticmethod
    def _key_from_html(html: str) -> str | None:
        m = re.search(r'"app":"([A-Z0-9]+)","key":"([^"]+)"', html)
        return m.group(2) if m else None

    def _capture_keys_from_network(self):
        """Listen for Algolia requests and steal their API keys (launches page)."""
        self._captures = []

        def _on_request(req):
            if "algolia" in req.url and "x-algolia-api-key=" in req.url:
                m = re.search(r"x-algolia-api-key=([^&]+)", req.url)
                if m:
                    self._captures.append(m.group(1))

        self._page.on("request", _on_request)
        return _on_request

    def _inpage_query(self, app: str, key: str, index: str, params: str) -> dict:
        """Run an Algolia multi-query from inside the page (browser origin)."""
        script = """
        async ([app, key, index, params]) => {
            const url = `https://${app.toLowerCase()}-dsn.algolia.net/1/indexes/*/queries`
                + `?x-algolia-application-id=${encodeURIComponent(app)}`
                + `&x-algolia-api-key=${encodeURIComponent(key)}`;
            const body = { requests: [{ indexName: index, params: params }] };
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            return { status: r.status, data: await r.json().catch(() => null) };
        }
        """
        out = self._page.evaluate(script, [app, key, index, params])
        if out.get("status") != 200 or not out.get("data"):
            raise RuntimeError(f"Algolia in-page query failed: {out}")
        res = out["data"]["results"][0]
        if res.get("hits") is None:
            raise RuntimeError(f"Algolia error: {json.dumps(res)[:300]}")
        return res

    # ---------- public API ----------

    def ensure_companies_page(self):
        if "ycombinator.com/companies" not in self._page.url:
            self._goto(COMPANIES_URL)
            self._page.wait_for_function("() => window.AlgoliaOpts && window.AlgoliaOpts.key",
                                         timeout=30_000)
            self._company_key = self._page.evaluate("() => window.AlgoliaOpts.key")

    def recent_companies(self, hits: int = 60) -> list[dict[str, Any]]:
        """Newest-launched YC companies from the public directory."""
        self.ensure_companies_page()
        app = "45BWZJ1SGC"
        res = self._inpage_query(app, self._company_key,
                                 "YCCompany_By_Launch_Date_production",
                                 f"hitsPerPage={hits}")
        return res["hits"]

    def recent_launches(self, hits: int = 50) -> list[dict[str, Any]]:
        """Newest Launch YC posts (official YC announcements)."""
        self._goto(LAUNCHES_URL)
        listener = self._capture_keys_from_network()
        try:
            # the page fires its own Algolia search shortly after load
            self._page.wait_for_timeout(4000)
            if self._page.locator("input[type=search], input[placeholder*=Search]").count():
                try:
                    self._page.locator(
                        "input[type=search], input[placeholder*=Search]").first.fill("a", timeout=5000)
                    self._page.wait_for_timeout(2500)
                except PWTimeout:
                    pass
        finally:
            self._page.remove_listener("request", listener)

        if not self._captures:
            raise RuntimeError("Could not capture launches Algolia key from network")
        self._launch_key = self._captures[-1]

        body_params = "hitsPerPage=%d" % hits
        script = """
        async ([app, key, index, params]) => {
            const url = `https://${app.toLowerCase()}-dsn.algolia.net/1/indexes/*/queries`
                + `?x-algolia-application-id=${encodeURIComponent(app)}`
                + `&x-algolia-api-key=${encodeURIComponent(key)}`;
            const body = { requests: [{ indexName: index, query: '', params: params }] };
            const r = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            return { status: r.status, data: await r.json().catch(() => null) };
        }
        """
        out = self._page.evaluate(script, ["45BWZJ1SGC", self._launch_key,
                                           "Launches_by_date_production", body_params])
        if out.get("status") != 200 or not out.get("data"):
            raise RuntimeError(f"Algolia launches query failed: {out}")
        return out["data"]["results"][0]["hits"]

    def search_companies(self, name: str, hits: int = 5) -> list[dict[str, Any]]:
        """Look up companies by name (used for early-detection cross-check)."""
        self.ensure_companies_page()
        params = "hitsPerPage=%d&query=%s" % (hits, name.replace(" ", "%20"))
        res = self._inpage_query("45BWZJ1SGC", self._company_key,
                                 "YCCompany_By_Launch_Date_production", params)
        return res["hits"]

    def close(self):
        try:
            self._browser.close()
            self._pw.stop()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
