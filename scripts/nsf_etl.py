"""
nsf_etl.py
Loads all NSF award ZIP files from data/raw/nsf/ into federal_awards.db.
"""

import argparse
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

# Allow importing from src/
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import init_db, upsert_nsf_award, upsert_nsf_awards_batch, DB_PATH

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "nsf"
BATCH_SIZE = 500


def map_records(raw: dict) -> list:
    """One row per award PER FISCAL YEAR -- unnests oblg_fy instead of
    collapsing the award to a single lifetime-total row. Each entry's own
    fund_oblg_fiscal_yr/fund_oblg_amt (or fiscal_yr/oblg_amt for the small
    number of contract-style awards) becomes that row's fiscal_year/awd_amount.
    All other fields are constant per award and repeated on every year-row.
    A $0 entry still produces a row -- never dropped.
    """
    # institution (single dict, not a list)
    inst = raw.get("inst") or {}

    # PI: prefer entry with role 'Principal Investigator', fallback to first
    pi_list = raw.get("pi") or []
    pi_entry = next(
        (p for p in pi_list if p.get("pi_role") == "Principal Investigator"),
        pi_list[0] if pi_list else None,
    )
    pi_name = pi_entry.get("pi_full_name") if pi_entry else None

    # program element name
    pgm_ele = raw.get("pgm_ele") or []
    pgm_ele_name = pgm_ele[0].get("pgm_ele_name") if pgm_ele else None

    # No per-year obligation date exists in NSF bulk data -- the only date
    # available (awd_min_amd_letter_date) is award-level, so it's reused
    # as-is on every year-row rather than implying a false per-year date.
    obligation_date = raw.get("awd_min_amd_letter_date")

    common = {
        "awd_id":                 raw.get("awd_id"),
        "awd_titl_txt":           raw.get("awd_titl_txt"),
        "inst_name":              inst.get("inst_name"),
        "inst_state_code":        inst.get("inst_state_code"),
        "obligation_date":        obligation_date,
        "project_start_date":     raw.get("awd_eff_date"),
        "project_end_date":       raw.get("awd_exp_date"),
        "awd_abstract_narration": raw.get("awd_abstract_narration"),
        "dir_abbr":               raw.get("dir_abbr"),
        "div_abbr":               raw.get("div_abbr"),
        "pgm_ele_name":           pgm_ele_name,
        "pi_name":                pi_name,
        "agcy_id":                raw.get("agcy_id"),
        "raw_json":               json.dumps(raw),
        "source":                 "nsf",
        "opportunity_number":     None,
        "activity_code":          None,
        "nih_institute":          None,
        "direct_cost_amt":        None,
    }

    oblg_fy = raw.get("oblg_fy") or []
    records = []
    for entry in oblg_fy:
        # normal shape: {fund_oblg_fiscal_yr, fund_oblg_amt}
        # contract-style shape (e.g. 49100421C0035): {fiscal_yr, oblg_amt}
        fy_raw = entry.get("fund_oblg_fiscal_yr", entry.get("fiscal_yr"))
        amt_raw = entry.get("fund_oblg_amt", entry.get("oblg_amt"))
        try:
            fiscal_year = int(fy_raw) if fy_raw is not None else None
        except (TypeError, ValueError):
            fiscal_year = None
        try:
            awd_amount = float(amt_raw) if amt_raw is not None else None
        except (TypeError, ValueError):
            awd_amount = None
        if fiscal_year is None:
            continue
        records.append({**common, "fiscal_year": fiscal_year, "awd_amount": awd_amount})

    return records


def process_zip(zip_path: Path) -> dict:
    stats = {"total": 0, "inserted": 0, "updated": 0}

    # snapshot existing (awd_id, fiscal_year) keys for this run to track inserts vs updates
    conn = sqlite3.connect(DB_PATH)
    existing_keys = set(
        (row[0], row[1])
        for row in conn.execute("SELECT awd_id, fiscal_year FROM awards WHERE source = 'nsf'").fetchall()
    )
    conn.close()

    batch = []

    with zipfile.ZipFile(zip_path) as zf:
        json_files = [n for n in zf.namelist() if n.endswith(".json")]

        for name in json_files:
            with zf.open(name) as f:
                try:
                    raw = json.load(f)
                except json.JSONDecodeError:
                    continue

            if not raw.get("awd_id"):
                continue

            for record in map_records(raw):
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

                if stats["total"] % 1000 == 0:
                    print(
                        f"  [{zip_path.name}] "
                        f"processed={stats['total']:,}  "
                        f"inserted={stats['inserted']:,}  "
                        f"updated={stats['updated']:,}"
                    )

    if batch:
        upsert_nsf_awards_batch(batch)

    return stats


def run_summary_query():
    conn = sqlite3.connect(DB_PATH)
    print("\nSELECT fiscal_year, COUNT(*), ROUND(SUM(awd_amount)/1e6,1)")
    print("FROM awards WHERE source='nsf' GROUP BY fiscal_year ORDER BY fiscal_year DESC;\n")
    print(f"  {'fiscal_year':>12}  {'awards':>8}  {'total_millions':>15}")
    print("  " + "-" * 40)
    for row in conn.execute("""
        SELECT fiscal_year,
               COUNT(*)                          AS awards,
               ROUND(SUM(awd_amount)/1000000.0, 1) AS total_millions
        FROM awards
        WHERE source = 'nsf'
        GROUP BY fiscal_year
        ORDER BY fiscal_year DESC
    """):
        fy, awards, total_m = row
        total_m = total_m or 0.0
        print(f"  {str(fy):>12}  {awards:>8,}  {total_m:>14.1f}M")
    conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=str, default=None,
                        help="Only process the ZIP whose filename contains this year string.")
    args = parser.parse_args()

    init_db()

    zip_files = sorted(RAW_DIR.glob("*.zip"))
    if args.year:
        zip_files = [z for z in zip_files if args.year in z.name]
    if not zip_files:
        print(f"No ZIP files found in {RAW_DIR}")
        return

    print(f"Found {len(zip_files)} ZIP file(s) in {RAW_DIR}\n")

    summary = {}
    for zip_path in zip_files:
        print(f"-- Processing {zip_path.name} --")
        stats = process_zip(zip_path)
        summary[zip_path.name] = stats
        print(
            f"  Done: total={stats['total']:,}  "
            f"inserted={stats['inserted']:,}  "
            f"updated={stats['updated']:,}\n"
        )

    print("=" * 50)
    print("FINAL SUMMARY")
    print("=" * 50)
    print(f"  {'File':<25}  {'Total':>7}  {'Inserted':>9}  {'Updated':>8}")
    print("  " + "-" * 55)
    for fname, s in summary.items():
        print(f"  {fname:<25}  {s['total']:>7,}  {s['inserted']:>9,}  {s['updated']:>8,}")

    run_summary_query()


if __name__ == "__main__":
    main()
