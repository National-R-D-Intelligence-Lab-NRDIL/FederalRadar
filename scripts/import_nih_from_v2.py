"""
import_nih_from_v2.py
Loads NIH raw_json records (exported from Federal Radar V2's validated
raw_nih_awards table, one JSON object per line) into federal_awards.db.

Grain: one row per award PER FISCAL YEAR, keyed on appl_id -- NIH's API
already returns one record per award-year, no unnesting needed (unlike
NSF's oblg_fy). award_amount is already that year's own amount, not a
lifetime total, so no "take higher" trap here either.
"""

import argparse
import json
import sqlite3
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_awards_batch, DB_PATH

RAW_FILE = Path(__file__).parent.parent / "data" / "raw" / "nih_v2_export.jsonl"
BATCH_SIZE = 500


def map_record(rec: dict) -> dict | None:
    appl_id = rec.get("appl_id")
    if appl_id is None:
        return None
    fiscal_year = rec.get("fiscal_year")
    if fiscal_year is None:
        return None

    org = rec.get("organization") or {}
    ic_admin = rec.get("agency_ic_admin") or {}

    try:
        awd_amount = float(rec["award_amount"]) if rec.get("award_amount") is not None else None
    except (TypeError, ValueError):
        awd_amount = None
    try:
        direct_cost_amt = float(rec["direct_cost_amt"]) if rec.get("direct_cost_amt") is not None else None
    except (TypeError, ValueError):
        direct_cost_amt = None

    return {
        "awd_id":                 str(appl_id),
        "awd_titl_txt":           rec.get("project_title") or "(untitled)",
        "inst_name":              org.get("org_name"),
        "inst_state_code":        org.get("org_state"),
        "awd_amount":             awd_amount,
        "obligation_date":        rec.get("award_notice_date"),
        "project_start_date":     rec.get("project_start_date"),
        "project_end_date":       rec.get("project_end_date"),
        "awd_abstract_narration": rec.get("abstract_text"),
        "dir_abbr":               None,
        "div_abbr":               None,
        "pgm_ele_name":           None,
        "pi_name":                rec.get("contact_pi_name"),
        "agcy_id":                rec.get("agency_code"),
        "fiscal_year":            int(fiscal_year),
        "raw_json":               json.dumps(rec),
        "source":                 "nih",
        "opportunity_number":     None,
        "activity_code":          rec.get("activity_code"),
        "nih_institute":          ic_admin.get("abbreviation"),
        "direct_cost_amt":        direct_cost_amt,
    }


def run(fy_min: int | None, fy_max: int | None):
    if not RAW_FILE.exists():
        print(f"ERROR: {RAW_FILE} not found.")
        return

    init_db()

    conn = sqlite3.connect(DB_PATH)
    existing_keys = set(
        (row[0], row[1])
        for row in conn.execute("SELECT awd_id, fiscal_year FROM awards WHERE source = 'nih'").fetchall()
    )
    conn.close()

    stats = {"total": 0, "inserted": 0, "updated": 0, "skipped_fy": 0, "skipped_bad": 0}
    batch = []

    with open(RAW_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped_bad"] += 1
                continue

            record = map_record(rec)
            if record is None:
                stats["skipped_bad"] += 1
                continue
            if fy_min is not None and record["fiscal_year"] < fy_min:
                stats["skipped_fy"] += 1
                continue
            if fy_max is not None and record["fiscal_year"] > fy_max:
                stats["skipped_fy"] += 1
                continue

            key = (record["awd_id"], record["fiscal_year"])
            is_update = key in existing_keys
            batch.append(record)

            stats["total"] += 1
            if is_update:
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
                existing_keys.add(key)

            if len(batch) >= BATCH_SIZE:
                upsert_nsf_awards_batch(batch)
                batch.clear()

            if stats["total"] % 20000 == 0:
                print(f"  processed={stats['total']:,}  inserted={stats['inserted']:,}  updated={stats['updated']:,}")

    if batch:
        upsert_nsf_awards_batch(batch)

    print("\n" + "=" * 50)
    print("FINAL SUMMARY")
    print("=" * 50)
    for k, v in stats.items():
        print(f"  {k:12s}: {v:,}")

    conn = sqlite3.connect(DB_PATH)
    print("\nSELECT fiscal_year, COUNT(*), ROUND(SUM(awd_amount)/1e6,1) FROM awards WHERE source='nih' GROUP BY fiscal_year ORDER BY fiscal_year;")
    for row in conn.execute("""
        SELECT fiscal_year, COUNT(*) AS awards, ROUND(SUM(awd_amount)/1000000.0, 1) AS total_millions
        FROM awards WHERE source = 'nih' GROUP BY fiscal_year ORDER BY fiscal_year
    """):
        fy, awards, total_m = row
        print(f"  {str(fy):>12}  {awards:>8,}  {(total_m or 0.0):>14.1f}M")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fy-min", type=int, default=None)
    parser.add_argument("--fy-max", type=int, default=None)
    args = parser.parse_args()
    run(args.fy_min, args.fy_max)
