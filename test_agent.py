"""E2E test of the Pond agent server (run while agent_server.py is up)."""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8001"
KEY = "test-key-123"


def req(method: str, path: str, body: dict | None = None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Authorization", f"Bearer {KEY}")
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, data=data, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


# 1. force_scan async
st, res = req("POST", "/runs", {"action": "force_scan", "input": {"lookback_hours": 24}})
print("force_scan submit:", st, res.get("status"), "task:", res.get("task_id"))
tid = res["task_id"]

# 2. poll up to 150s
for i in range(30):
    time.sleep(5)
    st, t = req("GET", f"/tasks/{tid}")
    print(f"  poll {i+1}: {t['status']}")
    if t["status"] in ("completed", "failed"):
        break

r = t.get("result") or {}
print("scan ok:", r.get("ok"))
print("yc stats:", json.dumps((r.get("scan") or {}).get("yc")))
print("social stats:", json.dumps((r.get("scan") or {}).get("social")))

# 3. latest_alerts
st, la = req("POST", "/runs", {"action": "latest_alerts", "input": {"limit": 5}})
print("latest_alerts:", st, "count:", la.get("count"))
