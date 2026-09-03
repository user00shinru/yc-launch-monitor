import json, os, urllib.request, urllib.error, uuid as _u, time as _t

BASE = "http://127.0.0.1:8001"
KEY = os.environ.get("KEY", "")
ok = fail = 0

def req(method, path, body=None, headers=None, expect=None, label=""):
    global ok, fail
    h = {"Content-Type": "application/json"}
    h.update({k: v for k, v in (headers or {}).items() if v is not None})
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            code, payload = resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        code, payload = e.code, json.loads(e.read().decode())
    verdict = "PASS" if (expect is None or code == expect) else f"FAIL(exp {expect})"
    ok, fail = ok + (verdict == "PASS"), fail + (verdict != "PASS")
    print(f"[{verdict}] {label or (method + ' ' + path)} -> {code}: {str(payload)[:80]}")
    return code, payload

H = {"Authorization": f"Bearer {KEY}", "X-Agent-Protocol-Version": "1.0"}
uh = lambda: _u.uuid4().hex[:8]

def run_body(action=None, deadline_ms=120000):
    return {"run_id": f"run-{uh()}", "agent_id": "yc-launch-monitor",
            "conversation_id": "conv-1", "history_truncated": False,
            "action_id": action, "user": {"id": "u1", "locale": "en", "timezone": "UTC"},
            "messages": [{"id": "m1", "role": "user", "created_at": "2026-09-03T00:00:00Z",
                          "parts": [{"type": "text", "text": "give me latest alerts"}]}],
            "parameters": {"limit": 3},
            "execution": {"accepted_output_modes": ["text/markdown"], "deadline_ms": deadline_ms}}

c, p = req("GET", "/manifest", expect=200, label="1 manifest anonymous")
assert p["protocol_version"] == "1.0" and p["agent_version"] == "1.1.0"
req("POST", "/runs", body={}, expect=401, label="2 runs no auth")
req("POST", "/runs", body={}, headers={"Authorization": "Bearer wrong"}, expect=401, label="3 runs bad key")
req("POST", "/runs", body=run_body(), headers={"Authorization": f"Bearer {KEY}"}, expect=400, label="4 no protocol header")
req("POST", "/runs", body=run_body(), headers={**H, "X-Agent-Protocol-Version": "2.0"}, expect=400, label="5 bad version")
b = run_body("health_check")
req("POST", "/runs", body=b, headers={**H, "Idempotency-Key": "mismatch"}, expect=400, label="6 idempotency mismatch")
bb = run_body("nope")
req("POST", "/runs", body=bb, headers={**H, "Idempotency-Key": uh()}, expect=400, label="7a unknown action (bad key)")
bb2 = run_body("nope")
req("POST", "/runs", body=bb2, headers={**H, "Idempotency-Key": bb2["run_id"]}, expect=400, label="7b unknown action")
bb3 = run_body("health_check", deadline_ms=99999999)
req("POST", "/runs", body=bb3, headers={**H, "Idempotency-Key": bb3["run_id"]}, expect=400, label="8 deadline exceed")
req("POST", "/runs", body={"garbage": True}, headers=H, expect=400, label="9 malformed body Pond shape")

b = run_body("health_check")
c, p = req("POST", "/runs", body=b, headers={**H, "Idempotency-Key": b["run_id"]}, expect=202, label="10 health_check -> 202")
tid = p["task_id"]
for _ in range(20):
    _t.sleep(1)
    _, p2 = req("GET", f"/tasks/{tid}", headers=H, label="11 poll")
    if p2.get("status") in ("completed", "failed"):
        break
assert p2["status"] == "completed", p2
assert p2["usage"]["unit_of_measurement"] == "result" and p2["usage"]["quantity"] >= 1
assert "YC Launch Monitor" in p2["output"][0]["text"]
c3, p3 = req("POST", "/runs", body=b, headers={**H, "Idempotency-Key": b["run_id"]}, label="12 replay run_id")
assert p3.get("status") == "completed"

b2 = run_body(None)
c4, p4 = req("POST", "/runs", body=b2, headers={**H, "Idempotency-Key": b2["run_id"]}, expect=202, label="13 default action -> 202")
for _ in range(15):
    _t.sleep(1)
    _, p5 = req("GET", f"/tasks/{p4['task_id']}", headers=H, label="14 poll")
    if p5.get("status") in ("completed", "failed"):
        break
assert p5["status"] == "completed", p5

req("GET", "/tasks/task_nonexistent", headers=H, expect=404, label="15 unknown task")
print(f"\n=== RESULT: {ok} passed, {fail} failed ===")
