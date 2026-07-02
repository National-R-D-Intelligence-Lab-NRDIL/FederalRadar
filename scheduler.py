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
from scripts.nsf_api_fetcher import fetch_all, map_record
from scripts.nih_api_fetcher import fetch_all_by_date_range, map_record as nih_map_record
from scripts.usaspending_api_fetcher import fetch_incremental, map_record_from_search, validate_record

DAYS_BACK = 2  # rolling window to catch weekends / late postings


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

        mapped = [map_record(r) for r in raw_records if r.get("id")]
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

        mapped = [nih_map_record(r) for r in raw_records if r.get("project_num")]
        upsert_nsf_awards_batch(mapped)
        print(f"[scheduler] NIH done. Upserted {len(mapped)} records.", flush=True)
        log_refresh_end(log_id, "success", records_fetched=len(raw_records), records_upserted=len(mapped))
    except Exception as e:
        print(f"[scheduler] NIH refresh failed: {e}", flush=True)
        log_refresh_end(log_id, "error", error_message=str(e))
        raise


def run_usaspending_refresh():
    """Incremental refresh for DOE, NASA, DOD, USDA, EPA, DHS, Commerce, ED,
    DOT, HHS, NEH via the synchronous Advanced Search API — small rolling
    date window, one paginated call across all agencies. No ZIP/job/poll."""
    today = date.today()
    date_to   = today.strftime("%Y-%m-%d")
    date_from = (today - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")

    print(f"[scheduler] Fetching USASpending awards {date_from} → {date_to}", flush=True)
    init_db()
    log_id = log_refresh_start("usaspending", details=f"{date_from} to {date_to}")

    try:
        raw_records = fetch_incremental(date_from, date_to)
        if not raw_records:
            print("[scheduler] USASpending: No records returned.", flush=True)
            log_refresh_end(log_id, "success", records_fetched=0, records_upserted=0)
            return

        mapped = []
        for r in raw_records:
            rec = map_record_from_search(r)
            if rec is None:
                continue
            ok, _ = validate_record(rec)
            if ok:
                mapped.append(rec)

        upsert_nsf_awards_batch(mapped)
        print(f"[scheduler] USASpending done. Upserted {len(mapped)} records.", flush=True)
        log_refresh_end(log_id, "success", records_fetched=len(raw_records), records_upserted=len(mapped))
    except Exception as e:
        print(f"[scheduler] USASpending refresh failed: {e}", flush=True)
        log_refresh_end(log_id, "error", error_message=str(e))
        raise


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="UTC")
    # NSF refresh at 08:00 UTC
    scheduler.add_job(run_nsf_refresh, "cron", hour=8, minute=0)
    # NIH refresh at 08:05 UTC (5 min offset to avoid simultaneous DB writes)
    scheduler.add_job(run_nih_refresh, "cron", hour=8, minute=5)
    # USASpending refresh at 08:10 UTC (DOE, NASA, DOD, USDA, EPA, DHS, Commerce, ED, DOT, HHS, NEH)
    scheduler.add_job(run_usaspending_refresh, "cron", hour=8, minute=10)

    print("[scheduler] Starting. Will run NSF at 08:00, NIH at 08:05, USASpending at 08:10 UTC daily.", flush=True)
    print("[scheduler] Running NSF refresh now...", flush=True)
    run_nsf_refresh()
    print("[scheduler] Running NIH refresh now...", flush=True)
    run_nih_refresh()
    print("[scheduler] Running USASpending refresh now...", flush=True)
    run_usaspending_refresh()

    scheduler.start()
