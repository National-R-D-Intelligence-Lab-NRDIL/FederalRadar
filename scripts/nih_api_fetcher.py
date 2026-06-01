"""
nih_api_fetcher.py
Fetches NIH awards from the NIH RePORTER API and upserts them into federal_awards.db.
"""

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_awards_batch, DB_PATH, log_refresh_start, log_refresh_end

URL = "https://api.reporter.nih.gov/v2/projects/search"
LIMIT = 500
RAW_NIH_DIR = Path(__file__).parent.parent / "data" / "raw" / "nih"


def iso_date(dt_str) -> str | None:
    """Strip time component from NIH datetime strings (e.g. '2025-09-05T00:00:00' -> '2025-09-05').
    Returns None if blank or None.
    """
    if not dt_str:
        return None
    try:
        return dt_str.strip().split("T")[0]
    except Exception:
        return None


def map_record(rec: dict) -> dict:
    """Maps one NIH API result to the 21-column awards dict (DB adds created_at/updated_at).

    NIH multi-year note: project_num changes yearly (1R35...-01 -> 5R35...-05).
    Each year = one row in awards. core_project_num in raw_json links them.
    """
    org = rec.get("organization") or {}

    # Pick the IC with highest total_cost for nih_institute; fall back to first
    ic_fundings = rec.get("agency_ic_fundings") or []
    if ic_fundings:
        top_ic = max(ic_fundings, key=lambda x: x.get("total_cost") or 0)
        nih_institute = top_ic.get("abbreviation")
    else:
        nih_institute = None

    pi_name = rec.get("contact_pi_name")
    if pi_name:
        pi_name = pi_name.strip()

    try:
        awd_amount = float(rec["award_amount"]) if rec.get("award_amount") is not None else None
    except (TypeError, ValueError):
        awd_amount = None

    return {
        "awd_id":                 rec.get("project_num"),
        "awd_titl_txt":           rec.get("project_title"),
        "inst_name":              org.get("org_name"),
        "inst_state_code":        org.get("org_state"),
        "awd_amount":             awd_amount,
        "obligation_date":        iso_date(rec.get("award_notice_date")),
        "project_start_date":     iso_date(rec.get("project_start_date")),
        "project_end_date":       iso_date(rec.get("project_end_date")),
        "awd_abstract_narration": rec.get("abstract_text"),
        "pi_name":                pi_name,
        "agcy_id":                rec.get("agency_code"),
        "fiscal_year":            rec.get("fiscal_year"),
        "raw_json":               json.dumps(rec),
        "source":                 "nih",
        "activity_code":          rec.get("activity_code"),
        "nih_institute":          nih_institute,
        "direct_cost_amt":        rec.get("direct_cost_amt"),
        "opportunity_number":     rec.get("opportunity_number"),
        # NIH has no directorate/division/program-element equivalents
        "dir_abbr":               None,
        "div_abbr":               None,
        "pgm_ele_name":           None,
    }


def fetch_page(criteria: dict, offset: int) -> tuple[list[dict], int]:
    """POST one page to the NIH RePORTER API. Returns (results, meta_total)."""
    payload = json.dumps({
        "criteria": criteria,
        "limit": LIMIT,
        "offset": offset,
        "sort_field": "award_notice_date",
        "sort_order": "desc",
    }).encode()

    req = urllib.request.Request(
        URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())

    results = data.get("results") or []
    meta_total = data.get("meta", {}).get("total", 0)
    return results, meta_total


# The NIH API rejects requests with offset >= 15,000 (HTTP 400).
# Monthly windowing keeps each window well under this limit.
NIH_MAX_OFFSET = 14500


def _paginate(criteria: dict, label: str) -> list[dict]:
    """Paginate a single criteria set, respecting NIH's offset ceiling.

    If a window still exceeds NIH_MAX_OFFSET records, prints a warning but
    does not crash — that window's remainder is silently dropped (log and
    investigate if it appears in production).
    """
    records = []
    offset = 0
    page_num = 0
    meta_total = None

    while True:
        page, total = fetch_page(criteria, offset)

        if meta_total is None:
            meta_total = total

        if not page:
            break

        records.extend(page)
        page_num += 1
        print(f"  {label}  offset={offset:>6}  page={page_num:>4}  fetched={len(records):>6}  window={total:>6}")

        next_offset = offset + LIMIT
        if len(page) < LIMIT or next_offset > NIH_MAX_OFFSET:
            if next_offset > NIH_MAX_OFFSET and len(page) == LIMIT:
                print(f"  WARNING: {label} - window has {total:,} records but API offset limit reached at {offset + LIMIT:,}. Split window further if data completeness is critical.")
            break
        offset = next_offset

    return records


def fetch_all_by_fiscal_years(fiscal_years: list[int]) -> list[dict]:
    """Bulk fetch for fiscal years. Chunks into bi-weekly award_notice_date windows
    combined with fiscal_years criteria to stay under the NIH API offset limit.

    The NIH API rejects offset >= 15,000. Bi-weekly windows (14-15 days) keep
    each window under ~8,000 records for FY2024+2025, well within the ceiling.
    """
    # Start 3 months before the earliest FY to catch any early-noticed awards.
    # FY starts Oct 1 of the prior calendar year.
    min_fy = min(fiscal_years)
    range_start = date(min_fy - 1, 7, 1)   # Jul 1 of prior year — safe buffer
    range_end   = date.today()

    print(f"  FY{fiscal_years}: scanning {range_start} -> {range_end} in bi-weekly windows")

    all_records = []
    seen_ids: set[str] = set()
    current = range_start

    while current <= range_end:
        # Bi-weekly: first half = days 1-15, second half = days 16-end-of-month
        if current.day <= 15:
            chunk_end = current.replace(day=15)
            if current.month == 12:
                next_start = date(current.year + 1, 1, 16)
            else:
                next_start = date(current.year, current.month, 16)
        else:
            if current.month == 12:
                chunk_end = date(current.year, 12, 31)
                next_start = date(current.year + 1, 1, 1)
            else:
                next_month = current.month + 1
                chunk_end = date(current.year, current.month,
                                 (date(current.year, next_month, 1) - timedelta(days=1)).day)
                next_start = date(current.year, next_month, 1)

        chunk_end = min(chunk_end, range_end)
        date_from = current.strftime("%Y-%m-%d")
        date_to   = chunk_end.strftime("%Y-%m-%d")
        label = f"{date_from}->{date_to}"

        criteria = {
            "fiscal_years": fiscal_years,
            "award_notice_date": {"from_date": date_from, "to_date": date_to},
        }

        chunk = _paginate(criteria, label)

        # Deduplicate across windows (project_num may appear in multiple date windows
        # for multi-year awards that receive a new notice in a later period).
        new = [r for r in chunk if r.get("project_num") not in seen_ids]
        seen_ids.update(r["project_num"] for r in new if r.get("project_num"))
        all_records.extend(new)

        current = next_start

    print(f"\n  FY{fiscal_years} total fetched: {len(all_records):,} unique records")
    return all_records


def fetch_all_by_date_range(date_from: str, date_to: str) -> list[dict]:
    """Daily refresh fetch by award_notice_date range.

    date_from / date_to format: "YYYY-MM-DD"
    For a 1-2 day window this will never approach the API offset limit.
    """
    criteria = {
        "award_notice_date": {
            "from_date": date_from,
            "to_date": date_to,
        }
    }
    return _paginate(criteria, label=f"{date_from}->{date_to}")


def run_summary_query():
    """Print NIH award counts and total funding by fiscal year."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT source, fiscal_year, COUNT(*), SUM(awd_amount)/1e9 "
        "FROM awards WHERE source = 'nih' "
        "GROUP BY fiscal_year ORDER BY fiscal_year DESC"
    ).fetchall()
    conn.close()

    print(f"\n{'SOURCE':<8}  {'FY':<6}  {'Count':>8}  {'Total ($B)':>12}")
    print("-" * 42)
    for source, fy, count, funding_b in rows:
        funding_str = f"{funding_b:.4f}" if funding_b is not None else "NULL"
        print(f"{source:<8}  {fy:<6}  {count:>8,}  {funding_str:>12}")


def download_fiscal_year(fy: int) -> int:
    """Download all awards for a single fiscal year to a local JSONL file.

    Crash-safe: completed bi-weekly windows are recorded in a .progress file so
    an interrupted run resumes from where it left off.

    Returns the total number of records written (new this run + previously written).
    """
    RAW_NIH_DIR.mkdir(parents=True, exist_ok=True)
    jsonl_path = RAW_NIH_DIR / f"FY{fy}.jsonl"
    progress_path = RAW_NIH_DIR / f"FY{fy}.progress"

    # Load completed windows
    completed: set[str] = set()
    if progress_path.exists():
        completed = {line.strip() for line in progress_path.read_text().splitlines() if line.strip()}

    # Load already-seen project_nums to deduplicate on resume
    seen_ids: set[str] = set()
    existing_count = 0
    if jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rec = json.loads(line)
                        pid = rec.get("project_num")
                        if pid:
                            seen_ids.add(pid)
                        existing_count += 1
                    except json.JSONDecodeError:
                        pass

    print(f"FY{fy}: resuming with {existing_count:,} existing records, {len(completed)} completed windows")

    # Bi-weekly window loop (same logic as fetch_all_by_fiscal_years)
    range_start = date(fy - 1, 7, 1)   # Jul 1 of prior year — safe buffer
    range_end   = date.today()
    current = range_start
    new_count = 0

    with open(jsonl_path, "a", encoding="utf-8") as jsonl_f, \
         open(progress_path, "a", encoding="utf-8") as prog_f:

        while current <= range_end:
            if current.day <= 15:
                chunk_end = current.replace(day=15)
                if current.month == 12:
                    next_start = date(current.year + 1, 1, 16)
                else:
                    next_start = date(current.year, current.month, 16)
            else:
                if current.month == 12:
                    chunk_end = date(current.year, 12, 31)
                    next_start = date(current.year + 1, 1, 1)
                else:
                    next_month = current.month + 1
                    chunk_end = date(current.year, current.month,
                                     (date(current.year, next_month, 1) - timedelta(days=1)).day)
                    next_start = date(current.year, next_month, 1)

            chunk_end = min(chunk_end, range_end)
            date_from = current.strftime("%Y-%m-%d")
            date_to   = chunk_end.strftime("%Y-%m-%d")
            window_key = f"{date_from}->{date_to}"

            if window_key in completed:
                current = next_start
                continue

            criteria = {
                "fiscal_years": [fy],
                "award_notice_date": {"from_date": date_from, "to_date": date_to},
            }
            chunk = _paginate(criteria, window_key)

            for rec in chunk:
                pid = rec.get("project_num")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                jsonl_f.write(json.dumps(rec) + "\n")
                new_count += 1

            jsonl_f.flush()
            prog_f.write(window_key + "\n")
            prog_f.flush()

            current = next_start

    total_count = existing_count + new_count

    # Summary
    total_funding = 0.0
    ic_totals: dict[str, float] = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            amt = rec.get("award_amount")
            if amt:
                try:
                    total_funding += float(amt)
                except (TypeError, ValueError):
                    pass
            for ic in rec.get("agency_ic_fundings") or []:
                abbr = ic.get("abbreviation") or "?"
                cost = ic.get("total_cost") or 0
                ic_totals[abbr] = ic_totals.get(abbr, 0.0) + cost

    top_ics = sorted(ic_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"\nFY{fy} download complete:")
    print(f"  Records : {total_count:,}")
    print(f"  Funding : ${total_funding / 1e9:.3f}B")
    print(f"  Top ICs : {', '.join(f'{k}(${v/1e6:.0f}M)' for k, v in top_ics)}")
    return total_count


def load_from_jsonl(path: str | Path) -> None:
    """Load awards from a JSONL file into the DB (memory-efficient, line by line)."""
    path = Path(path)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return

    init_db()
    mapped = []
    read_count = 0
    skip_count = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            read_count += 1
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skip_count += 1
                continue
            if not rec.get("project_num"):
                skip_count += 1
                continue
            mapped.append(map_record(rec))

    total_funding = sum(
        r["awd_amount"] for r in mapped if r.get("awd_amount") is not None
    )

    print(f"Read:     {read_count:>6,}")
    print(f"Skipped:  {skip_count:>6,}")
    print(f"Mapped:   {len(mapped):>6,}")
    print(f"Funding:  ${total_funding / 1e9:.3f}B")

    upsert_nsf_awards_batch(mapped)
    print(f"Upserted: {len(mapped):>6,}")


def main():
    parser = argparse.ArgumentParser(description="NIH RePORTER award fetcher")
    parser.add_argument(
        "--fiscal-years", default="2024,2025",
        help='Comma-separated fiscal years for bulk load, e.g. "2024,2025" (default)',
    )
    parser.add_argument(
        "--days", type=int,
        help="Daily refresh: fetch awards with award_notice_date in the last N days",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + map + print counts, no DB writes",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print NIH summary from DB, no fetch",
    )
    parser.add_argument(
        "--download-only", action="store_true",
        help="Download raw records to JSONL only (no DB writes). Use with --fiscal-years for a single year.",
    )
    parser.add_argument(
        "--load-raw", metavar="FILE",
        help="Load awards from a JSONL file into DB (no API calls).",
    )
    args = parser.parse_args()

    if args.summary:
        run_summary_query()
        return

    if args.load_raw:
        load_from_jsonl(args.load_raw)
        return

    if args.download_only:
        fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
        if len(fiscal_years) != 1:
            print("ERROR: --download-only requires exactly one fiscal year, e.g. --fiscal-years 2019")
            sys.exit(1)
        download_fiscal_year(fiscal_years[0])
        return

    init_db()

    details = f"--days {args.days}" if args.days else f"--fiscal-years {args.fiscal_years}"
    log_id = log_refresh_start("nih", details)

    try:
        if args.days:
            today = date.today()
            date_to = today.strftime("%Y-%m-%d")
            date_from = (today - timedelta(days=args.days)).strftime("%Y-%m-%d")
            print(f"Fetching NIH awards: award_notice_date {date_from} -> {date_to}\n")
            raw_records = fetch_all_by_date_range(date_from, date_to)
        else:
            fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
            print(f"Fetching NIH awards for fiscal years: {fiscal_years}\n")
            raw_records = fetch_all_by_fiscal_years(fiscal_years)

        if not raw_records:
            print("No records returned.")
            log_refresh_end(log_id, "success", 0, 0)
            return

        mapped = [map_record(r) for r in raw_records if r.get("project_num")]

        print(f"\nFetched:  {len(raw_records):>6,}")
        print(f"Mapped:   {len(mapped):>6,}")

        if args.dry_run:
            print("--dry-run: skipping DB writes.")
            log_refresh_end(log_id, "dry_run", len(raw_records), 0)
            return

        upsert_nsf_awards_batch(mapped)
        print(f"Upserted: {len(mapped):>6,}")
        log_refresh_end(log_id, "success", len(raw_records), len(mapped))
    except Exception as e:
        log_refresh_end(log_id, "failed", error_message=str(e))
        raise


if __name__ == "__main__":
    main()
