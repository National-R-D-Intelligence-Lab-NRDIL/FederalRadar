"""
phase2_build_institutions_table.py
Build the institutions reference table from USASpending UEIs extracted in Phase 1.
One row per UEI — the canonical name is the most frequently used inst_name for that UEI.
Safe to re-run: drops and recreates the table.
"""

import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "federal_awards.db"


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Drop and recreate for idempotency
    conn.execute("DROP TABLE IF EXISTS institutions")
    conn.execute("""
        CREATE TABLE institutions (
            inst_uei            TEXT PRIMARY KEY,
            canonical_name      TEXT NOT NULL,
            inst_state_code     TEXT,
            uei_source          TEXT DEFAULT 'usaspending',
            samgov_legal_name   TEXT,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    print("Table created.")

    # For each UEI, pick the inst_name with the highest record count.
    # Tie-break alphabetically so results are deterministic.
    t0 = time.time()
    conn.execute("""
        INSERT INTO institutions (inst_uei, canonical_name, inst_state_code, uei_source)
        SELECT
            inst_uei,
            inst_name       AS canonical_name,
            inst_state_code,
            'usaspending'   AS uei_source
        FROM (
            SELECT
                inst_uei,
                inst_name,
                inst_state_code,
                COUNT(*) AS n,
                ROW_NUMBER() OVER (
                    PARTITION BY inst_uei
                    ORDER BY COUNT(*) DESC, inst_name ASC
                ) AS rn
            FROM awards
            WHERE inst_uei IS NOT NULL AND inst_uei != ''
            GROUP BY inst_uei, inst_name
        )
        WHERE rn = 1
    """)
    conn.commit()
    elapsed = time.time() - t0

    count = conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
    print(f"Populated {count:,} institutions in {elapsed:.1f}s")

    # Index for fast lookups
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_uei ON institutions(inst_uei)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_canonical ON institutions(canonical_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_state ON institutions(inst_state_code)")
    conn.commit()
    print("Indexes created.")

    # Spot check — peer institutions
    print("\nSpot check (peer institutions):")
    rows = conn.execute("""
        SELECT inst_uei, canonical_name, inst_state_code
        FROM institutions
        WHERE UPPER(canonical_name) LIKE '%NORTH TEXAS%'
           OR UPPER(canonical_name) LIKE '%TEXAS A&M%'
           OR UPPER(canonical_name) LIKE '%UNIVERSITY OF TEXAS AT AUSTIN%'
           OR UPPER(canonical_name) LIKE '%ARIZONA STATE%'
           OR UPPER(canonical_name) LIKE '%GEORGIA STATE%'
        ORDER BY canonical_name
        LIMIT 15
    """).fetchall()
    print(f"  {'UEI':<15} {'State':<6} {'Canonical Name'}")
    print("  " + "-" * 70)
    for uei, name, state in rows:
        print(f"  {uei:<15} {(state or ''):<6} {name}")

    conn.close()
    print("\nPhase 2 complete.")


if __name__ == "__main__":
    run()
