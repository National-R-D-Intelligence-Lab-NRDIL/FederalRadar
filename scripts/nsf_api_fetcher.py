"""
nsf_api_fetcher.py
Fetches recent NSF awards from the public API and upserts them into federal_awards.db.
"""

import argparse
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_awards_batch, DB_PATH

BASE_URL = "https://api.nsf.gov/services/v1/awards.json"
PRINT_FIELDS = (
    "id,title,awardeeName,awardeeStateCode,fundsObligatedAmt,"
    "date,startDate,expDate,abstractText,dirAbbr,divAbbr,fundProgramName,pdPIName"
)
RPP = 25


def date_to_iso(mmddyyyy: str) -> str | None:
    """Convert MM/DD/YYYY to YYYY-MM-DD. Returns None if blank/unparseable."""
    try:
        m, d, y = mmddyyyy.strip().split("/")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        return None


def map_record(rec: dict) -> dict:
    raw_date = rec.get("date") or ""
    iso_date = date_to_iso(raw_date)
    try:
        parts = raw_date.strip().split("/")
        month = int(parts[0])
        year  = int(parts[2])
        fiscal_year = year + 1 if month >= 10 else year
    except Exception:
        fiscal_year = None

    try:
        awd_amount = float(rec["fundsObligatedAmt"]) if rec.get("fundsObligatedAmt") not in (None, "") else None
    except (TypeError, ValueError):
        awd_amount = None

    return {
        "awd_id":                 rec.get("id"),
        "awd_titl_txt":           rec.get("title"),
        "inst_name":              rec.get("awardeeName"),
        "inst_state_code":        rec.get("awardeeStateCode"),
        "awd_amount":             awd_amount,
        "obligation_date":        iso_date,
        "project_start_date":     date_to_iso(rec.get("startDate") or ""),
        "project_end_date":       date_to_iso(rec.get("expDate") or ""),
        "awd_abstract_narration": rec.get("abstractText"),
        "dir_abbr":               rec.get("dirAbbr"),
        "div_abbr":               rec.get("divAbbr"),
        "pgm_ele_name":           rec.get("fundProgramName"),
        "pi_name":                rec.get("pdPIName"),
        "agcy_id":                None,
        "fiscal_year":            fiscal_year,
        "raw_json":               json.dumps(rec),
    }


def fetch_by_id(award_id: str) -> dict | None:
    params = urllib.parse.urlencode({"id": award_id, "printFields": PRINT_FIELDS})
    url = f"{BASE_URL}?{params}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    awards = data.get("response", {}).get("award") or []
    return awards[0] if awards else None


def fetch_db_row(awd_id: str) -> dict | None:
    COLUMNS = [
        "awd_id", "awd_titl_txt", "inst_name", "inst_state_code",
        "awd_amount", "obligation_date", "project_start_date", "project_end_date",
        "awd_abstract_narration", "dir_abbr", "div_abbr", "pgm_ele_name",
        "pi_name", "agcy_id", "fiscal_year", "raw_json",
    ]
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM nsf_awards WHERE awd_id = ?", (awd_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(zip(COLUMNS, row))


def run_test():
    TEST_IDS = ["2531827", "2552363"]
    COMPARE_COLS = [
        "awd_id", "awd_titl_txt", "inst_name", "inst_state_code",
        "awd_amount", "obligation_date", "project_start_date", "project_end_date",
        "dir_abbr", "div_abbr", "pgm_ele_name", "pi_name", "fiscal_year",
    ]
    COL_W, VAL_W = 22, 45

    for award_id in TEST_IDS:
        print(f"\n{'='*100}")
        print(f"Award ID: {award_id}")
        print(f"{'='*100}")

        raw = fetch_by_id(award_id)
        if raw is None:
            print("  Not found in API.")
            continue
        api_rec = map_record(raw)

        db_rec = fetch_db_row(award_id)
        if db_rec is None:
            print("  Not found in DB (not yet loaded from ZIP).")
            db_rec = {}

        header = f"  {'COLUMN':<{COL_W}}  {'API VALUE':<{VAL_W}}  {'DB VALUE':<{VAL_W}}  STATUS"
        print(header)
        print("  " + "-" * (COL_W + VAL_W * 2 + 14))

        for col in COMPARE_COLS:
            api_val = api_rec.get(col)
            db_val  = db_rec.get(col)

            # truncate for display
            api_str = str(api_val)[:VAL_W] if api_val is not None else "NULL"
            db_str  = str(db_val)[:VAL_W]  if db_val  is not None else "NULL"

            match = api_val == db_val
            status = "OK" if match else "MISMATCH <<<"
            print(f"  {col:<{COL_W}}  {api_str:<{VAL_W}}  {db_str:<{VAL_W}}  {status}")


def run_compare():
    COMPARE_IDS = ["2618799", "2543389", "2550221", "2541022", "2544114"]
    COMPARE_COLS = [
        "awd_id", "inst_name", "awd_amount",
        "obligation_date", "project_start_date", "project_end_date",
        "fiscal_year", "pi_name", "dir_abbr", "div_abbr",
    ]
    DB_COLS = ", ".join(COMPARE_COLS)
    COL_W, VAL_W = 22, 42

    conn = sqlite3.connect(DB_PATH)

    for award_id in COMPARE_IDS:
        print(f"\n{'='*98}")
        print(f"Award ID: {award_id}")
        print(f"{'='*98}")

        raw = fetch_by_id(award_id)
        if raw is None:
            print("  Not found in API.")
            continue

        # map API response to compare fields
        raw_date  = raw.get("date") or ""
        try:
            api_amount = float(raw["fundsObligatedAmt"]) if raw.get("fundsObligatedAmt") not in (None, "") else None
        except (TypeError, ValueError):
            api_amount = None
        try:
            parts = raw_date.strip().split("/")
            month = int(parts[0])
            year  = int(parts[2])
            api_fiscal_year = year + 1 if month >= 10 else year
        except Exception:
            api_fiscal_year = None

        api_rec = {
            "awd_id":             raw.get("id"),
            "inst_name":          raw.get("awardeeName"),
            "awd_amount":         api_amount,
            "obligation_date":    date_to_iso(raw_date),
            "project_start_date": date_to_iso(raw.get("startDate") or ""),
            "project_end_date":   date_to_iso(raw.get("expDate") or ""),
            "fiscal_year":        api_fiscal_year,
            "pi_name":            raw.get("pdPIName"),
            "dir_abbr":           raw.get("dirAbbr"),
            "div_abbr":           raw.get("divAbbr"),
        }

        row = conn.execute(
            f"SELECT {DB_COLS} FROM nsf_awards WHERE awd_id = ?", (award_id,)
        ).fetchone()
        db_rec = dict(zip(COMPARE_COLS, row)) if row else {}

        if not row:
            print("  Not found in DB.")

        print(f"  {'FIELD':<{COL_W}}  {'ZIP VALUE':<{VAL_W}}  {'API VALUE':<{VAL_W}}  MATCH")
        print("  " + "-" * (COL_W + VAL_W * 2 + 10))

        for col in COMPARE_COLS:
            zip_val = db_rec.get(col)
            api_val = api_rec.get(col)

            zip_str = str(zip_val)[:VAL_W] if zip_val is not None else "NULL"
            api_str = str(api_val)[:VAL_W] if api_val is not None else "NULL"

            match = zip_val == api_val
            status = "YES" if match else "NO <<<"
            print(f"  {col:<{COL_W}}  {zip_str:<{VAL_W}}  {api_str:<{VAL_W}}  {status}")

    conn.close()


def fetch_page(date_start: str, date_end: str, offset: int) -> list[dict]:
    params = urllib.parse.urlencode({
        "dateStart":   date_start,
        "dateEnd":     date_end,
        "printFields": PRINT_FIELDS,
        "rpp":         RPP,
        "offset":      offset,
    })
    url = f"{BASE_URL}?{params}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    return data.get("response", {}).get("award") or []


def fetch_all(date_start: str, date_end: str) -> list[dict]:
    records, offset = [], 0
    while True:
        page = fetch_page(date_start, date_end, offset)
        if not page:
            break
        records.extend(page)
        print(f"  Fetched offset={offset:>5}  page={len(page):>3}  total={len(records):>5}")
        if len(page) < RPP:
            break
        offset += RPP
    return records


def run_exists(days: int):
    today = date.today()
    start = today - timedelta(days=days)
    date_start = start.strftime("%m/%d/%Y")
    date_end   = today.strftime("%m/%d/%Y")

    print(f"Checking DB existence for NSF awards from {date_start} to {date_end} (--days={days})\n")
    raw_records = fetch_all(date_start, date_end)
    if not raw_records:
        print("No records returned.")
        return

    mapped = [map_record(r) for r in raw_records if r.get("id")]
    ids = [r["awd_id"] for r in mapped]

    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(ids))
    existing = set(
        row[0] for row in conn.execute(
            f"SELECT awd_id FROM nsf_awards WHERE awd_id IN ({placeholders})", ids
        ).fetchall()
    )
    conn.close()

    in_db = [r for r in mapped if r["awd_id"] in existing]
    new   = [r for r in mapped if r["awd_id"] not in existing]

    print(f"Total fetched  : {len(mapped):>5}")
    print(f"Already in DB  : {len(in_db):>5}")
    print(f"New (not in DB): {len(new):>5}")

    HDR  = f"  {'AWD_ID':<12}  {'INST_NAME':<40}  {'AMOUNT':>14}  {'FY':>6}  IN DB?"
    SEP  = "  " + "-" * (len(HDR) - 2)

    if new:
        print(f"\nNew awards (would be inserted on a real run):")
        print(HDR)
        print(SEP)
        for r in new:
            inst    = (r["inst_name"] or "")[:40]
            amt     = r["awd_amount"]
            amt_str = f"{amt:>14,.0f}" if amt is not None else f"{'NULL':>14}"
            fy      = str(r["fiscal_year"]) if r["fiscal_year"] is not None else "NULL"
            print(f"  {r['awd_id']:<12}  {inst:<40}  {amt_str}  {fy:>6}  NO")

    if in_db:
        print(f"\nAwards already in DB:")
        print(HDR)
        print(SEP)
        for r in in_db:
            inst    = (r["inst_name"] or "")[:40]
            amt     = r["awd_amount"]
            amt_str = f"{amt:>14,.0f}" if amt is not None else f"{'NULL':>14}"
            fy      = str(r["fiscal_year"]) if r["fiscal_year"] is not None else "NULL"
            print(f"  {r['awd_id']:<12}  {inst:<40}  {amt_str}  {fy:>6}  YES")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1,
                        help="Pull awards from today minus DAYS to today (default: 1).")
    parser.add_argument("--test", action="store_true",
                        help="Fetch awards 2531827 and 2552363, compare API vs DB. No upsert.")
    parser.add_argument("--compare", action="store_true",
                        help="Compare 5 awards: ZIP vs API values. No upsert.")
    parser.add_argument("--exists", action="store_true",
                        help="Fetch API awards for --days range and check which already exist in DB. No upsert.")
    args = parser.parse_args()

    if args.test:
        run_test()
        return

    if args.compare:
        run_compare()
        return

    if args.exists:
        run_exists(args.days)
        return

    today = date.today()
    start = today - timedelta(days=args.days)
    date_start = start.strftime("%m/%d/%Y")
    date_end   = today.strftime("%m/%d/%Y")

    print(f"Fetching NSF awards from {date_start} to {date_end} (--days={args.days})\n")

    init_db()

    raw_records = fetch_all(date_start, date_end)
    if not raw_records:
        print("No records returned.")
        return

    # snapshot existing IDs to distinguish inserts vs updates
    conn = sqlite3.connect(DB_PATH)
    existing_ids = set(
        row[0] for row in conn.execute("SELECT awd_id FROM nsf_awards").fetchall()
    )
    conn.close()

    mapped = [map_record(r) for r in raw_records if r.get("id")]

    inserted = sum(1 for r in mapped if r["awd_id"] not in existing_ids)
    updated  = len(mapped) - inserted

    upsert_nsf_awards_batch(mapped)

    print(f"\nFetched:  {len(raw_records):>6,}")
    print(f"Inserted: {inserted:>6,}")
    print(f"Updated:  {updated:>6,}")


if __name__ == "__main__":
    main()
