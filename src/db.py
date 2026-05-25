"""
db.py
SQLite database setup and upsert for NSF awards.
"""

import json
import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.environ.get("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "federal_awards.db")))

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS nsf_awards (
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
    updated_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_SQL = """
INSERT INTO nsf_awards (
    awd_id, awd_titl_txt, inst_name, inst_state_code,
    awd_amount, obligation_date, project_start_date, project_end_date, awd_abstract_narration,
    dir_abbr, div_abbr, pgm_ele_name, pi_name,
    agcy_id, fiscal_year, raw_json, created_at, updated_at
) VALUES (
    :awd_id, :awd_titl_txt, :inst_name, :inst_state_code,
    :awd_amount, :obligation_date, :project_start_date, :project_end_date, :awd_abstract_narration,
    :dir_abbr, :div_abbr, :pgm_ele_name, :pi_name,
    :agcy_id, :fiscal_year, :raw_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
) ON CONFLICT(awd_id) DO UPDATE SET
    awd_titl_txt            = excluded.awd_titl_txt,
    inst_name               = excluded.inst_name,
    inst_state_code         = excluded.inst_state_code,
    awd_amount              = excluded.awd_amount,
    obligation_date         = excluded.obligation_date,
    project_start_date      = excluded.project_start_date,
    project_end_date        = excluded.project_end_date,
    awd_abstract_narration  = excluded.awd_abstract_narration,
    dir_abbr                = excluded.dir_abbr,
    div_abbr                = excluded.div_abbr,
    pgm_ele_name            = excluded.pgm_ele_name,
    pi_name                 = excluded.pi_name,
    agcy_id                 = excluded.agcy_id,
    fiscal_year             = excluded.fiscal_year,
    raw_json                = excluded.raw_json,
    updated_at              = CURRENT_TIMESTAMP;
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(CREATE_TABLE_SQL)
        conn.commit()


def upsert_nsf_award(record: dict):
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
        "pi_name":                record.get("po_sign_block_name"),
        "agcy_id":                record.get("agcy_id"),
        "fiscal_year":            record.get("fiscal_year"),
        "raw_json":               json.dumps(record),
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

    print("Tables in federal_awards.db:")
    for (name,) in tables:
        print(f"  {name}")
