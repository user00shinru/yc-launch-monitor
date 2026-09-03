#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YC Launch Monitor — Pond Protocol V1 agent server (full spec).

Endpoints:
  GET  /manifest            (public, no auth)  — agent discovery
  POST /runs                (auth)             — execute one prepared run
  GET  /tasks/{task_id}     (auth)             — poll async task result

Auth:  Authorization: Bearer <POND_ACCESS_KEY>
       X-Agent-Protocol-Version: 1.0
Idempotency: Idempotency-Key header must equal body run_id.
Usage: every terminal result carries cumulative usage (unit = result).
Actions: health_check | latest_alerts | force_scan (default when action_id is None).
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
import monitor
import state

ACCESS_KEY = os.environ.get("POND_ACCESS_KEY", "") or getattr(config, "POND_ACCESS_KEY", "")
AGENT_VERSION = os.environ.get("POND_AGENT_VERSION", "1.1.0")
MAX_RUN_SECONDS = 300

app = FastAPI(title="YC Launch Monitor Agent", docs_url=None, redoc_url=None, openapi_url=None)

_store: dict[str, dict] = {}   # run_id -> terminal result
_tasks: dict[str, dict] = {}   # task_id -> task record
_pool = ThreadPoolExecutor(max_workers=8)
_usage_lock = threading.Lock()
_cumulative_runs = 0

ACTIONS = ("health_check", "latest_alerts", "force_scan")

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
    "limits": {"max_request_bytes": 10485760, "max_attachment_bytes": 0, "max_run_seconds": MAX_RUN_SECONDS},
}


# ─────────────────────────────────────────────────────────────
# Pydantic models (Pond Protocol V1 run body)
# ─────────────────────────────────────────────────────────────
class TextPart(BaseModel):
    type: str = "text"
    text: str = Field(min_length=1)


class Message(BaseModel):
    id: str
    role: str = "user"
    created_at: str
    parts: list


class UserInfo(BaseModel):
    id: str
    locale: str
    timezone: str


class Execution(BaseModel):
    accepted_output_modes: list[str]
    deadline_ms: int


class RunRequest(BaseModel):
    run_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    history_truncated: bool
    action_id: str | None = None
    user: UserInfo
    messages: list[Message]
    parameters: dict
    execution: Execution


# ─────────────────────────────────────────────────────────────
# Auth (raise, never return — returning a Response does NOT abort)
# ─────────────────────────────────────────────────────────────
def authenticate_pond(
    authorization: str | None = Header(default=None),
    pond_version: str | None = Header(default=None, alias="X-Agent-Protocol-Version"),
):
    if authorization != f"Bearer {ACCESS_KEY}":
        raise HTTPException(status_code=401, detail={
            "code": "unauthorized",
            "message": "The Access Key is missing or invalid.",
        })
    if pond_version is None or not re.fullmatch(r"\d+\.\d+", pond_version):
        raise HTTPException(status_code=400, detail={
            "code": "invalid_request",
            "message": "X-Agent-Protocol-Version must be Major.Minor, e.g. 1.0.",
        })
    if pond_version != "1.0":
        raise HTTPException(status_code=400, detail={
            "code": "unsupported_protocol_version",
            "message": f"Version {pond_version} not supported.",
        })


def _fail(status: int, code: str, message: str):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


# Every response must be Pond-shaped — FastAPI's default {"detail": ...}
# validation errors (422) and bare 500s read as "non-Pond responses".
from fastapi.exceptions import RequestValidationError  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402


@app.exception_handler(RequestValidationError)
async def _validation_handler(request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    msg = f"Invalid request field '{loc}': {first.get('msg', 'validation error')}" if loc else "Invalid request body."
    return _fail(400, "invalid_request", msg)


@app.exception_handler(StarletteHTTPException)
async def _http_handler(request, exc: StarletteHTTPException):
    # HTTPExceptions raised with dict detail (auth) already carry Pond shape.
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    return _fail(exc.status_code, "invalid_request", str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled_handler(request, exc: Exception):
    return _fail(500, "internal_error", "Unexpected server error.")


# ─────────────────────────────────────────────────────────────
# Action implementations — return (markdown, error)
# ─────────────────────────────────────────────────────────────
def run_action(action_id: str, prompt: str, params: dict) -> tuple[str | None, str | None]:
    if action_id == "health_check":
        import json as _json
        last = state.get_meta("last_cycle")
        last = _json.loads(last) if last else None
        c = {
            "companies_tracked": state.count("company"),
            "launches_tracked": state.count("launch"),
            "social_posts_tracked": state.count("social_post"),
            "alerts_sent": state.alert_count(),
        }
        status = "healthy" if last and last.get("ok") else "degraded"
        md = (
            f"## YC Launch Monitor — Health\n\n"
            f"- **Status**: {status}\n"
            f"- **Companies tracked**: {c['companies_tracked']}\n"
            f"- **Launches tracked**: {c['launches_tracked']}\n"
            f"- **Social posts tracked**: {c['social_posts_tracked']}\n"
            f"- **Alerts sent**: {c['alerts_sent']}\n"
            f"- **Poll interval**: every {config.POLL_INTERVAL_HOURS}h\n"
            f"- **Batches watched**: {', '.join(config.CURRENT_BATCHES)}\n"
            f"- **Last cycle**: {'ok' if last and last.get('ok') else 'pending/degraded'}\n"
        )
        return md, None

    if action_id == "latest_alerts":
        try:
            limit = max(1, min(50, int(params.get("limit", 10))))
        except Exception:
            limit = 10
        alerts = state.recent_alerts(limit)
        md = f"## Latest alerts ({len(alerts)} shown, {state.alert_count()} total)\n\n"
        for a in alerts:
            md += f"- **{a.get('name', '?')}** ({a.get('batch', '?')}) — {a.get('source', '?')} — {a.get('link', '')}\n"
        if not alerts:
            md += "_No alerts recorded yet._\n"
        return md, None

    if action_id == "force_scan":
        t0 = time.time()
        res = monitor.run_cycle(alert=False,
                                lookback_hours=float(params.get("lookback_hours", 24)))
        dur = round(time.time() - t0, 1)
        md = (
            f"## Force scan complete\n\n"
            f"- **OK**: {res.get('ok')}\n"
            f"- **Duration**: {dur}s\n"
            f"- **New companies**: {res.get('new_companies', res.get('companies', '?'))}\n"
            f"- **New launches**: {res.get('new_launches', res.get('launches', '?'))}\n"
            f"- **New social posts**: {res.get('new_social', res.get('social', '?'))}\n"
        )
        return md, None

    return None, f"Action {action_id} is not supported."


# ─────────────────────────────────────────────────────────────
# /runs — ALWAYS async: 202 queued, poll /tasks/{task_id}
# ─────────────────────────────────────────────────────────────
@app.post("/runs", dependencies=[Depends(authenticate_pond)])
async def create_run(run: RunRequest,
                     idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if idempotency_key != run.run_id:
        return _fail(400, "invalid_request", "Idempotency-Key must match run_id.")

    # Idempotent replay of a finished run
    saved = _store.get(run.run_id)
    if saved is not None:
        return JSONResponse(content=saved)
    for tid, trec in _tasks.items():
        if trec.get("run_id") == run.run_id:
            return JSONResponse(status_code=202, content={
                "run_id": run.run_id, "task_id": tid, "status": trec.get("status", "queued"),
                "poll_after_ms": trec.get("poll_after_ms", 2000),
            })

    action = run.action_id
    if action is None:
        # Pond chat sends the free prompt without action_id → default action
        action = "latest_alerts"
    elif action not in ACTIONS:
        # also accept display names
        display = {"health check": "health_check", "latest alerts": "latest_alerts",
                   "force scan": "force_scan"}
        action = display.get(action.lower())
        if action is None:
            return _fail(400, "unsupported_operation", f"Action {run.action_id} is not supported.")

    if run.execution.deadline_ms > MAX_RUN_SECONDS * 1000:
        return _fail(400, "invalid_request", "deadline_ms exceeds limits.max_run_seconds.")

    prompt = ""
    for msg in run.messages:
        for part in msg.parts:
            if isinstance(part, dict) and part.get("type") == "text":
                prompt += part.get("text", "") + "\n"

    task_id = "task_" + uuid.uuid4().hex[:12]

    def _work():
        global _cumulative_runs
        _tasks[task_id]["status"] = "running"
        try:
            md, err = run_action(action, prompt, run.parameters)
        except Exception as ex:  # pragma: no cover
            md, err = None, str(ex)
        with _usage_lock:
            _cumulative_runs += 1
            quantity = _cumulative_runs
        if err is not None:
            terminal = {
                "run_id": run.run_id, "status": "failed",
                "error": {"code": "execution_failed", "message": err},
                "usage": {"unit_of_measurement": "result", "quantity": quantity},
            }
        else:
            terminal = {
                "run_id": run.run_id, "status": "completed",
                "output": [{"type": "text", "text": md}],
                "usage": {"unit_of_measurement": "result", "quantity": quantity},
            }
        _store[run.run_id] = terminal
        _tasks[task_id] = {"run_id": run.run_id, "status": terminal["status"], **terminal}

    _tasks[task_id] = {"run_id": run.run_id, "status": "queued", "poll_after_ms": 2000}
    _pool.submit(_work)
    return JSONResponse(status_code=202, content={
        "run_id": run.run_id, "task_id": task_id, "status": "queued", "poll_after_ms": 2000,
    })


# ─────────────────────────────────────────────────────────────
# /tasks/{task_id} — poll
# ─────────────────────────────────────────────────────────────
@app.get("/tasks/{task_id}", dependencies=[Depends(authenticate_pond)])
def get_task(task_id: str):
    trec = _tasks.get(task_id)
    if trec is None:
        return _fail(404, "task_not_found", "The task does not exist or is inaccessible.")
    body = {
        "run_id": trec["run_id"], "task_id": task_id,
        "status": trec.get("status"),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if trec.get("status") in ("completed", "failed", "expired"):
        for k in ("output", "error", "usage"):
            if k in trec:
                body[k] = trec[k]
    return JSONResponse(content=body)


@app.get("/health")
def health():
    return {"status": "ok", "runs_completed": _cumulative_runs}


@app.get("/manifest")
def manifest():
    return MANIFEST


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", str(getattr(config, "AGENT_PORT", 8001)))))
