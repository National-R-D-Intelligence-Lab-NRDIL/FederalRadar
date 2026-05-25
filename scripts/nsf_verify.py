"""
nsf_verify.py
Compares NSF 2025 award data from local ZIP vs live API.
No database writes.
"""

import json
import zipfile
from pathlib import Path

import requests

ZIP_PATH = Path(__file__).parent.parent / "data" / "raw" / "nsf" / "2025.zip"
API_BASE = "https://api.nsf.gov/services/v1/awards.json"
API_PARAMS = {
    "startDateStart": "10/01/2024",  # NSF FY2025 start
    "startDateEnd":   "09/30/2025",  # NSF FY2025 end
    "rpp":            100,
    "offset":         0,
}


# ── Part 1: Parse ZIP ─────────────────────────────────────────────────────────

def parse_zip(path: Path) -> tuple[int, float]:
    record_count = 0
    total_amount = 0.0

    with zipfile.ZipFile(path) as zf:
        json_files = [n for n in zf.namelist() if n.endswith(".json")]
        for name in json_files:
            with zf.open(name) as f:
                try:
                    record = json.load(f)
                except json.JSONDecodeError:
                    continue
            record_count += 1
            try:
                total_amount += float(record.get("awd_amount") or 0)
            except (TypeError, ValueError):
                pass

    return record_count, total_amount


# ── Part 1b: ZIP date range check ────────────────────────────────────────────

def check_zip_dates(path: Path):
    from datetime import date
    fy_start = date(2024, 10, 1)
    fy_end   = date(2025,  9, 30)

    dates = []
    outside = 0

    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            with zf.open(name) as f:
                try:
                    record = json.load(f)
                except json.JSONDecodeError:
                    continue
            raw = record.get("awd_eff_date")
            if not raw:
                continue
            try:
                d = date.fromisoformat(raw[:10])
            except ValueError:
                continue
            dates.append(d)
            if d < fy_start or d > fy_end:
                outside += 1

    if dates:
        print(f"  Min awd_eff_date : {min(dates)}")
        print(f"  Max awd_eff_date : {max(dates)}")
    print(f"  Outside 10/01/2024-09/30/2025 : {outside:,} of {len(dates):,}")


# ── Part 2: Pull from API ─────────────────────────────────────────────────────

def fetch_api() -> tuple[int, float]:
    record_count = 0
    total_amount = 0.0
    params = dict(API_PARAMS)

    print("  Paginating API", end="", flush=True)
    while True:
        resp = requests.get(API_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()["response"]
        awards = data.get("award") or []
        if not awards:
            break

        for award in awards:
            record_count += 1
            try:
                total_amount += float(award.get("fundsObligatedAmt") or 0)
            except (TypeError, ValueError):
                pass

        total_available = int(data.get("metadata", {}).get("totalCount", 0))
        params["offset"] += len(awards)
        print(".", end="", flush=True)

        if params["offset"] >= total_available:
            break

    print()  # newline after dots
    return record_count, total_amount


# ── Part 3: Compare ───────────────────────────────────────────────────────────

def compare(zip_count, zip_total, api_count, api_total):
    count_diff  = zip_count - api_count
    dollar_diff = zip_total - api_total
    pct_count   = (count_diff  / api_count  * 100) if api_count  else float("nan")
    pct_dollars = (dollar_diff / api_total  * 100) if api_total  else float("nan")

    col = 28
    sep = "-" * 55
    print(f"\n{sep}")
    print(f"{'COMPARISON':^55}")
    print(sep)
    print(f"{'':>{col}}  {'ZIP':>12}  {'API':>12}")
    print(sep)
    print(f"{'Record count':<{col}}  {zip_count:>12,}  {api_count:>12,}")
    print(f"{'Total dollars':<{col}}  {zip_total:>12,.0f}  {api_total:>12,.0f}")
    print(sep)
    print(f"{'Count difference':<{col}}  {count_diff:>+12,}")
    print(f"{'Dollar difference':<{col}}  {dollar_diff:>+12,.0f}")
    print(f"{'Count % variance':<{col}}  {pct_count:>+11.2f}%")
    print(f"{'Dollar % variance':<{col}}  {pct_dollars:>+11.2f}%")
    print(sep)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Part 1
    print("\n-- Part 1: Parsing ZIP --")
    if not ZIP_PATH.exists():
        raise FileNotFoundError(f"ZIP not found: {ZIP_PATH}")
    zip_count, zip_total = parse_zip(ZIP_PATH)
    print(f"  Records parsed   : {zip_count:,}")
    print(f"  Total awd_amount : ${zip_total:,.0f}")
    check_zip_dates(ZIP_PATH)

    # Part 2
    print("\n-- Part 2: Fetching API --")
    api_count, api_total = fetch_api()
    print(f"  Records fetched          : {api_count:,}")
    print(f"  Total fundsObligatedAmt  : ${api_total:,.0f}")

    # Part 3
    print("\n-- Part 3: Comparison --")
    compare(zip_count, zip_total, api_count, api_total)


if __name__ == "__main__":
    main()
