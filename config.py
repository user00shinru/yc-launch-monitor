"""Configuration — loaded from environment / .env file."""
import os
import sys
from pathlib import Path

# Load .env manually (no python-dotenv dependency needed)
def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_env()

# --- Slack ---
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN", "")       # xoxb-...
SLACK_ALERT_CHANNEL = os.environ.get("SLACK_ALERT_CHANNEL", "")  # channel ID or name
SLACK_EARLY_CHANNEL = os.environ.get("SLACK_EARLY_CHANNEL", "")  # optional separate channel for early signals; falls back to ALERT channel

# --- Monitoring ---
POLL_INTERVAL_HOURS = float(os.environ.get("POLL_INTERVAL_HOURS", "8"))
LOOKBACK_HOURS = float(os.environ.get("LOOKBACK_HOURS", "24"))   # first-run backfill window
DB_PATH = os.environ.get("YC_MONITOR_DB", str(Path(__file__).parent / "data" / "seen.db"))

# --- Pond agent server ---
POND_ACCESS_KEY = os.environ.get("POND_ACCESS_KEY", "change-me")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8001"))

# --- Early-detection keywords (X + LinkedIn) ---
EARLY_KEYWORDS = [
    "got into yc", "accepted to yc", "accepted into yc", "we're in yc",
    "we are in yc", "excited to share we", "yc s2", "yc w2", "yc f2",
    "yc su2", "speedrun batch", "y combinator s2", "y combinator w2",
    "backed by y combinator", "ycombinator.com", "joining yc", "@ycombinator",
]
# Batches we track (current cycle). Speedrun is its own sub-program.
CURRENT_BATCHES = [b.strip() for b in os.environ.get(
    "CURRENT_BATCHES", "Summer 2026,Fall 2026,Winter 2027").split(",") if b.strip()]

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def die_if_missing(need_slack: bool = True):
    missing = []
    if need_slack and not SLACK_BOT_TOKEN:
        missing.append("SLACK_BOT_TOKEN")
    if need_slack and not SLACK_ALERT_CHANNEL:
        missing.append("SLACK_ALERT_CHANNEL")
    if missing:
        print("Missing required env vars: " + ", ".join(missing))
        print("Copy .env.example to .env and fill them in. See README.md")
        sys.exit(1)
