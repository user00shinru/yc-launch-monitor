"""Pond Protocol V1 agent server exposing the YC monitor for review & health checks.

Endpoints:
  GET  /manifest          (public)     — agent description
  POST /runs              (Bearer key) — actions: health_check | latest_alerts | force_scan
  GET  /tasks/{task_id}   (Bearer key) — async task polling for force_scan
"""
from __future__ import annotations

import threading
import time
import uuid

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
import monitor
import state

app = FastAPI(title="YC Launch Monitor Agent", version="1.0.0")

AGENT_VERSION = "1.0.0"

MANIFEST = {
    "protocol": "marketplace-agent",
    "protocol_version": "1.0",
    "agent_version": AGENT_VERSION,
    "metadata": {
        "name": "YC Launch Monitor",
        "short_description": "Early detection of YC startups — monitors YC Directory, Launch YC, "
                             "X (Twitter) and LinkedIn for founder announcements before official listing.",
        "description": "<p>YC Launch Monitor is a persistent monitoring agent that watches 4 sources "
                       "for early-stage YC signals: the YC Directory, Launch YC posts, founder posts on "
                       "X (Twitter) and founder posts on LinkedIn.</p>"
                       "<p><b>Early detection:</b> when a founder announces a new company before YC lists "
                       "it officially, the monitor flags it as an early signal and cross-checks it against "
                       "the directory (in_directory flag).</p>"
                       "<p><b>Persistent &amp; stateful:</b> every company, launch and social post is stored "
                       "in SQLite — alerts never repeat on already-seen items, even across restarts.</p>"
                       "<p><b>Slack delivery:</b> real-time alerts include company name, batch, source, "
                       "description and a direct link.</p>",
        "category": "research",
        "key_features": "<ul><li>4-source monitoring: YC Directory, Launch YC, X, LinkedIn</li>"
                        "<li>Early-detection before official YC listing</li>"
                        "<li>Stateful SQLite store — zero duplicate alerts</li>"
                        "<li>Real-time Slack delivery</li></ul>",
        "use_cases": "<p>Find brand-new YC startups before they trend, catch early founder signals for "
                     "outreach or research, and monitor Speedrun launches.</p>",
        "setup_instructions": "No setup needed. Call health_check, latest_alerts or force_scan directly.",
        "developer_x_url": "https://x.com/destrogaming3",
        "faqs": [
            {"question": "Which sources does it monitor?",
             "answer": "<p>Four: YC Directory, Launch YC posts, X (Twitter) founder posts and LinkedIn "
                       "founder posts. Every alert tells you the exact source with a direct link.</p>"},
            {"question": "How does early detection work?",
             "answer": "<p>Founder announcement posts on X/LinkedIn are keyword-matched and cross-checked "
                       "against the official YC Directory. Posts about companies not yet listed are flagged "
                       "as early signals.</p>"},
            {"question": "Will it re-alert on companies I've already seen?",
             "answer": "<p>No. Every item is stored persistently and never re-alerted — across restarts.</p>"},
        ],
        "pricing_plans": [{"name": "Free Beta", "pricing_model": "pay_as_you_go", "amount_minor": 0,
                           "usage_quantity": 100, "usage_unit": "result",
                           "description": "Full access during beta.", "sort_order": 1}],
    },
    "actions": [
        {"id": "health_check", "name": "Health Check",
         "description": "Persistent monitor health: live counters, last scan result, tracked batches.",
         "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
        {"id": "latest_alerts", "name": "Latest Alerts",
         "description": "Most recent early + official detections.",
         "input_schema": {"type": "object",
                          "properties": {"limit": {"type": "integer",
                                                   "description": "How many alerts to return (default 10)."}},
                          "additionalProperties": False}},
        {"id": "force_scan", "name": "Force Scan",
         "description": "Trigger a full scan of all 4 sources now (async task).",
         "input_schema": {"type": "object",
                          "properties": {"lookback_hours": {"type": "number",
                                                            "description": "How far back to scan (default 24)."}},
                          "additionalProperties": False}},
    ],
    "capabilities": {"sync": True, "streaming": False, "async_tasks": True,
                     "cancellation": False, "attachments": False, "feedback": False},
    "input_modes": ["text/plain"],
    "output_modes": ["text/markdown"],
    "limits": {"max_request_bytes": 10485760, "max_attachment_bytes": 0, "max_run_seconds": 300},
}

KNOWN_ACTIONS = {a["id"] for a in MANIFEST["actions"]} | {a["name"] for a in MANIFEST["actions"]}

TASKS: dict[str, dict] = {}


def _fail(status: int, code: str, message: str):
    return JSONResponse(status_code=status,
                        content={"error": {"code": code, "message": message}})


def _auth(authorization: str = Header(default="")):
    # NB: a dependency that *returns* a Response does NOT abort the request in
    # FastAPI — raising HTTPException is what actually blocks execution.
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer access key")
    key = authorization.removeprefix("Bearer ").strip()
    if key != config.POND_ACCESS_KEY:
        raise HTTPException(status_code=401, detail="Invalid access key")


class RunRequest(BaseModel):
    action: str
    input: dict = Field(default_factory=dict)
    run_id: str | None = None


@app.get("/manifest")
def manifest():
    return MANIFEST


@app.post("/runs", status_code=202)
def runs(req: RunRequest, _=Depends(_auth)):
    if req.action not in KNOWN_ACTIONS:
        return _fail(400, "unsupported_action", f"Unknown action '{req.action}'")
    if req.action in ("health_check", "latest_alerts"):
        return JSONResponse(status_code=200, content=execute(req.action, req.input))
    task_id = str(uuid.uuid4())
    TASKS[task_id] = {"task_id": task_id, "status": "queued", "result": None}

    def _work():
        TASKS[task_id]["status"] = "running"
        try:
            TASKS[task_id]["result"] = execute("force_scan", req.input)
            TASKS[task_id]["status"] = "completed"
        except Exception as e:  # pragma: no cover
            TASKS[task_id] = {"task_id": task_id, "status": "failed",
                              "result": {"error": str(e)}}
    threading.Thread(target=_work, daemon=True).start()
    return {"task_id": task_id, "status": "queued"}


@app.get("/tasks/{task_id}")
def get_task(task_id: str, _=Depends(_auth)):
    if task_id not in TASKS:
        return _fail(404, "task_not_found", "Unknown task id")
    return TASKS[task_id]


def execute(action: str, inp: dict) -> dict:
    if action == "health_check":
        last = state.get_meta("last_cycle")
        import json as _json
        last = _json.loads(last) if last else None
        return {
            "status": "healthy" if last and last.get("ok") else "degraded",
            "last_cycle": last,
            "counters": {
                "companies_tracked": state.count("company"),
                "launches_tracked": state.count("launch"),
                "social_posts_tracked": state.count("social_post"),
                "alerts_sent": state.alert_count(),
            },
            "poll_interval_hours": config.POLL_INTERVAL_HOURS,
            "batches": config.CURRENT_BATCHES,
        }
    if action == "latest_alerts":
        limit = int(inp.get("limit", 10))
        return {"alerts": state.recent_alerts(limit), "count": state.alert_count()}
    if action == "force_scan":
        t0 = time.time()
        res = monitor.run_cycle(alert=False,
                                lookback_hours=float(inp.get("lookback_hours", 24)))
        res["duration_s"] = round(time.time() - t0, 1)
        return {"scan": {k: v for k, v in res.items() if k != "errors"},
                "ok": res["ok"], "errors": res.get("errors", [])}
    return {"error": "unknown action"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.AGENT_PORT)
