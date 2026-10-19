"""
nsf_api_fetcher.py
Fetches recent NSF awards from the public API and upserts them into federal_awards.db.
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_awards_batch, DB_PATH, log_refresh_start, log_refresh_end

BASE_URL = "https://api.nsf.gov/services/v1/awards.json"
# fundsObligated: array of "FY 2021 = $19,162.00" strings, same per-year
# breakdown as bulk's oblg_fy -- confirmed live (see Federal Radar V2's
# CLAUDE.md, "Decided: Hybrid NSF Ingestion"). fundsObligatedAmt (singular)
# is kept only as a last-resort fallback for the rare record missing the
# per-year array.
PRINT_FIELDS = (
    "id,title,awardeeName,awardeeStateCode,fundsObligatedAmt,fundsObligated,"
    "date,startDate,expDate,abstractText,dirAbbr,divAbbr,fundProgramName,pdPIName"
)
RPP = 25
_FY_RE  = re.compile(r"FY\s*(\d{4})")
_AMT_RE = re.compile(r"\$([0-9,]+(?:\.[0-9]+)?)")


def date_to_iso(mmddyyyy: str) -> str | None:
    """Convert MM/DD/YYYY to YYYY-MM-DD. Returns None if blank/unparseable."""
    try:
        m, d, y = mmddyyyy.strip().split("/")
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    except Exception:
        return None


def _parse_funds_obligated(entries: list) -> list[tuple[int, float]]:
    """Parse fundsObligated display strings ("FY 2021 = $19,162.00") into
    (fiscal_year, amount) pairs. Skips any entry that doesn't match."""
    out = []
    for entry in entries or []:
        fy_m  = _FY_RE.search(entry or "")
        amt_m = _AMT_RE.search(entry or "")
        if not fy_m or not amt_m:
            continue
        try:
            fy  = int(fy_m.group(1))
            amt = float(amt_m.group(1).replace(",", ""))
        except (TypeError, ValueError):
            continue
        out.append((fy, amt))
    return out


def map_records(rec: dict) -> list[dict]:
    """One row per award PER FISCAL YEAR -- mirrors nsf_etl.py's bulk-ZIP
    mapping. Prefers the fundsObligated per-year array; falls back to a
    single row from fundsObligatedAmt + the award's origin date only if
    fundsObligated is absent (should be rare)."""
    common = {
        "awd_id":                 rec.get("id"),
        "awd_titl_txt":           rec.get("title"),
        "inst_name":              rec.get("awardeeName"),
        "inst_state_code":        rec.get("awardeeStateCode"),
        "obligation_date":        date_to_iso(rec.get("date") or ""),
        "project_start_date":     date_to_iso(rec.get("startDate") or ""),
        "project_end_date":       date_to_iso(rec.get("expDate") or ""),
        "awd_abstract_narration": rec.get("abstractText"),
        "dir_abbr":               rec.get("dirAbbr"),
        "div_abbr":               rec.get("divAbbr"),
        "pgm_ele_name":           rec.get("fundProgramName"),
        "pi_name":                rec.get("pdPIName"),
        "agcy_id":                None,
        "raw_json":               json.dumps(rec),
        "source":                 "nsf",
        "opportunity_number":     None,
        "activity_code":          None,
        "nih_institute":          None,
        "direct_cost_amt":        None,
    }

    year_amounts = _parse_funds_obligated(rec.get("fundsObligated"))
    if year_amounts:
        return [{**common, "fiscal_year": fy, "awd_amount": amt} for fy, amt in year_amounts]

    # Fallback: no per-year breakdown returned, use the single total + origin date.
    raw_date = rec.get("date") or ""
    try:
        parts = raw_date.strip().split("/")
        month, year = int(parts[0]), int(parts[2])
        fiscal_year = year + 1 if month >= 10 else year
    except Exception:
        fiscal_year = None
    try:
        awd_amount = float(rec["fundsObligatedAmt"]) if rec.get("fundsObligatedAmt") not in (None, "") else None
    except (TypeError, ValueError):
        awd_amount = None
    if fiscal_year is None:
        return []
    return [{**common, "fiscal_year": fiscal_year, "awd_amount": awd_amount}]


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
    rows = conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM awards WHERE awd_id = ? ORDER BY fiscal_year", (awd_id,)
    ).fetchall()
    conn.close()
    return [dict(zip(COLUMNS, row)) for row in rows]


def run_test():
    """Fetch two known awards, print one comparison block per fiscal-year row
    (grain is now one row per award-year, so a multi-year award prints
    multiple blocks)."""
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
        api_recs = map_records(raw)
        db_recs_by_fy = {r["fiscal_year"]: r for r in fetch_db_row(award_id)}

        for api_rec in api_recs:
            fy = api_rec["fiscal_year"]
            db_rec = db_recs_by_fy.get(fy, {})
            print(f"\n  -- FY{fy} --")
            if not db_rec:
                print("  Not found in DB for this fiscal year.")

            header = f"  {'COLUMN':<{COL_W}}  {'API VALUE':<{VAL_W}}  {'DB VALUE':<{VAL_W}}  STATUS"
            print(header)
            print("  " + "-" * (COL_W + VAL_W * 2 + 14))

            for col in COMPARE_COLS:
                api_val = api_rec.get(col)
                db_val  = db_rec.get(col)

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

        api_recs = map_records(raw)
        db_rows = conn.execute(
            f"SELECT {DB_COLS} FROM awards WHERE awd_id = ? ORDER BY fiscal_year", (award_id,)
        ).fetchall()
        db_recs_by_fy = {dict(zip(COMPARE_COLS, row))["fiscal_year"]: dict(zip(COMPARE_COLS, row)) for row in db_rows}

        if not db_rows:
            print("  Not found in DB.")

        for api_rec in api_recs:
            fy = api_rec["fiscal_year"]
            db_rec = db_recs_by_fy.get(fy, {})
            print(f"\n  -- FY{fy} --")
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

    mapped = [row for r in raw_records if r.get("id") for row in map_records(r)]
    ids = list({r["awd_id"] for r in mapped})

    conn = sqlite3.connect(DB_PATH)
    placeholders = ",".join("?" * len(ids))
    existing = set(
        (row[0], row[1]) for row in conn.execute(
            f"SELECT awd_id, fiscal_year FROM awards WHERE awd_id IN ({placeholders})", ids
        ).fetchall()
    )
    conn.close()

    in_db = [r for r in mapped if (r["awd_id"], r["fiscal_year"]) in existing]
    new   = [r for r in mapped if (r["awd_id"], r["fiscal_year"]) not in existing]

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
    log_id = log_refresh_start("nsf", f"--days {args.days}")

    try:
        raw_records = fetch_all(date_start, date_end)
        if not raw_records:
            print("No records returned.")
            log_refresh_end(log_id, "success", 0, 0)
            return

        # snapshot existing (awd_id, fiscal_year) keys to distinguish inserts vs updates
        conn = sqlite3.connect(DB_PATH)
        existing_keys = set(
            (row[0], row[1]) for row in conn.execute(
                "SELECT awd_id, fiscal_year FROM awards WHERE source = 'nsf'"
            ).fetchall()
        )
        conn.close()

        mapped = [row for r in raw_records if r.get("id") for row in map_records(r)]

        inserted = sum(1 for r in mapped if (r["awd_id"], r["fiscal_year"]) not in existing_keys)
        updated  = len(mapped) - inserted

        upsert_nsf_awards_batch(mapped)

        print(f"\nFetched:  {len(raw_records):>6,}")
        print(f"Inserted: {inserted:>6,}")
        print(f"Updated:  {updated:>6,}")
        log_refresh_end(log_id, "success", len(raw_records), len(mapped))
    except Exception as e:
        log_refresh_end(log_id, "failed", error_message=str(e))
        raise


if __name__ == "__main__":
    main()
