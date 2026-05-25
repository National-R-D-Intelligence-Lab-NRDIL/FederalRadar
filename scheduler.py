"""
scheduler.py
Runs the NSF daily award refresh on a schedule using APScheduler.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

sys.path.insert(0, str(Path(__file__).parent))
from src.db import init_db, upsert_nsf_awards_batch
from scripts.nsf_api_fetcher import fetch_all, map_record

DAYS_BACK = 2  # rolling window to catch weekends / late postings


def run_nsf_refresh():
    today = date.today()
    start = today - timedelta(days=DAYS_BACK)
    date_start = start.strftime("%m/%d/%Y")
    date_end   = today.strftime("%m/%d/%Y")

    print(f"[scheduler] Fetching NSF awards {date_start} → {date_end}", flush=True)
    init_db()

    raw_records = fetch_all(date_start, date_end)
    if not raw_records:
        print("[scheduler] No records returned.", flush=True)
        return

    mapped = [map_record(r) for r in raw_records if r.get("id")]
    upsert_nsf_awards_batch(mapped)
    print(f"[scheduler] Done. Upserted {len(mapped)} records.", flush=True)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_nsf_refresh, "cron", hour=8, minute=0)

    print("[scheduler] Starting. Will run daily at 08:00 UTC. Running once now...", flush=True)
    run_nsf_refresh()

    scheduler.start()
