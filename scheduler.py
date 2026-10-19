"""
scheduler.py
Runs daily award refresh jobs for NSF and NIH on a schedule using APScheduler.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

sys.path.insert(0, str(Path(__file__).parent))
from src.db import init_db, upsert_nsf_awards_batch, log_refresh_start, log_refresh_end
from scripts.nsf_api_fetcher import fetch_all, map_records
from scripts.nih_api_fetcher import fetch_all_by_date_range, map_record as nih_map_record
from scripts.fetch_grantsgov import fetch_and_save as grantsgov_fetch
from scripts.load_grantsgov import load_from_jsonl as grantsgov_load

# USASpending is intentionally not refreshed -- dropped as a data source
# (unreliable, not planned out). Only NSF + NIH going forward.

DAYS_BACK = 7  # trailing window -- NSF/NIH don't publish same-day, so a week covers the lag


def run_nsf_refresh():
    today = date.today()
    start = today - timedelta(days=DAYS_BACK)
    date_start = start.strftime("%m/%d/%Y")
    date_end   = today.strftime("%m/%d/%Y")

    print(f"[scheduler] Fetching NSF awards {date_start} → {date_end}", flush=True)
    init_db()
    log_id = log_refresh_start("nsf", details=f"{date_start} to {date_end}")

    try:
        raw_records = fetch_all(date_start, date_end)
        if not raw_records:
            print("[scheduler] NSF: No records returned.", flush=True)
            log_refresh_end(log_id, "success", records_fetched=0, records_upserted=0)
            return

        mapped = [row for r in raw_records if r.get("id") for row in map_records(r)]
        upsert_nsf_awards_batch(mapped)
        print(f"[scheduler] NSF done. Upserted {len(mapped)} records.", flush=True)
        log_refresh_end(log_id, "success", records_fetched=len(raw_records), records_upserted=len(mapped))
    except Exception as e:
        print(f"[scheduler] NSF refresh failed: {e}", flush=True)
        log_refresh_end(log_id, "error", error_message=str(e))
        raise


def run_nih_refresh():
    today = date.today()
    date_to   = today.strftime("%Y-%m-%d")
    date_from = (today - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    print(f"[scheduler] Fetching NIH awards {date_from} → {date_to}", flush=True)
    init_db()
    log_id = log_refresh_start("nih", details=f"{date_from} to {date_to}")

    try:
        raw_records = fetch_all_by_date_range(date_from, date_to)
        if not raw_records:
            print("[scheduler] NIH: No records returned.", flush=True)
            log_refresh_end(log_id, "success", records_fetched=0, records_upserted=0)
            return

        mapped = [nih_map_record(r) for r in raw_records if r.get("appl_id") is not None]
        upsert_nsf_awards_batch(mapped)
        print(f"[scheduler] NIH done. Upserted {len(mapped)} records.", flush=True)
        log_refresh_end(log_id, "success", records_fetched=len(raw_records), records_upserted=len(mapped))
    except Exception as e:
        print(f"[scheduler] NIH refresh failed: {e}", flush=True)
        log_refresh_end(log_id, "error", error_message=str(e))
        raise


def run_grantsgov_refresh():
    """Download today's full Grants.gov extract and upsert into opportunities.

    Unlike NSF/NIH/USASpending (rolling-window incremental APIs), Grants.gov
    publishes one complete daily snapshot. The load-time upsert always applies
    the incoming derived_status, so each run correctly transitions opportunities
    posted -> closed -> archived. A day missed (extract not yet posted at run
    time) self-heals on the next run because every extract is a full snapshot."""
    print("[scheduler] Fetching Grants.gov daily extract", flush=True)
    init_db()
    log_id = log_refresh_start("grantsgov", details=date.today().isoformat())

    try:
        jsonl_path = grantsgov_fetch()  # downloads today's extract -> JSONL, returns path
        read_count, skip_count, upserted_count = grantsgov_load(jsonl_path)
        print(f"[scheduler] Grants.gov done. Upserted {upserted_count} of {read_count} read.", flush=True)
        log_refresh_end(log_id, "success", records_fetched=read_count, records_upserted=upserted_count)
    except Exception as e:
        print(f"[scheduler] Grants.gov refresh failed: {e}", flush=True)
        log_refresh_end(log_id, "error", error_message=str(e))
        raise


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="UTC")
    # NSF refresh at 08:00 UTC
    scheduler.add_job(run_nsf_refresh, "cron", hour=8, minute=0)
    # NIH refresh at 08:05 UTC (5 min offset to avoid simultaneous DB writes)
    scheduler.add_job(run_nih_refresh, "cron", hour=8, minute=5)
    # Grants.gov refresh at 08:15 UTC (open/forecasted solicitations)
    scheduler.add_job(run_grantsgov_refresh, "cron", hour=8, minute=15)

    print("[scheduler] Starting. Will run NSF at 08:00, NIH at 08:05, Grants.gov at 08:15 UTC daily.", flush=True)
    print("[scheduler] Running NSF refresh now...", flush=True)
    run_nsf_refresh()
    print("[scheduler] Running NIH refresh now...", flush=True)
    run_nih_refresh()
    print("[scheduler] Running Grants.gov refresh now...", flush=True)
    run_grantsgov_refresh()

    scheduler.start()
