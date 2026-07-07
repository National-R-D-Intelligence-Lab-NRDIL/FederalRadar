"""
Load data/herd_ipeds_crosswalk.csv into the herd_institutions table.

Safe to re-run — uses INSERT OR REPLACE so re-running after regenerating
the crosswalk will update all rows cleanly.

Usage:
    python scripts/load_herd_crosswalk.py
"""

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "federal_awards.db")))
CROSSWALK = Path(__file__).parent.parent / "data" / "herd_ipeds_crosswalk.csv"

UPSERT_SQL = """
INSERT INTO herd_institutions (
    unitid, ipeds_name, state, carnegie, ipeds_uei,
    awards_uei, awards_name, awards_count, awards_total_m,
    match_type, note, created_at, updated_at
) VALUES (
    :unitid, :ipeds_name, :state, :carnegie, :ipeds_uei,
    :awards_uei, :awards_name, :awards_count, :awards_total_m,
    :match_type, :note, :now, :now
)
ON CONFLICT(unitid) DO UPDATE SET
    ipeds_name     = excluded.ipeds_name,
    state          = excluded.state,
    carnegie       = excluded.carnegie,
    ipeds_uei      = excluded.ipeds_uei,
    awards_uei     = excluded.awards_uei,
    awards_name    = excluded.awards_name,
    awards_count   = excluded.awards_count,
    awards_total_m = excluded.awards_total_m,
    match_type     = excluded.match_type,
    note           = excluded.note,
    updated_at     = excluded.updated_at;
"""


def main():
    if not CROSSWALK.exists():
        print(f"ERROR: {CROSSWALK} not found. Run scripts/build_herd_crosswalk.py first.")
        return

    with open(CROSSWALK, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Crosswalk rows to load: {len(rows):,}")

    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    # Create table if it doesn't exist yet (in case init_db hasn't been re-run)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS herd_institutions (
            unitid          TEXT PRIMARY KEY,
            ipeds_name      TEXT NOT NULL,
            state           TEXT,
            carnegie        TEXT,
            ipeds_uei       TEXT,
            awards_uei      TEXT,
            awards_name     TEXT,
            awards_count    INTEGER DEFAULT 0,
            awards_total_m  REAL DEFAULT 0.0,
            match_type      TEXT,
            note            TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_herd_awards_uei ON herd_institutions(awards_uei);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_herd_state      ON herd_institutions(state);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_herd_carnegie   ON herd_institutions(carnegie);")

    now = datetime.now().isoformat()
    batch = []
    for row in rows:
        batch.append({
            "unitid":        row["unitid"],
            "ipeds_name":    row["ipeds_name"],
            "state":         row["state"],
            "carnegie":      row["carnegie"],
            "ipeds_uei":     row["ipeds_uei"],
            "awards_uei":    row["awards_uei"] or None,
            "awards_name":   row["awards_name"] or None,
            "awards_count":  int(row["awards_count"]) if row["awards_count"] else 0,
            "awards_total_m": float(row["awards_total_m"]) if row["awards_total_m"] else 0.0,
            "match_type":    row["match_type"],
            "note":          row["note"] or None,
            "now":           now,
        })

    conn.executemany(UPSERT_SQL, batch)
    conn.commit()

    # Verify
    total     = conn.execute("SELECT COUNT(*) FROM herd_institutions").fetchone()[0]
    matched   = conn.execute("SELECT COUNT(*) FROM herd_institutions WHERE awards_uei IS NOT NULL").fetchone()[0]
    no_awards = conn.execute("SELECT COUNT(*) FROM herd_institutions WHERE awards_uei IS NULL").fetchone()[0]

    print(f"\nherd_institutions table:")
    print(f"  Total rows:  {total:,}")
    print(f"  Matched:     {matched:,}  ({matched/total*100:.1f}%)")
    print(f"  No awards:   {no_awards:,}  ({no_awards/total*100:.1f}%)")

    print("\nBy Carnegie classification:")
    for carnegie, label in [("15","R1"), ("16","R2"), ("17","D/PU"), ("18","M1"), ("19","M2"), ("20","M3")]:
        n = conn.execute(
            "SELECT COUNT(*) FROM herd_institutions WHERE carnegie = ?", (carnegie,)
        ).fetchone()[0]
        m = conn.execute(
            "SELECT COUNT(*) FROM herd_institutions WHERE carnegie = ? AND awards_uei IS NOT NULL", (carnegie,)
        ).fetchone()[0]
        print(f"  C{carnegie} ({label}): {m}/{n} matched")

    print("\nBy match type:")
    for row in conn.execute(
        "SELECT match_type, COUNT(*) FROM herd_institutions GROUP BY match_type ORDER BY COUNT(*) DESC"
    ):
        print(f"  {row[0]:20s}: {row[1]}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
