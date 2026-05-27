"""
usaspending_api_fetcher.py
Fetches federal grants to universities from USASpending.gov and upserts them
into federal_awards.db. Covers DOE, NASA, DOD, USDA, EPA, DHS, Commerce, etc.

Two-step pattern (mirrors nih_api_fetcher):
  1. --download-only  → bulk download ZIP → extract JSONL (crash-safe via .done sentinel)
  2. --load-raw FILE   → map + upsert from JSONL into DB

Bulk Download API replaces bi-weekly pagination:
  - POST /api/v2/bulk_download/awards/ → get file_name
  - GET  /api/v2/bulk_download/status/?file_name=xxx.zip → poll until finished
  - Download ZIP → extract CSV(s) → filter university rows → write JSONL

Live API gotchas:
  - recipient_type_names filter is broken (returns 0 results) → use keyword filter instead
  - Fiscal Year field is always null → derive from Start Date using Oct 1 boundary
  - recipient_state_code is always null → use Place of Performance State Code
"""

import argparse
import concurrent.futures
import csv
import io
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_awards_batch, DB_PATH

BULK_DOWNLOAD_URL = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
STATUS_URL        = "https://api.usaspending.gov/api/v2/bulk_download/status/"
POLL_INTERVAL     = 10   # seconds between status checks
MAX_WAIT          = 3600 # 1 hour max before giving up

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "usaspending"

GRANT_AWARD_TYPES = ["02", "03", "04", "05"]

UNIVERSITY_KEYWORDS = ["UNIVERSITY", "COLLEGE", "INSTITUTE", "POLYTECHNIC", "SCHOOL", "ACADEMY"]

AGENCIES = {
    "doe":      "Department of Energy",
    "nasa":     "National Aeronautics and Space Administration",
    "dod":      "Department of Defense",
    "usda":     "Department of Agriculture",
    "epa":      "Environmental Protection Agency",
    "dhs":      "Department of Homeland Security",
    "commerce": "Department of Commerce",
    "ed":       "Department of Education",
    "dot":      "Department of Transportation",
    "hhs":      "Department of Health and Human Services",
    "neh":      "National Endowment for the Humanities",
}

# Sub-agencies to exclude during record extraction.
# HHS contains NIH — we load NIH separately via nih_api_fetcher.py so we
# strip NIH records here to avoid double-counting.
EXCLUDE_SUBAGENCIES = {
    "hhs": {"national institutes of health"},
}


def is_university(name: str) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(kw in upper for kw in UNIVERSITY_KEYWORDS)


def derive_fiscal_year(start_date: str) -> int | None:
    if not start_date:
        return None
    try:
        d = date.fromisoformat(start_date[:10])
        return d.year + 1 if d.month >= 10 else d.year
    except ValueError:
        return None


def request_bulk_download(agency_key: str, fy: int) -> str:
    """POST bulk download job for one agency + fiscal year.

    Returns the file_name from the response (used for polling).
    """
    date_from = f"{fy - 1}-10-01"
    date_to   = f"{fy}-09-30"
    # Cap end date at today so we don't request future dates
    today_str = date.today().strftime("%Y-%m-%d")
    if date_to > today_str:
        date_to = today_str

    payload = json.dumps({
        "filters": {
            "agencies": [{"type": "awarding", "tier": "toptier", "name": AGENCIES[agency_key]}],
            "date_range": {"start_date": date_from, "end_date": date_to},
            "date_type": "action_date",
            "prime_award_types": GRANT_AWARD_TYPES,
            "recipient_scope": "domestic",
        },
        "file_format": "csv",
    }).encode()

    req = urllib.request.Request(
        BULK_DOWNLOAD_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
            break
        except Exception as exc:
            if attempt == 3:
                raise
            print(f"  [submit] attempt {attempt} failed: {exc} — retrying in 10s")
            time.sleep(10)

    file_name = data.get("file_name")
    if not file_name:
        raise RuntimeError(f"bulk_download POST returned no file_name: {data}")

    print(f"  Job submitted: {file_name}")
    return file_name


def poll_until_ready(file_name: str, max_wait: int = MAX_WAIT) -> str:
    """Poll status endpoint until job is finished.

    Returns the file_url when status == 'finished'.
    Raises RuntimeError on failure or timeout.
    """
    deadline = time.time() + max_wait
    elapsed = 0
    while time.time() < deadline:
        url = f"{STATUS_URL}?file_name={urllib.parse.quote(file_name)}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            print(f"  [poll] warning: {exc} — retrying")
            time.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL
            continue

        status = data.get("status", "")
        file_url = data.get("file_url")
        print(f"  [{elapsed:>4}s] status={status}  file_url={'set' if file_url else 'null'}")

        if status == "finished" and file_url:
            return file_url
        if status == "failed":
            raise RuntimeError(f"Bulk download job failed: {data.get('message', 'no message')}")

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    raise RuntimeError(f"Bulk download timed out after {max_wait}s: {file_name}")


def download_zip(file_url: str, dest_path: Path) -> None:
    """Stream-download the ZIP to dest_path, printing progress."""
    print(f"  Downloading: {file_url}")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(file_url, headers={"Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=300) as resp, \
         open(dest_path, "wb") as out_f:
        downloaded = 0
        chunk_size = 1024 * 1024  # 1 MB
        while True:
            chunk = resp.read(chunk_size)
            if not chunk:
                break
            out_f.write(chunk)
            downloaded += len(chunk)
            print(f"  {downloaded / 1e6:.1f} MB downloaded...", end="\r")

    print(f"\n  Saved: {dest_path} ({dest_path.stat().st_size / 1e6:.1f} MB)")


# ---------------------------------------------------------------------------
# Normalizers — one function per field type, reusable across all agencies
# ---------------------------------------------------------------------------

# Full state name → 2-letter USPS code
_STATE_NAME_TO_CODE = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI", "IDAHO": "ID",
    "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
    "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT",
    "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV",
    "WISCONSIN": "WI", "WYOMING": "WY", "DISTRICT OF COLUMBIA": "DC",
    "PUERTO RICO": "PR", "GUAM": "GU", "VIRGIN ISLANDS": "VI",
    "AMERICAN SAMOA": "AS", "NORTHERN MARIANA ISLANDS": "MP",
}

def normalize_date(value: str | None) -> str | None:
    """Return YYYY-MM-DD, stripping any time/timezone component."""
    if not value:
        return None
    return value.strip()[:10] or None


def normalize_state(value: str | None) -> str | None:
    """Return 2-letter state code regardless of whether input is code or full name."""
    if not value:
        return None
    v = value.strip().upper()
    if len(v) == 2:
        return v
    return _STATE_NAME_TO_CODE.get(v)


def normalize_amount(value: str | None) -> float | None:
    """Parse dollar amount string to float, handling commas and empty strings."""
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def normalize_fiscal_year(row: dict) -> int | None:
    """Use action_date_fiscal_year directly; fall back to deriving from start date."""
    raw = row.get("action_date_fiscal_year")
    if raw:
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    return derive_fiscal_year(row.get("period_of_performance_start_date"))


# ---------------------------------------------------------------------------
# Mapper — assembles one DB row from a normalized CSV row
# ---------------------------------------------------------------------------

def map_record_from_csv(row: dict, agency_key: str) -> dict:
    """Map one normalized CSV row to the awards DB schema.

    Column names are already lowercased + spaces→underscores before this is called.
    Raw JSON is preserved as-is for full auditability and future re-derivation.
    """
    state = (
        normalize_state(row.get("recipient_state_code"))
        or normalize_state(row.get("primary_place_of_performance_state_name"))
    )
    awd_id = row.get("assistance_award_unique_key") or row.get("assistance_transaction_unique_key")
    description = row.get("prime_award_base_transaction_description") or row.get("transaction_description")

    return {
        "awd_id":                 awd_id,
        "awd_titl_txt":           description,
        "inst_name":              row.get("recipient_name"),
        "inst_state_code":        state,
        "awd_amount":             normalize_amount(row.get("total_obligated_amount")),
        "obligation_date":        normalize_date(row.get("last_modified_date") or row.get("action_date")),
        "project_start_date":     normalize_date(row.get("period_of_performance_start_date")),
        "project_end_date":       normalize_date(row.get("period_of_performance_current_end_date")),
        "fiscal_year":            normalize_fiscal_year(row),
        "source":                 agency_key,
        "agcy_id":                agency_key.upper(),
        "opportunity_number":     row.get("cfda_number"),
        "raw_json":               json.dumps(row),
        # Not available in USASpending data
        "awd_abstract_narration": None,
        "pi_name":                None,
        "dir_abbr":               None,
        "div_abbr":               None,
        "pgm_ele_name":           None,
        "activity_code":          None,
        "nih_institute":          None,
        "direct_cost_amt":        None,
    }


def validate_record(record: dict) -> tuple[bool, str]:
    """Return (True, '') if record is loadable, or (False, reason) if it should be skipped."""
    if not record.get("awd_id"):
        return False, "missing awd_id"
    if not record.get("awd_titl_txt"):
        return False, "missing title"
    return True, ""


def extract_csv(zip_path: Path, csv_path: Path) -> None:
    """Extract and concatenate all CSVs from ZIP into one full raw CSV (all recipients)."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        with open(csv_path, "w", encoding="utf-8", newline="") as out_f:
            writer = csv.writer(out_f)
            header_written = False
            for csv_name in csv_names:
                with zf.open(csv_name) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                    reader = csv.reader(text)
                    for i, row in enumerate(reader):
                        if i == 0:
                            if not header_written:
                                writer.writerow(row)
                                header_written = True
                        else:
                            writer.writerow(row)
    print(f"  Raw CSV saved: {csv_path.name} ({csv_path.stat().st_size / 1e6:.1f} MB)")


def process_zip_to_jsonl(zip_path: Path, agency_key: str, jsonl_path: Path) -> int:
    """Extract ZIP, filter university rows from all CSVs, write to JSONL.

    Deduplicates by generated_internal_id. Returns count of records written.
    """
    seen_ids: set[str] = set()
    count = 0

    with open(jsonl_path, "w", encoding="utf-8") as out_f, \
         zipfile.ZipFile(zip_path, "r") as zf:

        csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        print(f"  ZIP contains {len(csv_names)} CSV file(s): {csv_names}")

        for csv_name in csv_names:
            print(f"  Processing {csv_name}...")
            with zf.open(csv_name) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                for row in reader:
                    # Normalise column names: strip whitespace and lowercase
                    row = {k.strip().lower().replace(" ", "_"): v.strip() if v else v
                           for k, v in row.items()}

                    recipient = row.get("recipient_name") or ""
                    if not is_university(recipient):
                        continue

                    # Exclude specific sub-agencies (e.g. NIH within HHS to avoid
                    # double-counting with nih_api_fetcher.py records)
                    excluded_subs = EXCLUDE_SUBAGENCIES.get(agency_key, set())
                    if excluded_subs:
                        sub = (row.get("awarding_sub_agency_name") or "").lower()
                        if any(ex in sub for ex in excluded_subs):
                            continue

                    gid = row.get("assistance_award_unique_key") or row.get("assistance_transaction_unique_key")
                    if not gid or gid in seen_ids:
                        continue

                    seen_ids.add(gid)
                    out_f.write(json.dumps(row) + "\n")
                    count += 1

    print(f"  University records written: {count:,}")
    return count


def download_fiscal_year(agency_key: str, fy: int) -> int:
    """Download all university grants for one agency + fiscal year to a JSONL file.

    Crash-safe via .done sentinel:
      - If .done exists, JSONL is complete — skip entirely.
      - If ZIP already exists (partial run), skip download and re-process.
      - .done is written only after JSONL is fully written.

    Returns count of university records in the JSONL.
    """
    year_dir = RAW_DIR / str(fy)
    year_dir.mkdir(parents=True, exist_ok=True)
    zip_path   = year_dir / f"{agency_key.upper()}_FY{fy}.zip"
    csv_path   = year_dir / f"{agency_key.upper()}_FY{fy}.csv"
    jsonl_path = year_dir / f"{agency_key.upper()}_FY{fy}.jsonl"
    done_path  = year_dir / f"{agency_key.upper()}_FY{fy}.done"

    # Already complete
    if done_path.exists() and csv_path.exists() and jsonl_path.exists():
        count = sum(1 for line in open(jsonl_path, encoding="utf-8") if line.strip())
        print(f"  Already complete: {count:,} records (delete .done to re-run)")
        return count

    # Download ZIP if not already on disk
    if not zip_path.exists():
        print(f"{agency_key.upper()} FY{fy}: submitting bulk download job...")
        file_name = request_bulk_download(agency_key, fy)
        print(f"{agency_key.upper()} FY{fy}: polling for completion (max {MAX_WAIT}s)...")
        file_url = poll_until_ready(file_name)
        download_zip(file_url, zip_path)
    else:
        print(f"{agency_key.upper()} FY{fy}: ZIP already downloaded, skipping to processing")

    # Extract full raw CSV (all recipients)
    print(f"{agency_key.upper()} FY{fy}: extracting full raw CSV...")
    extract_csv(zip_path, csv_path)

    # Extract + filter → JSONL (overwrites any partial JSONL from a previous failed run)
    print(f"{agency_key.upper()} FY{fy}: extracting and filtering university records...")
    count = process_zip_to_jsonl(zip_path, agency_key, jsonl_path)

    # Mark complete
    done_path.touch()

    # Summary
    total_funding = 0.0
    inst_totals: dict[str, float] = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw_amt = row.get("total_obligated_amount")
            if raw_amt:
                try:
                    v = float(raw_amt)
                    total_funding += v
                    name = row.get("recipient_name") or "?"
                    inst_totals[name] = inst_totals.get(name, 0.0) + v
                except (TypeError, ValueError):
                    pass

    top_insts = sorted(inst_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"\n{agency_key.upper()} FY{fy} download complete:")
    print(f"  Records : {count:,}")
    print(f"  Funding : ${total_funding / 1e9:.3f}B")
    print(f"  Top institutions:")
    for name, amt in top_insts:
        print(f"    {name[:60]:<60} ${amt / 1e6:>8.1f}M")

    return count


def load_from_jsonl(path: str | Path, agency_key: str) -> dict:
    """Load university grants from a JSONL file into the DB.

    Returns a dict with read/skipped/upserted counts and total funding.
    Safe to re-run — upsert is idempotent (ON CONFLICT DO UPDATE).
    """
    path = Path(path)
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        return {"read": 0, "skipped": 0, "upserted": 0, "funding": 0.0, "error": "file not found"}

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
                row = json.loads(line)
            except json.JSONDecodeError:
                skip_count += 1
                continue
            mapped_row = map_record_from_csv(row, agency_key)
            ok, reason = validate_record(mapped_row)
            if not ok:
                skip_count += 1
                continue
            mapped.append(mapped_row)

    total_funding = sum(
        r["awd_amount"] for r in mapped if r.get("awd_amount") is not None
    )

    upsert_nsf_awards_batch(mapped)

    return {
        "read":     read_count,
        "skipped":  skip_count,
        "upserted": len(mapped),
        "funding":  total_funding,
        "error":    None,
    }


def load_all_years(skip_agencies: str = "") -> None:
    """Load all downloaded JSONL files across all years into the DB.

    - Discovers files automatically from data/raw/usaspending/<year>/<AGENCY>_FY<year>.jsonl
    - Only loads files that have a corresponding .done sentinel (fully downloaded)
    - Idempotent: safe to re-run, upsert handles duplicates
    - Prints a per-file progress line and a summary table at the end
    """
    skip = {s.strip().lower() for s in skip_agencies.split(",") if s.strip()}

    init_db()

    year_dirs = sorted(
        (d for d in RAW_DIR.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name)
    )

    results = []
    total_read = total_upserted = total_skipped = 0
    total_funding = 0.0

    for year_dir in year_dirs:
        fy = int(year_dir.name)
        for jsonl_path in sorted(year_dir.glob("*.jsonl")):
            stem = jsonl_path.stem  # e.g. DOE_FY2019
            agency_key = stem.split("_")[0].lower()

            if agency_key in skip:
                continue
            if agency_key not in AGENCIES:
                continue

            done_path = jsonl_path.with_suffix(".done")
            if not done_path.exists():
                print(f"  SKIP {stem} — no .done sentinel, download may be incomplete")
                results.append({"file": stem, "status": "skipped_incomplete"})
                continue

            print(f"  Loading {stem}...", end=" ", flush=True)
            counts = load_from_jsonl(jsonl_path, agency_key)

            if counts.get("error"):
                print(f"ERROR: {counts['error']}")
                results.append({"file": stem, "status": "error", **counts})
                continue

            total_read     += counts["read"]
            total_upserted += counts["upserted"]
            total_skipped  += counts["skipped"]
            total_funding  += counts["funding"]

            print(f"read={counts['read']:,}  upserted={counts['upserted']:,}  "
                  f"skipped={counts['skipped']}  funding=${counts['funding']/1e9:.2f}B")
            results.append({"file": stem, "fy": fy, "agency": agency_key,
                            "status": "ok", **counts})

    # Summary
    loaded = [r for r in results if r["status"] == "ok"]
    print(f"\n{'='*65}")
    print(f"  LOAD COMPLETE")
    print(f"{'='*65}")
    print(f"  Files loaded   : {len(loaded)}")
    print(f"  Total read     : {total_read:,}")
    print(f"  Total upserted : {total_upserted:,}")
    print(f"  Total skipped  : {total_skipped:,}")
    print(f"  Total funding  : ${total_funding/1e9:.2f}B")

    errors = [r for r in results if r["status"] == "error"]
    incomplete = [r for r in results if r["status"] == "skipped_incomplete"]
    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for r in errors: print(f"    {r['file']}: {r.get('error')}")
    if incomplete:
        print(f"\n  INCOMPLETE DOWNLOADS ({len(incomplete)}):")
        for r in incomplete: print(f"    {r['file']}")


def run_summary_query() -> None:
    """Print USASpending award counts and total funding by source + fiscal year."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT source, fiscal_year, COUNT(*), SUM(awd_amount)/1e9 "
        "FROM awards WHERE source NOT IN ('nsf', 'nih') "
        "GROUP BY source, fiscal_year ORDER BY source, fiscal_year DESC"
    ).fetchall()
    conn.close()

    if not rows:
        print("No USASpending records in DB yet.")
        return

    print(f"\n{'SOURCE':<10}  {'FY':<6}  {'Count':>8}  {'Total ($B)':>12}")
    print("-" * 44)
    for source, fy, count, funding_b in rows:
        funding_str = f"{funding_b:.4f}" if funding_b is not None else "NULL"
        print(f"{source:<10}  {fy:<6}  {count:>8,}  {funding_str:>12}")


def main():
    parser = argparse.ArgumentParser(description="USASpending.gov federal grants to universities fetcher")
    parser.add_argument(
        "--agency", choices=list(AGENCIES.keys()),
        help="Agency key (e.g. doe, nasa, dod)",
    )
    parser.add_argument(
        "--fiscal-years", default="2024",
        help='Comma-separated fiscal years, e.g. "2024,2025" (default: 2024)',
    )
    parser.add_argument(
        "--download-only", action="store_true",
        help="Download raw JSONL only (no DB writes). Requires --agency and exactly one fiscal year.",
    )
    parser.add_argument(
        "--load-raw", metavar="FILE",
        help="Load awards from a JSONL file into DB (no API calls). Requires --agency.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Submit one bulk download job, print first 10 university rows — no DB writes.",
    )
    parser.add_argument(
        "--summary", action="store_true",
        help="Print USASpending summary from DB (all non-NSF/NIH sources), no fetch.",
    )
    parser.add_argument(
        "--all-agencies", action="store_true",
        help='Download all agencies in parallel for each fiscal year, e.g. --fiscal-years "2019,2020".',
    )
    parser.add_argument(
        "--skip-agencies", default="",
        help='Comma-separated agency keys to skip, e.g. "dhs,usda".',
    )
    parser.add_argument(
        "--load-all-years", action="store_true",
        help="Load all downloaded JSONL files across all years into the DB. Idempotent.",
    )
    args = parser.parse_args()

    if args.load_all_years:
        load_all_years(skip_agencies=args.skip_agencies)
        return

    if args.summary:
        run_summary_query()
        return

    if args.load_raw:
        if not args.agency:
            print("ERROR: --load-raw requires --agency")
            sys.exit(1)
        load_from_jsonl(args.load_raw, args.agency)
        return

    if args.all_agencies:
        fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
        skip = {s.strip().lower() for s in args.skip_agencies.split(",") if s.strip()}
        agencies_to_run = [k for k in AGENCIES if k not in skip]
        if skip:
            print(f"Skipping: {', '.join(skip)}")
        for fy in fiscal_years:
            print(f"\n{'='*60}")
            print(f"  All agencies FY{fy} — {len(agencies_to_run)} parallel jobs")
            print(f"{'='*60}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(agencies_to_run)) as executor:
                futures = {
                    executor.submit(download_fiscal_year, agency_key, fy): agency_key
                    for agency_key in agencies_to_run
                }
                for future in concurrent.futures.as_completed(futures):
                    agency_key = futures[future]
                    try:
                        count = future.result()
                        print(f"  {agency_key.upper()} FY{fy}: done ({count:,} university records)")
                    except Exception as exc:
                        print(f"  {agency_key.upper()} FY{fy}: FAILED — {exc}")
        return

    if not args.agency and not args.all_agencies:
        print("ERROR: --agency or --all-agencies is required")
        sys.exit(1)

    if args.download_only:
        fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
        if len(fiscal_years) != 1:
            print("ERROR: --download-only requires exactly one fiscal year, e.g. --fiscal-years 2024")
            sys.exit(1)
        download_fiscal_year(args.agency, fiscal_years[0])
        return

    if args.dry_run:
        fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
        fy = fiscal_years[0]
        agency_key = args.agency
        print(f"DRY RUN: {agency_key.upper()} FY{fy} — submitting bulk download job...\n")

        file_name = request_bulk_download(agency_key, fy)
        print(f"Polling for completion...")
        file_url = poll_until_ready(file_name)

        print(f"\nDownloading ZIP to memory for preview...")
        req = urllib.request.Request(file_url, headers={"Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            zip_bytes = resp.read()

        print(f"ZIP size: {len(zip_bytes) / 1e6:.1f} MB")

        rows_shown = 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            print(f"CSV files: {csv_names}\n")
            for csv_name in csv_names:
                with zf.open(csv_name) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
                    reader = csv.DictReader(text)
                    for row in reader:
                        row = {k.strip().lower().replace(" ", "_"): v.strip() if v else v
                               for k, v in row.items()}
                        if not is_university(row.get("recipient_name") or ""):
                            continue
                        mapped = map_record_from_csv(row, agency_key)
                        print(f"  {(mapped['inst_name'] or '')[:55]:<55} "
                              f"FY={mapped['fiscal_year']}  "
                              f"${(mapped['awd_amount'] or 0)/1e6:>8.2f}M  "
                              f"src={mapped['source']}")
                        rows_shown += 1
                        if rows_shown >= 10:
                            break
                if rows_shown >= 10:
                    break

        print(f"\n(showed {rows_shown} university rows — no files written)")
        return

    # Default: bulk download only (no DB writes)
    fiscal_years = [int(y.strip()) for y in args.fiscal_years.split(",")]
    print(f"Fetching {args.agency.upper()} grants for FY{fiscal_years} (download only)\n")
    for fy in fiscal_years:
        download_fiscal_year(args.agency, fy)


if __name__ == "__main__":
    main()
