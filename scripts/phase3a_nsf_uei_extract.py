"""
phase3a_nsf_uei_extract.py
Extract org_uei_num from NSF raw_json into inst_uei column.
No API calls needed — UEI is already stored in raw_json from the NSF bulk data.
"""
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    total_nsf = conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nsf'"
    ).fetchone()[0]
    print(f"NSF records: {total_nsf:,}")

    t0 = time.time()
    result = conn.execute("""
        UPDATE awards
        SET inst_uei = NULLIF(TRIM(json_extract(raw_json, '$.inst.org_uei_num')), '')
        WHERE source = 'nsf'
        AND raw_json IS NOT NULL
        AND (inst_uei IS NULL OR inst_uei = '')
    """)
    conn.commit()
    elapsed = time.time() - t0
    print(f"Updated: {result.rowcount:,} records in {elapsed:.1f}s")

    # Coverage report
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            COUNT(inst_uei) as has_uei,
            COUNT(*) - COUNT(inst_uei) as missing_uei
        FROM awards WHERE source = 'nsf'
    """).fetchone()
    print(f"\nNSF UEI coverage:")
    print(f"  Total:   {row[0]:,}")
    print(f"  Has UEI: {row[1]:,}  ({row[1]/row[0]*100:.1f}%)")
    print(f"  Missing: {row[2]:,}  (pre-2022 awards, no UEI issued yet)")

    # Spot check peer institutions
    print("\nSpot check — peer institutions:")
    peers = [
        "UNIVERSITY OF NORTH TEXAS",
        "TEXAS A&M UNIVERSITY",
        "UNIVERSITY OF TEXAS AT AUSTIN",
        "ARIZONA STATE UNIVERSITY",
        "PURDUE UNIVERSITY",
    ]
    for name in peers:
        row = conn.execute("""
            SELECT inst_uei, inst_name FROM awards
            WHERE source = 'nsf' AND UPPER(inst_name) = ?
            AND inst_uei IS NOT NULL LIMIT 1
        """, (name,)).fetchone()
        if row:
            print(f"  {name}")
            print(f"    UEI: {row[0]}")
        else:
            print(f"  {name} -> no UEI found")

    conn.close()
    print("\nPhase 3a complete.")


if __name__ == "__main__":
    run()
