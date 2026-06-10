"""
db.py
SQLite database setup and upsert for federal awards (NSF, NIH, and future agencies).
"""

import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
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
    direct_cost_amt         REAL,
    -- Institution identity (populated via UEI enrichment pipeline)
    inst_uei                TEXT,   -- SAM.gov Unique Entity Identifier
    inst_canonical_name     TEXT    -- Normalized display name tied to UEI
);
"""

CREATE_REFRESH_LOG_SQL = """
CREATE TABLE IF NOT EXISTS refresh_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    started_at      DATETIME NOT NULL,
    finished_at     DATETIME,
    status          TEXT NOT NULL DEFAULT 'running',
    records_fetched INTEGER DEFAULT 0,
    records_upserted INTEGER DEFAULT 0,
    error_message   TEXT,
    details         TEXT
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
    -- COALESCE: never overwrite good data with NULL from a bad re-fetch
    awd_titl_txt            = COALESCE(excluded.awd_titl_txt, awards.awd_titl_txt),
    inst_name               = COALESCE(excluded.inst_name, awards.inst_name),
    inst_state_code         = COALESCE(excluded.inst_state_code, awards.inst_state_code),
    -- Take the higher amount: total_obligated_amount only grows over time.
    awd_amount              = CASE
                                WHEN excluded.awd_amount > awards.awd_amount THEN excluded.awd_amount
                                ELSE awards.awd_amount
                              END,
    obligation_date         = COALESCE(excluded.obligation_date, awards.obligation_date),
    project_start_date      = COALESCE(excluded.project_start_date, awards.project_start_date),
    project_end_date        = COALESCE(excluded.project_end_date, awards.project_end_date),
    awd_abstract_narration  = COALESCE(excluded.awd_abstract_narration, awards.awd_abstract_narration),
    dir_abbr                = COALESCE(excluded.dir_abbr, awards.dir_abbr),
    div_abbr                = COALESCE(excluded.div_abbr, awards.div_abbr),
    pgm_ele_name            = COALESCE(excluded.pgm_ele_name, awards.pgm_ele_name),
    pi_name                 = COALESCE(excluded.pi_name, awards.pi_name),
    agcy_id                 = COALESCE(excluded.agcy_id, awards.agcy_id),
    -- Never overwrite fiscal_year: the first insert captures the original award year.
    fiscal_year             = awards.fiscal_year,
    raw_json                = COALESCE(excluded.raw_json, awards.raw_json),
    source                  = COALESCE(excluded.source, awards.source),
    opportunity_number      = COALESCE(excluded.opportunity_number, awards.opportunity_number),
    activity_code           = COALESCE(excluded.activity_code, awards.activity_code),
    nih_institute           = COALESCE(excluded.nih_institute, awards.nih_institute),
    direct_cost_amt         = COALESCE(excluded.direct_cost_amt, awards.direct_cost_amt),
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
    # UEI-based institution identity indexes
    "CREATE INDEX IF NOT EXISTS idx_awards_inst_uei        ON awards(inst_uei);",
    "CREATE INDEX IF NOT EXISTS idx_awards_canonical_name  ON awards(inst_canonical_name);",
    # ── UNIVERSAL (all agencies) ──────────────────────────────────────────────
    # Peer comparison queries: lets SQLite go directly to ~13 institutions' rows
    # instead of scanning the full source+FY slice (biggest win for all agencies)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_uei_fy     ON awards(source, inst_uei, fiscal_year);",
    # Canonical name queries (get_scoped_pis, peer diversification)
    "CREATE INDEX IF NOT EXISTS idx_awards_canonical_src_fy  ON awards(inst_canonical_name, source, fiscal_year);",
    # ── NIH-SPECIFIC ─────────────────────────────────────────────────────────
    # Heatmap + field_wide_stats (all-institution NIH scans)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy_nih     ON awards(source, fiscal_year, nih_institute);",
    # get_nih_institutes DISTINCT (sidebar dropdown)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_nih        ON awards(source, nih_institute);",
    # ── NSF-SPECIFIC ─────────────────────────────────────────────────────────
    # Directorate-level queries (top-level NSF)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy_dir     ON awards(source, fiscal_year, dir_abbr);",
    # Division-level queries (NSF drill-down)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy_div     ON awards(source, fiscal_year, div_abbr);",
    # Program element queries (NSF deepest level)
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy_pgm     ON awards(source, fiscal_year, pgm_ele_name);",
    # ── USASPENDING AGENCIES (DOD, DOE, NASA, ED, USDA, DOT, NEH, EPA, DHS) ──
    # CFDA / opportunity number queries
    "CREATE INDEX IF NOT EXISTS idx_awards_source_fy_opp     ON awards(source, fiscal_year, opportunity_number);",
]


CREATE_HERD_INSTITUTIONS_SQL = """
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
);
"""

CREATE_HERD_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_herd_awards_uei ON herd_institutions(awards_uei);",
    "CREATE INDEX IF NOT EXISTS idx_herd_state      ON herd_institutions(state);",
    "CREATE INDEX IF NOT EXISTS idx_herd_carnegie   ON herd_institutions(carnegie);",
]

CREATE_OPPORTUNITIES_SQL = """
CREATE TABLE IF NOT EXISTS opportunities (
    opportunity_id              TEXT PRIMARY KEY,
    opportunity_number          TEXT,
    opportunity_title           TEXT NOT NULL,
    agency_code                 TEXT,
    agency_name                 TEXT,
    record_type                 TEXT NOT NULL,
    derived_status              TEXT NOT NULL,
    opportunity_category        TEXT,
    funding_instrument_type     TEXT,
    category_of_funding_activity TEXT,
    eligible_applicants         TEXT,
    post_date                   TEXT,
    close_date                  TEXT,
    archive_date                TEXT,
    last_updated_date           TEXT,
    fiscal_year                 INTEGER,
    award_ceiling               REAL,
    award_floor                 REAL,
    estimated_total_funding     REAL,
    expected_number_of_awards   INTEGER,
    cost_sharing_required       INTEGER,
    description                 TEXT,
    estimated_post_date         TEXT,
    estimated_close_date        TEXT,
    estimated_award_date        TEXT,
    estimated_project_start     TEXT,
    grantor_contact_email       TEXT,
    grantor_contact_name        TEXT,
    extracted_date              TEXT NOT NULL,
    raw_json                    TEXT NOT NULL,
    created_at                  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at                  DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_OPPORTUNITY_CFDAS_SQL = """
CREATE TABLE IF NOT EXISTS opportunity_cfdas (
    opportunity_id  TEXT NOT NULL,
    cfda_number     TEXT NOT NULL,
    PRIMARY KEY (opportunity_id, cfda_number)
);
"""

CREATE_OPPORTUNITIES_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_opp_status_fy      ON opportunities(derived_status, fiscal_year);",
    "CREATE INDEX IF NOT EXISTS idx_opp_agency_fy      ON opportunities(agency_code, fiscal_year);",
    "CREATE INDEX IF NOT EXISTS idx_opp_instrument     ON opportunities(funding_instrument_type);",
    "CREATE INDEX IF NOT EXISTS idx_opp_number         ON opportunities(opportunity_number);",
    "CREATE INDEX IF NOT EXISTS idx_opp_extracted_date ON opportunities(extracted_date);",
    "CREATE INDEX IF NOT EXISTS idx_opp_cfda_number    ON opportunity_cfdas(cfda_number);",
]


def init_db():
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(CREATE_TABLE_SQL)
        conn.execute(CREATE_REFRESH_LOG_SQL)
        conn.execute(CREATE_HERD_INSTITUTIONS_SQL)
        conn.execute(CREATE_OPPORTUNITIES_SQL)
        conn.execute(CREATE_OPPORTUNITY_CFDAS_SQL)
        for idx_sql in CREATE_INDEXES_SQL:
            conn.execute(idx_sql)
        for idx_sql in CREATE_HERD_INDEXES_SQL:
            conn.execute(idx_sql)
        for idx_sql in CREATE_OPPORTUNITIES_INDEXES_SQL:
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


# ---------------------------------------------------------------------------
# Backup & refresh logging
# ---------------------------------------------------------------------------

BACKUP_DIR = DB_PATH.parent / "backups"
BACKUP_KEEP_DAYS = 7


def backup_db() -> Path | None:
    """Copy DB to backups/federal_awards_YYYY-MM-DD.db. Skips if today's backup exists.
    Deletes backups older than BACKUP_KEEP_DAYS."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    backup_path = BACKUP_DIR / f"federal_awards_{today}.db"
    if not backup_path.exists():
        shutil.copy2(DB_PATH, backup_path)
        print(f"  Backup: {backup_path.name} ({backup_path.stat().st_size // (1024*1024)} MB)")
    # Cleanup old backups
    cutoff = datetime.now() - timedelta(days=BACKUP_KEEP_DAYS)
    for f in BACKUP_DIR.glob("federal_awards_*.db"):
        try:
            date_str = f.stem.replace("federal_awards_", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d")
            if file_date < cutoff:
                f.unlink()
                print(f"  Deleted old backup: {f.name}")
        except ValueError:
            pass
    return backup_path


def log_refresh_start(source: str, details: str = None) -> int:
    """Log the start of a refresh job. Returns the log row ID."""
    with _connect() as conn:
        conn.execute(CREATE_REFRESH_LOG_SQL)
        cur = conn.execute(
            "INSERT INTO refresh_log (source, started_at, status, details) VALUES (?, ?, 'running', ?)",
            (source, datetime.now().isoformat(), details),
        )
        conn.commit()
        return cur.lastrowid


def log_refresh_end(log_id: int, status: str, records_fetched: int = 0,
                    records_upserted: int = 0, error_message: str = None):
    """Log the end of a refresh job."""
    with _connect() as conn:
        conn.execute(
            """UPDATE refresh_log
               SET finished_at = ?, status = ?, records_fetched = ?,
                   records_upserted = ?, error_message = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), status, records_fetched,
             records_upserted, error_message, log_id),
        )
        conn.commit()


def get_refresh_history(limit: int = 20) -> list[dict]:
    """Return recent refresh log entries."""
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM refresh_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


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
