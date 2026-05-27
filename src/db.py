"""
db.py
SQLite database setup and upsert for federal awards (NSF, NIH, and future agencies).
"""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "federal_awards.db")))

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS awards (
    awd_id                  TEXT PRIMARY KEY,
    awd_titl_txt            TEXT NOT NULL,
    inst_name               TEXT,
    inst_state_code         TEXT,
    awd_amount              REAL,
    obligation_date         TEXT,
    project_start_date      TEXT,
    project_end_date        TEXT,
    awd_abstract_narration  TEXT,
    dir_abbr                TEXT,
    div_abbr                TEXT,
    pgm_ele_name            TEXT,
    pi_name                 TEXT,
    agcy_id                 TEXT,
    fiscal_year             INTEGER,
    raw_json                TEXT,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- shared across agencies
    source                  TEXT,
    opportunity_number      TEXT,
    -- NIH-specific (NULL for NSF records)
    activity_code           TEXT,
    nih_institute           TEXT,
    direct_cost_amt         REAL
);
"""

UPSERT_SQL = """
INSERT INTO awards (
    awd_id, awd_titl_txt, inst_name, inst_state_code,
    awd_amount, obligation_date, project_start_date, project_end_date, awd_abstract_narration,
    dir_abbr, div_abbr, pgm_ele_name, pi_name,
    agcy_id, fiscal_year, raw_json, created_at, updated_at,
    source, opportunity_number, activity_code, nih_institute, direct_cost_amt
) VALUES (
    :awd_id, :awd_titl_txt, :inst_name, :inst_state_code,
    :awd_amount, :obligation_date, :project_start_date, :project_end_date, :awd_abstract_narration,
    :dir_abbr, :div_abbr, :pgm_ele_name, :pi_name,
    :agcy_id, :fiscal_year, :raw_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
    :source, :opportunity_number, :activity_code, :nih_institute, :direct_cost_amt
) ON CONFLICT(awd_id) DO UPDATE SET
    awd_titl_txt            = excluded.awd_titl_txt,
    inst_name               = excluded.inst_name,
    inst_state_code         = excluded.inst_state_code,
    -- Take the higher amount: total_obligated_amount only grows over time.
    -- For NIH/NSF this is a no-op (single record per award).
    awd_amount              = CASE
                                WHEN excluded.awd_amount > awards.awd_amount THEN excluded.awd_amount
                                ELSE awards.awd_amount
                              END,
    obligation_date         = excluded.obligation_date,
    project_start_date      = excluded.project_start_date,
    project_end_date        = excluded.project_end_date,
    awd_abstract_narration  = excluded.awd_abstract_narration,
    dir_abbr                = excluded.dir_abbr,
    div_abbr                = excluded.div_abbr,
    pgm_ele_name            = excluded.pgm_ele_name,
    pi_name                 = excluded.pi_name,
    agcy_id                 = excluded.agcy_id,
    -- Never overwrite fiscal_year: the first insert captures the original award year.
    -- Later transactions (continuations, revisions) must not change when the grant was born.
    fiscal_year             = awards.fiscal_year,
    raw_json                = excluded.raw_json,
    source                  = excluded.source,
    opportunity_number      = excluded.opportunity_number,
    activity_code           = excluded.activity_code,
    nih_institute           = excluded.nih_institute,
    direct_cost_amt         = excluded.direct_cost_amt,
    updated_at              = CURRENT_TIMESTAMP;
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA cache_size = -65536;")    # 64MB page cache
    conn.execute("PRAGMA temp_store = MEMORY;")    # temp tables in RAM
    conn.execute("PRAGMA mmap_size = 268435456;")  # 256MB memory-mapped I/O
    return conn


CREATE_INDEXES_SQL = [
    # Single-column indexes
    "CREATE INDEX IF NOT EXISTS idx_awards_source          ON awards(source);",
    "CREATE INDEX IF NOT EXISTS idx_awards_fiscal_year     ON awards(fiscal_year);",
    "CREATE INDEX IF NOT EXISTS idx_awards_obligation_date ON awards(obligation_date);",
    "CREATE INDEX IF NOT EXISTS idx_awards_inst_name       ON awards(inst_name);",
    "CREATE INDEX IF NOT EXISTS idx_awards_inst_state      ON awards(inst_state_code);",
    "CREATE INDEX IF NOT EXISTS idx_awards_agcy_id         ON awards(agcy_id);",
    "CREATE INDEX IF NOT EXISTS idx_awards_opportunity_num ON awards(opportunity_number);",
    "CREATE INDEX IF NOT EXISTS idx_awards_activity_code   ON awards(activity_code);",
    "CREATE INDEX IF NOT EXISTS idx_awards_nih_institute   ON awards(nih_institute);",
    # Composite indexes for common VPR query patterns
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy       ON awards(source, fiscal_year);",
    "CREATE INDEX IF NOT EXISTS idx_awards_source_inst     ON awards(source, inst_name);",
    "CREATE INDEX IF NOT EXISTS idx_awards_inst_fy         ON awards(inst_name, fiscal_year);",
]


def init_db():
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(CREATE_TABLE_SQL)
        for idx_sql in CREATE_INDEXES_SQL:
            conn.execute(idx_sql)
        conn.commit()


def migrate_db():
    """
    Idempotently upgrade an existing DB to the unified awards schema.

    Safe to run multiple times — checks column/table existence before acting.
    Call once after pulling this code onto a machine with the old nsf_awards table.
    """
    with _connect() as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}

        # Step 1: rename nsf_awards → awards (only if old name still exists)
        if "nsf_awards" in tables and "awards" not in tables:
            conn.execute("ALTER TABLE nsf_awards RENAME TO awards")
            print("  Renamed nsf_awards -> awards")

        # Step 2: add new columns (idempotent — skip if already present)
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(awards)")}

        new_columns = [
            ("source",           "TEXT"),
            ("opportunity_number", "TEXT"),
            ("activity_code",    "TEXT"),
            ("nih_institute",    "TEXT"),
            ("direct_cost_amt",  "REAL"),
        ]
        for col_name, col_type in new_columns:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE awards ADD COLUMN {col_name} {col_type}")
                print(f"  Added column: {col_name} {col_type}")

        # Step 3: backfill source = 'nsf' for existing NSF records
        updated = conn.execute(
            "UPDATE awards SET source = 'nsf' WHERE source IS NULL"
        ).rowcount
        if updated:
            print(f"  Backfilled source='nsf' for {updated:,} rows")

        conn.commit()
    print("migrate_db() complete.")


def upsert_nsf_award(record: dict):
    """Single-record NSF upsert. Prefer upsert_nsf_awards_batch() for bulk loads."""
    pi_list = record.get("pi") or []
    pi_entry = next(
        (p for p in pi_list if p.get("pi_role") == "Principal Investigator"),
        pi_list[0] if pi_list else None,
    )
    row = {
        "awd_id":                 record.get("awd_id"),
        "awd_titl_txt":           record.get("awd_titl_txt"),
        "inst_name":              (record.get("inst") or [{}])[0].get("inst_name"),
        "inst_state_code":        (record.get("inst") or [{}])[0].get("inst_state_code"),
        "awd_amount":             record.get("awd_amount"),
        "obligation_date":        record.get("obligation_date"),
        "project_start_date":     record.get("project_start_date"),
        "project_end_date":       record.get("project_end_date"),
        "awd_abstract_narration": record.get("awd_abstract_narration"),
        "dir_abbr":               record.get("dir_abbr"),
        "div_abbr":               record.get("div_abbr"),
        "pgm_ele_name":           (record.get("pgm_ele") or [{}])[0].get("pgm_ele_name"),
        "pi_name":                pi_entry.get("pi_full_name") if pi_entry else None,
        "agcy_id":                record.get("agcy_id"),
        "fiscal_year":            record.get("fiscal_year"),
        "raw_json":               json.dumps(record),
        "source":                 "nsf",
        "opportunity_number":     None,
        "activity_code":          None,
        "nih_institute":          None,
        "direct_cost_amt":        None,
    }
    with _connect() as conn:
        conn.execute(UPSERT_SQL, row)
        conn.commit()


def upsert_nsf_awards_batch(records: list) -> tuple:
    with _connect() as conn:
        conn.executemany(UPSERT_SQL, records)
        conn.commit()
    return (len(records),)


if __name__ == "__main__":
    init_db()

    with _connect() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        ).fetchall()
        cols = [row[1] for row in conn.execute("PRAGMA table_info(awards)")]

    print("Tables in federal_awards.db:")
    for (name,) in tables:
        print(f"  {name}")

    print("\nColumns in awards:")
    for col in cols:
        print(f"  {col}")
