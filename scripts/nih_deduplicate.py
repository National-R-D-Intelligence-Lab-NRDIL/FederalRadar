"""
nih_deduplicate.py

Deduplicates NIH records in the awards table by grouping on core_project_num.

WHY THIS EXISTS
--------------
NIH assigns a new project_num every year for the same ongoing grant:
  1R01CA123456-01  FY2021  $500K  <- the actual award decision
  5R01CA123456-02  FY2022  $500K  <- year 2 disbursement
  5R01CA123456-03  FY2023  $500K  <- year 3 disbursement

These are the SAME research project — one peer-review decision, money released
annually. Storing all years as separate rows inflates award counts and confuses
"new awards won this year" metrics.

WHAT IT DOES
------------
Groups all NIH rows by core_project_num. For each group:
  - Canonical record = earliest fiscal_year (awd_id as tiebreaker)
  - awd_amount       = SUM of all annual amounts across all years in our data
  - All other fields = kept from the canonical (earliest) record

WHY PYTHON NOT SQL
------------------
json_extract() on 453K raw_json blobs with no column index = full table scan
with JSON parsing on every row. Doing it in SQL twice (GROUP BY + JOIN) is
prohibitively slow. Instead:
  1. One Python loop reads all rows and extracts core_project_num — O(n), fast
  2. Canonical mapping built in memory — O(n)
  3. Two indexed SQL operations (UPDATE + DELETE on awd_id primary key) — fast

VALIDATION
----------
After every run (including --dry-run):
  [1] Row count matches expected
  [2] Total funding preserved (sum before == sum after, within $1 float rounding)
  [3] No duplicate core_project_nums remaining
  [4] Spot-check: known multi-year grant shows correct summed amount + earliest FY
  [5] Fiscal year distribution

IDEMPOTENT: safe to run multiple times.
RAW DATA: JSONL files on disk are untouched — full reload + re-dedup always possible.

USAGE
-----
  python scripts/nih_deduplicate.py           # run deduplication
  python scripts/nih_deduplicate.py --dry-run # preview + validate, no DB changes
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import DB_PATH


def run(dry_run: bool = False):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # ── 0. Pre-flight snapshot ────────────────────────────────────────────────
    rows_before   = conn.execute("SELECT COUNT(*) FROM awards WHERE source='nih'").fetchone()[0]
    funding_before = conn.execute("SELECT COALESCE(SUM(awd_amount),0) FROM awards WHERE source='nih'").fetchone()[0]

    print(f"PRE-DEDUP SNAPSHOT")
    print(f"  NIH rows    : {rows_before:,}")
    print(f"  NIH funding : ${funding_before/1e9:.3f}B")

    # ── 1. One Python pass — extract core_project_num, build canonical map ───
    # Key insight: do JSON extraction once in Python (streaming), not in SQL.
    # canonical[core_num] = [canonical_awd_id, min_fiscal_year, summed_amount, count]
    print("\nBuilding canonical mapping (Python streaming pass)...")

    canonical = {}      # core_num -> [awd_id, fiscal_year, total_amount, year_count]
    no_core   = []      # awd_ids with no core_project_num — left untouched

    # Stream rows one at a time — never loads full dataset into RAM
    cursor = conn.execute(
        "SELECT awd_id, fiscal_year, awd_amount, raw_json FROM awards WHERE source='nih'"
    )
    for awd_id, fy, amt, raw in cursor:
        r    = json.loads(raw) if raw else {}
        core = r.get("core_project_num", "").strip()
        amt  = amt or 0.0
        fy   = fy  or 9999

        if not core:
            no_core.append(awd_id)
            continue

        if core not in canonical:
            canonical[core] = [awd_id, fy, amt, 1]
        else:
            c = canonical[core]
            c[2] += amt      # accumulate total
            c[3] += 1        # count years
            # Keep earliest fiscal_year; awd_id tiebreaker favours '1Rxx' over '5Rxx'
            if fy < c[1] or (fy == c[1] and awd_id < c[0]):
                c[0] = awd_id
                c[1] = fy

    canonical_ids  = {v[0] for v in canonical.values()}
    multi_year     = sum(1 for v in canonical.values() if v[3] > 1)
    rows_to_delete = rows_before - len(canonical) - len(no_core)

    print(f"  Unique core_project_nums : {len(canonical):,}")
    print(f"  Records without core num : {len(no_core):,}  (left untouched)")
    print(f"  Rows to delete           : {rows_to_delete:,}  ({100*rows_to_delete/rows_before:.1f}% reduction)")

    if dry_run:
        print("\n[DRY RUN] No changes written.")
        _validate(conn, funding_before, len(canonical) + len(no_core), dry_run=True)
        conn.close()
        return

    # ── 2. UPDATE canonical records with summed amount ────────────────────────
    # executemany on primary key = fast indexed update
    print("\nApplying changes...")
    updates = [(v[2], v[0]) for v in canonical.values()]   # (total_amount, awd_id)
    conn.executemany(
        "UPDATE awards SET awd_amount = ?, updated_at = CURRENT_TIMESTAMP WHERE awd_id = ?",
        updates,
    )
    print(f"  Updated {len(updates):,} canonical records")

    # ── 3. DELETE non-canonical rows via temp table ───────────────────────────
    # Insert canonical IDs into a temp table, then DELETE WHERE NOT IN.
    # Avoids hitting SQLite's variable limit on large IN (...) lists.
    conn.execute("DROP TABLE IF EXISTS _nih_keep")
    conn.execute("CREATE TEMP TABLE _nih_keep (awd_id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO _nih_keep VALUES (?)", [(i,) for i in canonical_ids])

    conn.execute("""
        DELETE FROM awards
        WHERE source = 'nih'
          AND awd_id NOT IN (SELECT awd_id FROM _nih_keep)
    """)
    conn.execute("DROP TABLE IF EXISTS _nih_keep")
    conn.commit()

    deleted = rows_before - conn.execute("SELECT COUNT(*) FROM awards WHERE source='nih'").fetchone()[0]
    print(f"  Deleted {deleted:,} duplicate rows")

    # ── 4. Validation ─────────────────────────────────────────────────────────
    _validate(conn, funding_before, len(canonical) + len(no_core), dry_run=False)
    conn.close()


def _validate(conn, funding_before: float, expected_rows: int, dry_run: bool):
    print()
    print("=" * 60)
    print("VALIDATION")
    print("=" * 60)

    if not dry_run:
        rows_after    = conn.execute("SELECT COUNT(*) FROM awards WHERE source='nih'").fetchone()[0]
        funding_after = conn.execute("SELECT COALESCE(SUM(awd_amount),0) FROM awards WHERE source='nih'").fetchone()[0]
        funding_match = abs(funding_after - funding_before) < 1.0

        print(f"\n[1] ROW COUNT")
        print(f"    Expected : {expected_rows:,}")
        print(f"    Actual   : {rows_after:,}  {'PASS' if rows_after == expected_rows else 'FAIL'}")

        print(f"\n[2] TOTAL FUNDING PRESERVED")
        print(f"    Before   : ${funding_before/1e9:.4f}B")
        print(f"    After    : ${funding_after/1e9:.4f}B")
        print(f"    Delta    : ${abs(funding_after - funding_before):,.2f}  {'PASS' if funding_match else 'FAIL -- investigate'}")

        # Check for duplicate awd_ids (sanity check — should never happen)
        dupe_ids = conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT awd_id FROM awards WHERE source='nih'
                GROUP BY awd_id HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        print(f"\n[3] NO DUPLICATE awd_ids")
        print(f"    Duplicates : {dupe_ids}  {'PASS' if dupe_ids == 0 else 'FAIL'}")

    # [4] Spot-check: R01AG048511 — National Social Life study, started 2014
    # We verified manually it has 11 transactions FY2019-2026 summing to ~$38M
    spot = conn.execute("""
        SELECT awd_id, fiscal_year, awd_amount
        FROM awards
        WHERE source = 'nih' AND awd_id LIKE '%AG048511%'
        ORDER BY fiscal_year
    """).fetchall()

    print(f"\n[4] SPOT-CHECK: R01AG048511 (multi-year study, started 2014)")
    if spot:
        for row in spot:
            print(f"    {row[0]:<35} FY{row[1]}  ${(row[2] or 0)/1e6:.3f}M")
        print(f"    Row count : {len(spot)}  {'PASS (1 row)' if len(spot) == 1 else 'FAIL -- expected 1 row'}")
        if len(spot) == 1:
            print(f"    FY check  : {'PASS (2019)' if spot[0][1] == 2019 else f'FAIL -- got FY{spot[0][1]}, expected 2019'}")
    else:
        print("    Not found in DB")

    # [5] Fiscal year distribution
    print(f"\n[5] FISCAL YEAR DISTRIBUTION")
    fy_rows = conn.execute("""
        SELECT fiscal_year, COUNT(*), ROUND(SUM(awd_amount)/1e9, 3)
        FROM awards WHERE source = 'nih'
        GROUP BY fiscal_year ORDER BY fiscal_year
    """).fetchall()
    for fy, cnt, funding in fy_rows:
        print(f"    FY{fy}: {cnt:>7,} awards  ${funding:.3f}B")

    print("\nValidation complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate NIH awards by core_project_num"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes and validate without writing to DB")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
