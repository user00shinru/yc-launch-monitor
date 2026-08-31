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

MANIFEST = {
    "protocol": "marketplace-agent",
    "protocol_versi": "1.0",
    "metadata": {
        "agent_id": "yc-launch-monitor",
        "name": "YC Launch Monitor",
        "description": "Monitors Y Combinator directory, Launch YC posts, X (Twitter) "
                       "and LinkedIn for new YC/Speedrun company announcements. Supports "
                       "early-detection of founder announcements before official listing, "
                       "and reports persistent monitor health.",
        "version": "1.0.0",
        "developer": "YC Monitor Bot",
        "capabilities": ["yc-directory", "launch-yc", "twitter-x", "linkedin", "early-detection"],
    },
    "actions": [
        {"name": "health_check", "description": "Persistent monitor health + counters",
         "inputs": {}, "outputs": {"type": "text"}},
        {"name": "latest_alerts", "description": "Recent detections (early + official)",
         "inputs": {"limit": {"type": "integer", "required": False, "default": 10}},
         "outputs": {"type": "text"}},
        {"name": "force_scan", "description": "Trigger a full scan of all 4 sources now "
                                              "(async task)",
         "inputs": {"lookback_hours": {"type": "number", "required": False, "default": 24}},
         "outputs": {"type": "text"}},
    ],
}

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
    if req.action not in {a["name"] for a in MANIFEST["actions"]}:
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
