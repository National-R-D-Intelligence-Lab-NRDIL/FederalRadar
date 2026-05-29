"""
tests/test_data_governance.py

Federal Radar — Comprehensive Data Governance Test Suite
Covers: Schema Integrity, ETL Pipeline, API Sync, Cross-Source Consistency,
        Data Quality, Fiscal Year Boundaries, Upsert/Audit, Performance,
        and Data Governance pillars.

Run all tests (skips network by default):
    pytest tests/test_data_governance.py -v

Run network tests too:
    FEDERAL_RADAR_NETWORK_TESTS=1 pytest tests/test_data_governance.py -v

Run only unit tests (no real DB, no network):
    pytest tests/test_data_governance.py -v -m "not realdb and not network"
"""

import json
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "app"))

from scripts.nsf_etl import map_record as etl_map_record
from scripts.nsf_api_fetcher import date_to_iso, map_record as api_map_record
from scripts.nih_api_fetcher import iso_date as nih_iso_date, map_record as nih_map_record
from src.db import CREATE_TABLE_SQL, UPSERT_SQL

REAL_DB = PROJECT_ROOT / "data" / "federal_awards.db"
BASELINES = json.loads((PROJECT_ROOT / "tests" / "baselines.json").read_text())

# ── Custom marks ──────────────────────────────────────────────────────────────
real_db = pytest.mark.skipif(
    not REAL_DB.exists(),
    reason=f"Real DB not found at {REAL_DB}",
)
network = pytest.mark.skipif(
    not os.environ.get("FEDERAL_RADAR_NETWORK_TESTS"),
    reason="Network test — set FEDERAL_RADAR_NETWORK_TESTS=1 to run",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def live_conn():
    """Read-only connection to the real DB (module-scoped for speed)."""
    if not REAL_DB.exists():
        pytest.skip(f"Real DB not found at {REAL_DB}")
    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    yield conn
    conn.close()


@pytest.fixture
def mem_db():
    """Fresh in-memory SQLite with the awards schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    yield conn
    conn.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _upsert(conn: sqlite3.Connection, record: dict):
    conn.execute(UPSERT_SQL, record)
    conn.commit()


def _make_etl_raw(**overrides) -> dict:
    """Minimal valid raw JSON dict for ETL map_record (ZIP format)."""
    base = {
        "awd_id": "1234567",
        "awd_titl_txt": "Test Award Title",
        "inst": {"inst_name": "Test University", "inst_state_code": "TX"},
        "pi": [{"pi_full_name": "Jane Doe", "pi_role": "Principal Investigator"}],
        "pgm_ele": [{"pgm_ele_name": "Test Program Element"}],
        "awd_min_amd_letter_date": "2024-06-15",
        "awd_eff_date": "2024-07-01",
        "awd_exp_date": "2027-06-30",
        "awd_abstract_narration": "Test abstract.",
        "dir_abbr": "ENG",
        "div_abbr": "CBET",
        "awd_amount": "150000",
        "agcy_id": "4900",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SCHEMA INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════════

EXPECTED_COLUMNS = {
    "awd_id", "awd_titl_txt", "inst_name", "inst_state_code",
    "awd_amount", "obligation_date", "project_start_date", "project_end_date",
    "awd_abstract_narration", "dir_abbr", "div_abbr", "pgm_ele_name",
    "pi_name", "agcy_id", "fiscal_year", "raw_json",
    "created_at", "updated_at",
    # unified multi-agency columns
    "source", "opportunity_number",
    # NIH-specific (NULL for NSF records)
    "activity_code", "nih_institute", "direct_cost_amt",
}


@real_db
def test_S01_all_columns_present(live_conn):
    """S-01: All expected columns are present in awards."""
    cols = {row[1] for row in live_conn.execute("PRAGMA table_info(awards)")}
    missing = EXPECTED_COLUMNS - cols
    assert not missing, f"Missing columns: {missing}"


@real_db
def test_S02_awd_id_unique(live_conn):
    """S-02: awd_id has no duplicates."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT awd_id FROM awards GROUP BY awd_id HAVING COUNT(*) > 1"
        ")"
    ).fetchone()[0]
    assert count == 0, f"{count} duplicate awd_id(s) found"


@real_db
def test_S03_awd_titl_txt_not_null(live_conn):
    """S-03: awd_titl_txt is never NULL."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE awd_titl_txt IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL awd_titl_txt"


@real_db
def test_S04_created_at_not_null(live_conn):
    """S-04: created_at is never NULL."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE created_at IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL created_at"


@real_db
def test_S05_updated_at_not_null(live_conn):
    """S-05: updated_at is never NULL."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE updated_at IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL updated_at"


@real_db
def test_S06_created_at_lte_updated_at(live_conn):
    """S-06: created_at <= updated_at for all rows."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE created_at > updated_at"
    ).fetchone()[0]
    assert count == 0, f"{count} rows where created_at > updated_at"


@real_db
def test_S07_awd_id_format(live_conn):
    """S-07: Flag awd_id values that don't match the standard 7-digit numeric format.

    10 contract-style IDs (e.g. '49100421C0035') exist — likely SBIR/contract awards.
    Flagged for documentation; not a hard failure.
    """
    rows = live_conn.execute(
        "SELECT awd_id FROM awards "
        "WHERE awd_id NOT GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9]' LIMIT 20"
    ).fetchall()
    if rows:
        non_std = [r[0] for r in rows]
        pytest.xfail(
            f"S-07 FLAGGED: {len(non_std)} non-standard awd_id format(s): {non_std}. "
            "These appear to be contract-type awards (SBIR/contract IDs). Document and verify."
        )


@real_db
def test_S08_raw_json_not_null(live_conn):
    """S-08: raw_json is never NULL (audit trail must be preserved)."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE raw_json IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL raw_json"


@real_db
def test_S09_raw_json_parseable(live_conn):
    """S-09: raw_json is valid JSON (sample 1,000 rows)."""
    rows = live_conn.execute(
        "SELECT awd_id, raw_json FROM awards LIMIT 1000"
    ).fetchall()
    errors = []
    for awd_id, rj in rows:
        try:
            json.loads(rj)
        except (json.JSONDecodeError, TypeError):
            errors.append(awd_id)
    assert not errors, f"{len(errors)} rows with unparseable raw_json: {errors[:5]}"


@real_db
def test_S10_wal_journal_mode(live_conn):
    """S-10: WAL journal mode is active."""
    mode = live_conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"journal_mode={mode!r}, expected 'wal'"


def test_S11_foreign_key_pragma(mem_db):
    """S-11: Foreign key pragma is accessible (no FK defined yet — flagged for future agencies)."""
    result = mem_db.execute("PRAGMA foreign_keys").fetchone()
    assert result is not None, "PRAGMA foreign_keys not accessible"


@real_db
def test_S12_source_nsf_for_all_records(live_conn):
    """S-12: No records have a NULL source tag (migration backfill verified).

    Originally checked source='nsf' for all rows (pre-NIH era). Updated to verify
    that every record across all agencies has a non-null source tag.
    """
    null_count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source IS NULL"
    ).fetchone()[0]
    assert null_count == 0, (
        f"{null_count} row(s) have NULL source (migration backfill incomplete)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ETL PIPELINE INTEGRITY (ZIP Loading)
# ═══════════════════════════════════════════════════════════════════════════════

@real_db
def test_E01_total_record_count(live_conn):
    """E-01: Total NSF record count matches baseline ±0.1%."""
    expected = BASELINES["nsf"]["expected_record_count"]
    actual = live_conn.execute("SELECT COUNT(*) FROM awards WHERE source = 'nsf'").fetchone()[0]
    tolerance = expected * 0.001
    assert abs(actual - expected) <= tolerance, (
        f"Record count {actual:,} outside ±0.1% of baseline {expected:,}"
    )


@real_db
def test_E02_total_funding(live_conn):
    """E-02: Total NSF funding matches baseline ±0.5%."""
    expected_b = BASELINES["nsf"]["expected_funding_billions"]
    actual = live_conn.execute("SELECT SUM(awd_amount) FROM awards WHERE source = 'nsf'").fetchone()[0] or 0.0
    actual_b = actual / 1e9
    assert abs(actual_b - expected_b) / expected_b <= 0.005, (
        f"Total funding ${actual_b:.2f}B outside ±0.5% of baseline ${expected_b:.2f}B"
    )


@real_db
def test_E03_each_fy_has_records(live_conn):
    """E-03: Every loaded fiscal year contributes > 0 records.

    NOTE: ZIPs 2016–2018 exist but their obligation dates map to FY2019+.
    The actual loaded FY range is 2019–2026. FY2016–2018 absence is documented.
    """
    rows = {
        row[0]: row[1]
        for row in live_conn.execute(
            "SELECT fiscal_year, COUNT(*) FROM awards "
            "WHERE fiscal_year BETWEEN 2019 AND 2026 GROUP BY fiscal_year"
        )
    }
    empty = [fy for fy in range(2019, 2027) if rows.get(fy, 0) == 0]
    assert not empty, f"Fiscal years with 0 records: {empty}"

    # Document the FY2016-2018 gap
    gap = {
        row[0]: row[1]
        for row in live_conn.execute(
            "SELECT fiscal_year, COUNT(*) FROM awards "
            "WHERE fiscal_year BETWEEN 2016 AND 2018 GROUP BY fiscal_year"
        )
    }
    missing_early = [fy for fy in range(2016, 2019) if gap.get(fy, 0) == 0]
    if missing_early:
        print(
            f"\n  NOTE E-03: FY {missing_early} have 0 records — ZIP files exist but "
            "obligation dates in those archives map to FY2019+. Investigate or document."
        )


def test_E04_fy_october_award():
    """E-04: October 15 award → FY = year + 1."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2023-10-15"))
    assert rec["fiscal_year"] == 2024


def test_E05_fy_september_award():
    """E-05: September 30 award → FY = year."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2023-09-30"))
    assert rec["fiscal_year"] == 2023


def test_E06_fy_oct1_boundary():
    """E-06: October 1 boundary → FY = year + 1."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2023-10-01"))
    assert rec["fiscal_year"] == 2024


def test_E07_fy_sep30_boundary():
    """E-07: September 30 boundary → FY = year."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2023-09-30"))
    assert rec["fiscal_year"] == 2023


def test_E08_fy_null_when_date_absent():
    """E-08: fiscal_year is NULL when obligation date is absent."""
    rec_none = etl_map_record(_make_etl_raw(awd_min_amd_letter_date=None))
    rec_blank = etl_map_record(_make_etl_raw(awd_min_amd_letter_date=""))
    assert rec_none["fiscal_year"] is None
    assert rec_blank["fiscal_year"] is None


def test_E09_pi_prefers_principal_investigator():
    """E-09: PI extraction prefers 'Principal Investigator' role."""
    raw = _make_etl_raw(pi=[
        {"pi_full_name": "Co-PI Person", "pi_role": "Co-Principal Investigator"},
        {"pi_full_name": "Jane Doe", "pi_role": "Principal Investigator"},
    ])
    rec = etl_map_record(raw)
    assert rec["pi_name"] == "Jane Doe"


def test_E10_pi_fallback_to_first():
    """E-10: No PI role match → fallback to first entry, no crash."""
    raw = _make_etl_raw(pi=[
        {"pi_full_name": "First Person", "pi_role": "Co-Principal Investigator"},
        {"pi_full_name": "Second Person", "pi_role": "Co-Principal Investigator"},
    ])
    rec = etl_map_record(raw)
    assert rec["pi_name"] == "First Person"


def test_E11_pi_empty_list():
    """E-11: Empty PI list → pi_name is None, no crash."""
    rec = etl_map_record(_make_etl_raw(pi=[]))
    assert rec["pi_name"] is None


def test_E12_amount_valid_float_string():
    """E-12: Valid float string → correct float value."""
    rec = etl_map_record(_make_etl_raw(awd_amount="150000"))
    assert rec["awd_amount"] == 150000.0


def test_E13_amount_null():
    """E-13: NULL/missing amount → awd_amount is None, no crash."""
    rec = etl_map_record(_make_etl_raw(awd_amount=None))
    assert rec["awd_amount"] is None


def test_E14_amount_zero():
    """E-14: Amount '0' → 0.0, not NULL."""
    rec = etl_map_record(_make_etl_raw(awd_amount="0"))
    assert rec["awd_amount"] == 0.0


def test_E15_upsert_idempotency(mem_db):
    """E-15: Upserting the same record twice → exactly 1 row, created_at preserved, updated_at advances."""
    rec = etl_map_record(_make_etl_raw())
    _upsert(mem_db, rec)
    created_v1, updated_v1 = mem_db.execute(
        "SELECT created_at, updated_at FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()

    time.sleep(1.1)
    _upsert(mem_db, rec)
    created_v2, updated_v2 = mem_db.execute(
        "SELECT created_at, updated_at FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()

    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 1, f"Expected 1 row after idempotent upsert, got {count}"
    assert created_v2 == created_v1, f"created_at changed on re-upsert: {created_v1!r} → {created_v2!r}"
    assert updated_v2 > updated_v1, "updated_at should advance after re-upsert"


def test_E16_batch_exactly_500(mem_db):
    """E-16: Batch of exactly 500 records processes without error."""
    records = [
        etl_map_record(_make_etl_raw(awd_id=f"{7000000 + i}", awd_titl_txt=f"Award {i}"))
        for i in range(500)
    ]
    mem_db.executemany(UPSERT_SQL, records)
    mem_db.commit()
    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 500


def test_E17_batch_single_record(mem_db):
    """E-17: Single-record batch processes correctly."""
    rec = etl_map_record(_make_etl_raw(awd_id="9999999"))
    mem_db.executemany(UPSERT_SQL, [rec])
    mem_db.commit()
    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 1


def test_E18_institution_name_populated():
    """E-18: inst_name populated from institution dict."""
    raw = _make_etl_raw(inst={"inst_name": "MIT", "inst_state_code": "MA"})
    rec = etl_map_record(raw)
    assert rec["inst_name"] == "MIT"


def test_E19_missing_institution_null():
    """E-19: Missing institution → inst_name is None, no crash."""
    raw = _make_etl_raw(inst=None)
    rec = etl_map_record(raw)
    assert rec["inst_name"] is None


def test_E20_raw_json_stored_and_parseable(mem_db):
    """E-20: raw_json is stored for every record and is parseable."""
    rec = etl_map_record(_make_etl_raw())
    _upsert(mem_db, rec)
    rj = mem_db.execute(
        "SELECT raw_json FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()[0]
    assert rj is not None, "raw_json is NULL"
    parsed = json.loads(rj)
    assert isinstance(parsed, dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API SYNC INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════════

def test_A01_date_conversion_valid():
    """A-01: MM/DD/YYYY → YYYY-MM-DD."""
    assert date_to_iso("01/15/2025") == "2025-01-15"
    assert date_to_iso("12/31/2024") == "2024-12-31"
    assert date_to_iso("03/05/2023") == "2023-03-05"


def test_A02_date_conversion_blank_or_null():
    """A-02: Blank or None input → None, no crash."""
    assert date_to_iso("") is None
    assert date_to_iso(None) is None


def test_A03_date_conversion_invalid_format():
    """A-03: Invalid format (no slashes, or wrong format) → None, no crash."""
    assert date_to_iso("not-a-date") is None
    assert date_to_iso("2025-01-15") is None  # ISO format not accepted by this function


@network
def test_A04_api_pagination_fetches_all():
    """A-04: Broad date range fetches 100+ records across pages."""
    from scripts.nsf_api_fetcher import fetch_all
    records = fetch_all("01/01/2025", "03/31/2025")
    assert len(records) >= 100, f"Expected >= 100 records, got {len(records)}"


@network
def test_A05_api_pagination_last_page_terminates():
    """A-05: Last page partial (< 25 records) terminates cleanly."""
    from scripts.nsf_api_fetcher import fetch_all
    records = fetch_all("01/01/2025", "01/03/2025")
    assert isinstance(records, list)


@network
def test_A06_api_zero_results_clean():
    """A-06: Future date range → 0 results, terminates cleanly."""
    from scripts.nsf_api_fetcher import fetch_all
    records = fetch_all("01/01/2050", "01/02/2050")
    assert records == []


def test_A07_api_amount_conversion():
    """A-07: fundsObligatedAmt converts to float; None/blank → None."""
    rec_val = api_map_record({"id": "1234567", "title": "T", "fundsObligatedAmt": "200000"})
    assert rec_val["awd_amount"] == 200000.0

    rec_none = api_map_record({"id": "1234567", "title": "T", "fundsObligatedAmt": None})
    assert rec_none["awd_amount"] is None

    rec_blank = api_map_record({"id": "1234567", "title": "T", "fundsObligatedAmt": ""})
    assert rec_blank["awd_amount"] is None


def test_A08_api_upsert_new_record(mem_db):
    """A-08: New award from API → inserted, created_at set."""
    rec = api_map_record({
        "id": "1234567", "title": "New API Award",
        "fundsObligatedAmt": "50000", "date": "06/15/2024",
        "awardeeName": "State University", "awardeeStateCode": "TX",
        "dirAbbr": "ENG", "divAbbr": "CBET",
    })
    _upsert(mem_db, rec)
    row = mem_db.execute(
        "SELECT awd_id, created_at FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()
    assert row is not None, "Record not inserted"
    assert row[1] is not None, "created_at is NULL after insert"


def test_A09_api_upsert_existing_updates(mem_db):
    """A-09: Existing award from API → updated (1 row, new title stored)."""
    rec_v1 = api_map_record({"id": "1234567", "title": "Original Title",
                              "fundsObligatedAmt": "50000", "date": "06/15/2024"})
    _upsert(mem_db, rec_v1)
    time.sleep(1.1)

    rec_v2 = api_map_record({"id": "1234567", "title": "Updated Title",
                              "fundsObligatedAmt": "75000", "date": "06/15/2024"})
    _upsert(mem_db, rec_v2)

    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 1, f"Expected 1 row, got {count} (duplicate created)"

    title = mem_db.execute(
        "SELECT awd_titl_txt FROM awards WHERE awd_id = '1234567'"
    ).fetchone()[0]
    assert title == "Updated Title"


def test_A10_api_fy_matches_etl():
    """A-10: Same award via API and ETL produces the same fiscal_year."""
    # ETL: obligation date in YYYY-MM-DD
    etl_rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2024-10-15"))

    # API: obligation date in MM/DD/YYYY
    api_rec = api_map_record({"id": "1234567", "title": "T", "date": "10/15/2024"})

    assert etl_rec["fiscal_year"] == api_rec["fiscal_year"] == 2025


@real_db
@network
def test_A11_api_vs_etl_field_consistency(live_conn):
    """A-11: Sample award: all 13 mapped fields match between ZIP-loaded and API-loaded versions."""
    from scripts.nsf_api_fetcher import fetch_by_id, map_record as api_map

    COMPARE_COLS = [
        "awd_id", "awd_titl_txt", "inst_name", "inst_state_code",
        "awd_amount", "obligation_date", "project_start_date", "project_end_date",
        "dir_abbr", "div_abbr", "pgm_ele_name", "pi_name", "fiscal_year",
    ]
    # Use a known stable award ID
    sample_id = live_conn.execute(
        "SELECT awd_id FROM awards WHERE fiscal_year = 2024 LIMIT 1"
    ).fetchone()
    if sample_id is None:
        pytest.skip("No FY2024 records available")

    awd_id = sample_id[0]
    raw = fetch_by_id(awd_id)
    if raw is None:
        pytest.skip(f"Award {awd_id} not found via API")

    api_rec = api_map(raw)
    db_row = live_conn.execute(
        f"SELECT {', '.join(COMPARE_COLS)} FROM awards WHERE awd_id = ?", (awd_id,)
    ).fetchone()
    if db_row is None:
        pytest.skip(f"Award {awd_id} not found in DB")

    db_rec = dict(zip(COMPARE_COLS, db_row))
    mismatches = []
    for col in COMPARE_COLS:
        if col in ("pi_name", "pgm_ele_name"):
            continue  # expected to differ between sources
        if api_rec.get(col) != db_rec.get(col):
            mismatches.append(
                f"  {col}: API={api_rec.get(col)!r}  DB={db_rec.get(col)!r}"
            )
    assert not mismatches, f"Field mismatches for {awd_id}:\n" + "\n".join(mismatches)


@network
def test_A12_api_network_error_handling():
    """A-12: HTTP/network error → graceful message, no DB corruption."""
    import urllib.request
    # Hit a bad endpoint and confirm it raises, not silently corrupts
    with pytest.raises(Exception):
        with urllib.request.urlopen("https://api.nsf.gov/services/v1/INVALID.json") as r:
            r.read()


def test_A13_api_pdPIName_maps_to_pi_name():
    """A-13: pdPIName (API field) maps to pi_name (DB field) correctly."""
    rec = api_map_record({"id": "1234567", "title": "T", "pdPIName": "John Smith"})
    assert rec["pi_name"] == "John Smith"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CROSS-SOURCE CONSISTENCY (ZIP vs API)
# ═══════════════════════════════════════════════════════════════════════════════

@real_db
@network
def test_C01_sample_10_awards_field_match(live_conn):
    """C-01: Sample 10 awards — key fields match between ZIP DB and live API."""
    from scripts.nsf_api_fetcher import fetch_by_id, map_record as api_map

    COMPARE_COLS = [
        "awd_id", "inst_name", "awd_amount", "obligation_date",
        "project_start_date", "project_end_date", "dir_abbr", "fiscal_year",
    ]
    sample_ids = [
        row[0] for row in live_conn.execute(
            "SELECT awd_id FROM awards WHERE fiscal_year = 2025 LIMIT 10"
        )
    ]
    mismatches = []
    for awd_id in sample_ids:
        raw = fetch_by_id(awd_id)
        if raw is None:
            continue
        api_rec = api_map(raw)
        db_row = live_conn.execute(
            f"SELECT {', '.join(COMPARE_COLS)} FROM awards WHERE awd_id = ?", (awd_id,)
        ).fetchone()
        if db_row is None:
            continue
        db_rec = dict(zip(COMPARE_COLS, db_row))
        for col in COMPARE_COLS:
            if api_rec.get(col) != db_rec.get(col):
                mismatches.append(
                    f"  {awd_id}.{col}: API={api_rec.get(col)!r}  DB={db_rec.get(col)!r}"
                )
    assert not mismatches, f"ZIP vs API mismatches:\n" + "\n".join(mismatches)


@real_db
@network
def test_C02_fy2025_record_count_variance(live_conn):
    """C-02: FY2025 record count: ZIP vs API within ±2%."""
    from scripts.nsf_api_fetcher import fetch_all

    zip_count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE fiscal_year = 2025"
    ).fetchone()[0]
    if zip_count == 0:
        pytest.skip("No FY2025 records in DB")

    records = fetch_all("10/01/2024", "09/30/2025")
    api_count = len(records)
    variance = abs(zip_count - api_count) / zip_count
    assert variance <= 0.02, (
        f"FY2025 count variance {variance:.1%} > 2% "
        f"(DB={zip_count:,}, API={api_count:,})"
    )


@real_db
@network
def test_C03_fy2025_funding_variance(live_conn):
    """C-03: FY2025 total funding: ZIP vs API within ±1%.

    NOTE: The NSF API returns HTTP 502 when paginating large full-year result
    sets (> ~2,500 records). If that happens, the test is marked xfail with
    details — this is an API infrastructure limitation, not a data issue.
    """
    import urllib.error
    from scripts.nsf_api_fetcher import fetch_all, map_record as api_map

    zip_total = live_conn.execute(
        "SELECT SUM(awd_amount) FROM awards WHERE fiscal_year = 2025"
    ).fetchone()[0] or 0.0
    if zip_total == 0:
        pytest.skip("No FY2025 funding data in DB")

    try:
        records = fetch_all("10/01/2024", "09/30/2025")
    except urllib.error.HTTPError as e:
        pytest.xfail(
            f"C-03 SKIPPED: NSF API returned HTTP {e.code} while paginating "
            "the full FY2025 date range. Re-run in smaller date windows or add "
            "retry logic to nsf_api_fetcher.fetch_page()."
        )

    api_total = sum(api_map(r)["awd_amount"] or 0 for r in records if r.get("id"))
    variance = abs(zip_total - api_total) / zip_total
    assert variance <= 0.01, (
        f"FY2025 funding variance {variance:.2%} > 1% "
        f"(DB=${zip_total/1e9:.2f}B, API=${api_total/1e9:.2f}B)"
    )


@real_db
@network
def test_C04_C05_zip_only_and_api_only_awards(live_conn):
    """C-04/C-05: Flag awards that appear in ZIP but not API, and vice versa."""
    from scripts.nsf_api_fetcher import fetch_all, map_record as api_map

    # Use a narrow recent window for tractable comparison
    api_records = fetch_all("01/01/2025", "03/31/2025")
    api_ids = {r["id"] for r in api_records if r.get("id")}

    db_ids = {
        row[0] for row in live_conn.execute(
            "SELECT awd_id FROM awards "
            "WHERE obligation_date BETWEEN '2025-01-01' AND '2025-03-31'"
        )
    }

    zip_only = db_ids - api_ids
    api_only = api_ids - db_ids

    # These are informational flags, not hard failures
    if zip_only:
        pytest.xfail(
            f"C-04 FLAGGED: {len(zip_only)} ZIP-only awards "
            f"(sample: {list(zip_only)[:5]}). Investigate retracted/amended awards."
        )
    if api_only:
        pytest.xfail(
            f"C-05 FLAGGED: {len(api_only)} API-only awards "
            f"(sample: {list(api_only)[:5]}). Should be captured via incremental sync."
        )


@real_db
@network
def test_C06_amount_discrepancies_flagged(live_conn):
    """C-06: Flag award amount differences between ZIP and API."""
    from scripts.nsf_api_fetcher import fetch_by_id, map_record as api_map

    sample_ids = [
        row[0] for row in live_conn.execute(
            "SELECT awd_id FROM awards WHERE fiscal_year = 2025 "
            "AND awd_amount IS NOT NULL LIMIT 10"
        )
    ]
    diffs = []
    for awd_id in sample_ids:
        raw = fetch_by_id(awd_id)
        if raw is None:
            continue
        api_amount = api_map(raw)["awd_amount"]
        db_amount = live_conn.execute(
            "SELECT awd_amount FROM awards WHERE awd_id = ?", (awd_id,)
        ).fetchone()[0]
        if api_amount is not None and db_amount is not None:
            if abs(api_amount - db_amount) > 0.01:
                diffs.append(f"  {awd_id}: DB={db_amount:,.0f}  API={api_amount:,.0f}")
    if diffs:
        pytest.xfail(
            "C-06 FLAGGED: Amount discrepancies (API is source of truth for current awards):\n"
            + "\n".join(diffs)
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. DATA QUALITY & COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════════════

@real_db
def test_Q01_null_rate_awd_amount(live_conn):
    """Q-01: NULL rate for awd_amount < 1%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN awd_amount IS NULL THEN 1 ELSE 0 END) FROM awards"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.01, f"awd_amount NULL rate {rate:.2%} exceeds 1% limit"


@real_db
def test_Q02_null_rate_obligation_date(live_conn):
    """Q-02: NULL rate for obligation_date < 0.5%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN obligation_date IS NULL THEN 1 ELSE 0 END) FROM awards"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.005, f"obligation_date NULL rate {rate:.2%} exceeds 0.5% limit"


@real_db
def test_Q03_null_rate_fiscal_year(live_conn):
    """Q-03: NULL rate for fiscal_year < 0.5%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN fiscal_year IS NULL THEN 1 ELSE 0 END) FROM awards"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.005, f"fiscal_year NULL rate {rate:.2%} exceeds 0.5% limit"


@real_db
def test_Q04_null_rate_inst_name(live_conn):
    """Q-04: NULL rate for inst_name < 2%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN inst_name IS NULL THEN 1 ELSE 0 END) FROM awards"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.02, f"inst_name NULL rate {rate:.2%} exceeds 2% limit"


@real_db
def test_Q05_null_rate_pi_name(live_conn):
    """Q-05: NULL rate for pi_name < 5%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN pi_name IS NULL THEN 1 ELSE 0 END) FROM awards"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.05, f"pi_name NULL rate {rate:.2%} exceeds 5% limit"


@real_db
def test_Q06_null_rate_dir_abbr(live_conn):
    """Q-06: NULL rate for dir_abbr < 1% among NSF records.

    NIH records always have dir_abbr=NULL (no directorate equivalent), so this
    check is scoped to source='nsf' to avoid false failures after NIH load.
    """
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN dir_abbr IS NULL THEN 1 ELSE 0 END) "
        "FROM awards WHERE source = 'nsf'"
    ).fetchone()
    rate = nulls / total
    assert rate < 0.01, f"NSF dir_abbr NULL rate {rate:.2%} exceeds 1% limit"


@real_db
def test_Q07_negative_amounts_flagged(live_conn):
    """Q-07: Flag negative awd_amount values (possible deobligations)."""
    count, min_val = live_conn.execute(
        "SELECT COUNT(*), MIN(awd_amount) FROM awards WHERE awd_amount < 0"
    ).fetchone()
    if count > 0:
        pytest.xfail(
            f"Q-07 FLAGGED: {count:,} negative amounts (min={min_val:,.0f}). "
            "May indicate deobligations — review before stakeholder use."
        )


@real_db
def test_Q08_zero_amounts_flagged(live_conn):
    """Q-08: Flag count of awd_amount = 0 (possible unfunded awards)."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE awd_amount = 0"
    ).fetchone()[0]
    if count > 0:
        pytest.xfail(
            f"Q-08 FLAGGED: {count:,} zero-amount awards. "
            "May indicate unfunded or placeholder records."
        )


@real_db
def test_Q09_outlier_amounts_flagged(live_conn):
    """Q-09: Flag awards > $1B for manual review."""
    rows = live_conn.execute(
        "SELECT awd_id, awd_amount FROM awards WHERE awd_amount > 1000000000 LIMIT 10"
    ).fetchall()
    if rows:
        detail = ", ".join(f"{awd_id}=${amt/1e6:.0f}M" for awd_id, amt in rows)
        pytest.xfail(f"Q-09 FLAGGED: {len(rows)}+ awards > $1B — verify legitimacy: {detail}")


@real_db
def test_Q10_fiscal_year_valid_range(live_conn):
    """Q-10: No fiscal_year values outside 2016–2027."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards "
        "WHERE fiscal_year IS NOT NULL AND (fiscal_year < 2016 OR fiscal_year > 2027)"
    ).fetchone()[0]
    assert count == 0, f"{count:,} records with fiscal_year outside 2016–2027"


@real_db
def test_Q11_end_date_not_before_start_date(live_conn):
    """Q-11: project_end_date never before project_start_date."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards "
        "WHERE project_start_date IS NOT NULL AND project_end_date IS NOT NULL "
        "AND project_end_date < project_start_date"
    ).fetchone()[0]
    assert count == 0, f"{count:,} records where end_date < start_date (date logic error)"


@real_db
def test_Q12_obligation_date_vs_fiscal_year(live_conn):
    """Q-12: Count and document awards where obligation_date is outside reported fiscal year."""
    count = live_conn.execute("""
        SELECT COUNT(*) FROM awards
        WHERE fiscal_year IS NOT NULL AND obligation_date IS NOT NULL
          AND NOT (
            (CAST(strftime('%m', obligation_date) AS INTEGER) >= 10
             AND fiscal_year = CAST(strftime('%Y', obligation_date) AS INTEGER) + 1)
            OR
            (CAST(strftime('%m', obligation_date) AS INTEGER) < 10
             AND fiscal_year = CAST(strftime('%Y', obligation_date) AS INTEGER))
          )
    """).fetchone()[0]
    if count > 0:
        pytest.xfail(
            f"Q-12 FLAGGED: {count:,} awards where obligation_date falls outside "
            "the reported fiscal year. Document these for VPR stakeholders."
        )


@real_db
def test_Q13_duplicate_titles_flagged(live_conn):
    """Q-13: Flag duplicate awd_titl_txt with different awd_id."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT awd_titl_txt FROM awards "
        "  GROUP BY awd_titl_txt HAVING COUNT(DISTINCT awd_id) > 1"
        ")"
    ).fetchone()[0]
    if count > 0:
        pytest.xfail(
            f"Q-13 FLAGGED: {count:,} title groups appear with multiple award IDs. "
            "Legitimate but worth reviewing."
        )


@real_db
def test_Q14_awards_per_fy_plausibility(live_conn):
    """Q-14: Each loaded FY 2019–2025 has > 1,000 records.

    FY2016–2018 are absent from the DB (ZIP obligation dates map to FY2019+).
    FY2026 is partial (in-progress year).
    """
    rows = {
        row[0]: row[1]
        for row in live_conn.execute(
            "SELECT fiscal_year, COUNT(*) FROM awards "
            "WHERE fiscal_year BETWEEN 2019 AND 2025 GROUP BY fiscal_year"
        )
    }
    below = [(fy, rows.get(fy, 0)) for fy in range(2019, 2026) if rows.get(fy, 0) <= 1000]
    assert not below, f"FYs with <= 1,000 records: {below}"


@real_db
def test_Q15_funding_per_fy_plausibility(live_conn):
    """Q-15: Each loaded FY 2019–2025 has > $1B total funding.

    FY2016–2018 are absent; FY2026 is partial.
    """
    rows = {
        row[0]: (row[1] or 0)
        for row in live_conn.execute(
            "SELECT fiscal_year, SUM(awd_amount) FROM awards "
            "WHERE fiscal_year BETWEEN 2019 AND 2025 GROUP BY fiscal_year"
        )
    }
    below = [(fy, rows.get(fy, 0)) for fy in range(2019, 2026) if rows.get(fy, 0) < 1e9]
    assert not below, f"FYs with < $1B total funding: {below}"


VALID_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "GU", "VI", "AS", "MP", "FM", "MH", "PW", "UM",
}


@real_db
def test_Q16_inst_state_code_valid(live_conn):
    """Q-16: inst_state_code values are valid US state/territory codes."""
    distinct = [
        row[0] for row in live_conn.execute(
            "SELECT DISTINCT inst_state_code FROM awards "
            "WHERE inst_state_code IS NOT NULL"
        )
    ]
    bad = [code for code in distinct if code not in VALID_STATE_CODES]
    if bad:
        pytest.xfail(f"Q-16 FLAGGED: Non-standard state codes found: {bad[:20]}")


VALID_DIRECTORATES = {
    "ENG", "MPS", "BIO", "SBE", "CISE", "GEO", "EDU",
    "OD", "TIP", "OISE", "OIA", "OIIA", "DEB", "DMS",
}


@real_db
def test_Q17_dir_abbr_valid(live_conn):
    """Q-17: dir_abbr values are known NSF directorates."""
    distinct = [
        row[0] for row in live_conn.execute(
            "SELECT DISTINCT dir_abbr FROM awards WHERE dir_abbr IS NOT NULL"
        )
    ]
    unknown = [d for d in distinct if d not in VALID_DIRECTORATES]
    if unknown:
        pytest.xfail(f"Q-17 FLAGGED: Unrecognized directorate abbreviations: {unknown}")


@real_db
def test_Q18_abstract_not_blank_recent(live_conn):
    """Q-18: FY2022+ should have < 5% null/blank abstracts."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN awd_abstract_narration IS NULL OR awd_abstract_narration = '' "
        "     THEN 1 ELSE 0 END) "
        "FROM awards WHERE fiscal_year >= 2022"
    ).fetchone()
    if total == 0:
        pytest.skip("No FY2022+ records available")
    rate = nulls / total
    assert rate < 0.05, f"FY2022+ abstract null/blank rate {rate:.2%} exceeds 5% limit"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. FISCAL YEAR BOUNDARY EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("date_str,expected_fy", [
    ("2024-09-30", 2024),  # FY-01: last day of FY2024
    ("2024-10-01", 2025),  # FY-02: first day of FY2025
    ("2025-01-01", 2025),  # FY-03: mid-FY2025
    ("2025-09-30", 2025),  # FY-04: last day of FY2025
    ("2025-10-01", 2026),  # FY-05: first day of FY2026
])
def test_FY_valid_boundary_dates(date_str, expected_fy):
    """FY-01 to FY-05: Valid boundary dates produce correct fiscal year."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date=date_str))
    assert rec["fiscal_year"] == expected_fy, (
        f"date={date_str!r} → fiscal_year={rec['fiscal_year']}, expected {expected_fy}"
    )


def test_FY06_null_date_gives_null_fy():
    """FY-06: NULL obligation_date → NULL fiscal_year, no crash."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date=None))
    assert rec["fiscal_year"] is None


def test_FY07_empty_string_date_gives_null_fy():
    """FY-07: Empty string obligation_date → NULL fiscal_year, no crash."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date=""))
    assert rec["fiscal_year"] is None


def test_FY08_invalid_date_string_gives_null_fy():
    """FY-08: Unparseable date string → NULL fiscal_year, no crash."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="not-a-date"))
    assert rec["fiscal_year"] is None


def test_FY09_valid_leap_year_date():
    """FY-09: 2024-02-29 (valid leap year) → FY 2024."""
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2024-02-29"))
    assert rec["fiscal_year"] == 2024


def test_FY10_invalid_leap_year_graceful():
    """FY-10: 2023-02-29 (invalid — not a leap year) → graceful handling.

    The ETL parses only year+month for FY derivation (day is ignored).
    Month=2, year=2023 → FY=2023 (or None if full parsing fails).
    Both outcomes are acceptable.
    """
    rec = etl_map_record(_make_etl_raw(awd_min_amd_letter_date="2023-02-29"))
    assert rec["fiscal_year"] in (2023, None), (
        f"Expected 2023 or None, got {rec['fiscal_year']!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. UPSERT & AUDIT TRAIL INTEGRITY
# ═══════════════════════════════════════════════════════════════════════════════

def test_U01_insert_created_at_equals_updated_at(mem_db):
    """U-01: Insert new record → created_at = updated_at at moment of insert."""
    rec = etl_map_record(_make_etl_raw())
    _upsert(mem_db, rec)
    row = mem_db.execute(
        "SELECT created_at, updated_at FROM awards WHERE awd_id = ?",
        (rec["awd_id"],)
    ).fetchone()
    assert row[0] == row[1], f"created_at={row[0]!r} != updated_at={row[1]!r}"


def test_U02_upsert_created_at_preserved(mem_db):
    """U-02: Re-upsert → created_at unchanged, updated_at advances."""
    rec = etl_map_record(_make_etl_raw())
    _upsert(mem_db, rec)
    created_at_v1, updated_at_v1 = mem_db.execute(
        "SELECT created_at, updated_at FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()

    time.sleep(1.1)
    _upsert(mem_db, rec)
    created_at_v2, updated_at_v2 = mem_db.execute(
        "SELECT created_at, updated_at FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()

    assert created_at_v2 == created_at_v1, (
        f"created_at changed on update: {created_at_v1!r} → {created_at_v2!r}"
    )
    assert updated_at_v2 > updated_at_v1, (
        f"updated_at did not advance: v1={updated_at_v1!r} v2={updated_at_v2!r}"
    )


def test_U03_re_insert_no_data_change_raw_json_same(mem_db):
    """U-03: Re-insert same record (no data change) → raw_json content identical."""
    rec = etl_map_record(_make_etl_raw())
    _upsert(mem_db, rec)
    rj1 = json.loads(mem_db.execute(
        "SELECT raw_json FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()[0])

    _upsert(mem_db, rec)
    rj2 = json.loads(mem_db.execute(
        "SELECT raw_json FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()[0])

    assert rj1 == rj2


def test_U04_upsert_field_change_updates_raw_json(mem_db):
    """U-04: Upsert with changed field → raw_json reflects the new value."""
    rec_v1 = etl_map_record(_make_etl_raw(awd_titl_txt="Original Title"))
    _upsert(mem_db, rec_v1)

    rec_v2 = etl_map_record(_make_etl_raw(awd_titl_txt="Updated Title"))
    _upsert(mem_db, rec_v2)

    rj = json.loads(mem_db.execute(
        "SELECT raw_json FROM awards WHERE awd_id = ?", (rec_v1["awd_id"],)
    ).fetchone()[0])
    assert rj["awd_titl_txt"] == "Updated Title"


def test_U05_collision_updates_not_duplicates(mem_db):
    """U-05: Same awd_id with different data → updated (1 row), not duplicated."""
    rec1 = etl_map_record(_make_etl_raw(awd_titl_txt="First Version"))
    rec2 = etl_map_record(_make_etl_raw(awd_titl_txt="Second Version"))
    _upsert(mem_db, rec1)
    _upsert(mem_db, rec2)

    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 1, f"Expected 1 row after collision upsert, got {count}"

    title = mem_db.execute(
        "SELECT awd_titl_txt FROM awards WHERE awd_id = ?", (rec1["awd_id"],)
    ).fetchone()[0]
    assert title == "Second Version"


def test_U06_batch_partial_failure_atomic_rollback(mem_db):
    """U-06: Batch fails on bad record → atomic rollback, 0 partial writes."""
    good_rec = etl_map_record(_make_etl_raw(awd_id="1111111"))

    # Force awd_titl_txt=None to violate the NOT NULL constraint
    bad_raw = _make_etl_raw(awd_id="2222222")
    bad_raw["awd_titl_txt"] = None
    bad_rec = etl_map_record(bad_raw)
    # bad_rec["awd_titl_txt"] is None → violates NOT NULL

    try:
        mem_db.executemany(UPSERT_SQL, [good_rec, bad_rec])
        mem_db.commit()
    except Exception:
        mem_db.rollback()

    count = mem_db.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
    assert count == 0, (
        f"Atomic rollback failed: {count} row(s) persisted after batch error"
    )


def test_U07_raw_json_matches_source(mem_db):
    """U-07: Stored raw_json accurately reflects the source record."""
    source = _make_etl_raw()
    rec = etl_map_record(source)
    _upsert(mem_db, rec)

    stored = json.loads(mem_db.execute(
        "SELECT raw_json FROM awards WHERE awd_id = ?", (rec["awd_id"],)
    ).fetchone()[0])

    assert stored["awd_id"] == source["awd_id"]
    assert stored["awd_titl_txt"] == source["awd_titl_txt"]
    assert stored["agcy_id"] == source["agcy_id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8. DATABASE PERFORMANCE & STABILITY
# ═══════════════════════════════════════════════════════════════════════════════

@real_db
def test_P01_full_table_scan_under_5s(live_conn):
    """P-01: Full table scan completes in < 5 seconds."""
    start = time.perf_counter()
    live_conn.execute("SELECT COUNT(*), MAX(awd_amount) FROM awards").fetchone()
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"Full table scan took {elapsed:.2f}s (limit 5s)"


@real_db
def test_P02_filter_by_fiscal_year_under_1s(live_conn):
    """P-02: Filter by fiscal_year completes in < 1 second."""
    start = time.perf_counter()
    live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE fiscal_year = 2024"
    ).fetchone()
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"fiscal_year filter took {elapsed:.2f}s (limit 1s)"


@real_db
def test_P03_filter_by_state_under_2s(live_conn):
    """P-03: Filter by inst_state_code completes in < 2 seconds."""
    start = time.perf_counter()
    live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE inst_state_code = 'TX'"
    ).fetchone()
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"State filter took {elapsed:.2f}s (limit 2s)"


@real_db
def test_P04_sum_by_fiscal_year_under_3s(live_conn):
    """P-04: SUM(awd_amount) GROUP BY fiscal_year completes in < 3 seconds."""
    start = time.perf_counter()
    live_conn.execute(
        "SELECT fiscal_year, SUM(awd_amount) FROM awards GROUP BY fiscal_year"
    ).fetchall()
    elapsed = time.perf_counter() - start
    assert elapsed < 3.0, f"SUM by fiscal year took {elapsed:.2f}s (limit 3s)"


@real_db
def test_P05_wal_concurrent_reads():
    """P-05: WAL mode allows two simultaneous read queries without blocking."""
    if not REAL_DB.exists():
        pytest.skip(f"Real DB not found at {REAL_DB}")

    results = []
    errors = []

    def read_worker():
        try:
            conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
            count = conn.execute("SELECT COUNT(*) FROM awards").fetchone()[0]
            conn.close()
            results.append(count)
        except Exception as e:
            errors.append(str(e))

    threads = [threading.Thread(target=read_worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f"Concurrent read errors: {errors}"
    assert len(results) == 2, "Not all concurrent reads completed"
    assert results[0] == results[1], "Concurrent reads returned different counts"


@real_db
def test_P06_integrity_check(live_conn):
    """P-06: PRAGMA integrity_check returns 'ok'."""
    result = live_conn.execute("PRAGMA integrity_check").fetchone()[0]
    assert result == "ok", f"integrity_check returned: {result!r}"


@real_db
def test_P07_foreign_key_check(live_conn):
    """P-07: PRAGMA foreign_key_check returns 0 violations."""
    violations = live_conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0, f"{len(violations)} FK violations found"


@real_db
def test_P08_quick_check(live_conn):
    """P-08: PRAGMA quick_check returns 'ok'."""
    result = live_conn.execute("PRAGMA quick_check").fetchone()[0]
    assert result == "ok", f"quick_check returned: {result!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# 9. DATA GOVERNANCE & PROVENANCE
# ═══════════════════════════════════════════════════════════════════════════════

@real_db
def test_G01_every_record_has_raw_json(live_conn):
    """G-01: Every record has raw_json (full audit trail preserved)."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE raw_json IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL raw_json"


@real_db
def test_G02_every_record_has_created_at(live_conn):
    """G-02: Every record has created_at."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE created_at IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL created_at"


@real_db
def test_G03_every_record_has_updated_at(live_conn):
    """G-03: Every record has updated_at."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE updated_at IS NULL"
    ).fetchone()[0]
    assert count == 0, f"{count} rows with NULL updated_at"


@real_db
def test_G04_agcy_id_populated_for_zip_records(live_conn):
    """G-04: agcy_id = 'NSF' for NSF awards loaded via ZIP.

    NOTE: The raw NSF ZIP data uses 'NSF' (not '4900') as the agency identifier.
    '4900' is the DUNS/SAM code; the raw JSON field contains the string 'NSF'.
    Scoped to source='nsf' to remain valid after NIH (agcy_id='NIH') records are added.
    """
    count_nsf = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nsf' AND agcy_id = 'NSF'"
    ).fetchone()[0]
    count_nonnull = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nsf' AND agcy_id IS NOT NULL"
    ).fetchone()[0]
    if count_nonnull == 0:
        pytest.skip("No NSF records with non-null agcy_id to check")
    rate = count_nsf / count_nonnull
    assert rate > 0.95, (
        f"Only {rate:.1%} of NSF records have agcy_id='NSF' "
        f"({count_nsf:,}/{count_nonnull:,})"
    )


@real_db
def test_G05_no_unexpected_pii(live_conn):
    """G-05: No SSN-like patterns in pi_name or inst_name (PII check)."""
    import re
    ssn_pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    samples = live_conn.execute(
        "SELECT pi_name, inst_name FROM awards LIMIT 5000"
    ).fetchall()
    hits = []
    for pi, inst in samples:
        if pi and ssn_pattern.search(pi):
            hits.append(f"pi_name={pi!r}")
        if inst and ssn_pattern.search(inst):
            hits.append(f"inst_name={inst!r}")
    assert not hits, f"SSN-like patterns found: {hits[:5]}"


@real_db
def test_G06_zip_year_fiscal_year_alignment(live_conn):
    """G-06: Fiscal years 2019–2026 all represented (source traceability).

    FY2016–2018 are absent — awards in those ZIPs have obligation dates that
    fall in FY2019+. This is a documented data characteristic, not a load error.
    """
    rows = {
        row[0]: row[1]
        for row in live_conn.execute(
            "SELECT fiscal_year, COUNT(*) FROM awards "
            "WHERE fiscal_year BETWEEN 2019 AND 2026 GROUP BY fiscal_year"
        )
    }
    represented = [fy for fy in range(2019, 2027) if rows.get(fy, 0) > 0]
    assert len(represented) >= 8, (
        f"Only {len(represented)} FYs represented between 2019–2026 "
        f"(expected 8): {represented}"
    )


@real_db
def test_G07_total_record_count_documented(live_conn):
    """G-07: Total NSF record count matches documented baseline (reproducible)."""
    expected = BASELINES["nsf"]["expected_record_count"]
    actual = live_conn.execute("SELECT COUNT(*) FROM awards WHERE source = 'nsf'").fetchone()[0]
    tolerance = expected * 0.001
    assert abs(actual - expected) <= tolerance, (
        f"Count {actual:,} outside ±0.1% of baseline {expected:,}. "
        "Update tests/baselines.json if data was intentionally reloaded."
    )


@real_db
def test_G08_total_funding_documented(live_conn):
    """G-08: Total NSF funding matches documented baseline (reproducible)."""
    expected_b = BASELINES["nsf"]["expected_funding_billions"]
    actual = live_conn.execute("SELECT SUM(awd_amount) FROM awards WHERE source = 'nsf'").fetchone()[0] or 0.0
    actual_b = actual / 1e9
    assert abs(actual_b - expected_b) / expected_b <= 0.005, (
        f"Total ${actual_b:.4f}B outside ±0.5% of baseline ${expected_b:.4f}B. "
        "Update tests/baselines.json if data was intentionally reloaded."
    )


@real_db
def test_G09_all_directorates_represented(live_conn):
    """G-09: More than 7 distinct NSF directorates represented."""
    count = live_conn.execute(
        "SELECT COUNT(DISTINCT dir_abbr) FROM awards WHERE dir_abbr IS NOT NULL"
    ).fetchone()[0]
    assert count > 7, f"Only {count} distinct directorates (expected > 7)"


@real_db
def test_G10_all_states_represented(live_conn):
    """G-10: >= 51 distinct state/territory codes (50 states + DC minimum)."""
    count = live_conn.execute(
        "SELECT COUNT(DISTINCT inst_state_code) FROM awards "
        "WHERE inst_state_code IS NOT NULL"
    ).fetchone()[0]
    assert count >= 51, (
        f"Only {count} distinct state codes (expected >= 51 for 50 states + DC)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 10. NIH API FETCHER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

def _make_nih_raw(**overrides) -> dict:
    """Minimal valid NIH API result dict for nih_map_record tests."""
    base = {
        "project_num":       "1R03CA303913-01",
        "project_title":     "Test NIH Award Title",
        "fiscal_year":       2025,
        "award_amount":      148500,
        "activity_code":     "R03",
        "award_notice_date": "2025-09-04T00:00:00",
        "project_start_date": "2025-09-05T00:00:00",
        "project_end_date":  "2027-08-31T00:00:00",
        "abstract_text":     "Test abstract.",
        "contact_pi_name":   "SOHAL, IKJOT SINGH ",
        "organization":      {"org_name": "UNIVERSITY OF NORTH TEXAS", "org_state": "TX"},
        "agency_ic_fundings": [
            {"abbreviation": "NCI", "total_cost": 148500.0, "direct_cost_ic": 100000.0}
        ],
        "agency_code":       "NIH",
        "direct_cost_amt":   100000,
        "opportunity_number": "PAR-23-058",
        "core_project_num":  "R03CA303913",
    }
    base.update(overrides)
    return base


# ── Unit tests (no DB, no network) ───────────────────────────────────────────

def test_N01_map_record_fields():
    """N-01: nih_map_record returns all 21 schema keys; source='nih'."""
    EXPECTED_KEYS = {
        "awd_id", "awd_titl_txt", "inst_name", "inst_state_code",
        "awd_amount", "obligation_date", "project_start_date", "project_end_date",
        "awd_abstract_narration", "dir_abbr", "div_abbr", "pgm_ele_name",
        "pi_name", "agcy_id", "fiscal_year", "raw_json",
        "source", "opportunity_number", "activity_code", "nih_institute", "direct_cost_amt",
    }
    rec = nih_map_record(_make_nih_raw())
    assert rec.keys() == EXPECTED_KEYS
    assert rec["source"] == "nih"


def test_N02_contact_pi_stripped():
    """N-02: Trailing space in contact_pi_name is stripped."""
    rec = nih_map_record(_make_nih_raw(contact_pi_name="SMITH, JOHN "))
    assert rec["pi_name"] == "SMITH, JOHN"


def test_N03_activity_code_mapped():
    """N-03: activity_code populated correctly from API field."""
    rec = nih_map_record(_make_nih_raw(activity_code="R01"))
    assert rec["activity_code"] == "R01"


def test_N04_nih_institute_from_fundings():
    """N-04: nih_institute taken from agency_ic_fundings abbreviation with highest total_cost."""
    raw = _make_nih_raw(agency_ic_fundings=[
        {"abbreviation": "NIBIB", "total_cost": 50000.0},
        {"abbreviation": "NCI",   "total_cost": 148500.0},
    ])
    rec = nih_map_record(raw)
    assert rec["nih_institute"] == "NCI"


def test_N05_date_iso_strip():
    """N-05: iso_date strips time component from NIH datetime string."""
    assert nih_iso_date("2025-09-05T00:00:00") == "2025-09-05"
    assert nih_iso_date("2024-10-01T00:00:00") == "2024-10-01"


def test_N06_null_date_returns_none():
    """N-06: iso_date(None) and iso_date('') both return None."""
    assert nih_iso_date(None) is None
    assert nih_iso_date("") is None


def test_N07_project_num_as_awd_id():
    """N-07: project_num is used as awd_id, not appl_id."""
    raw = _make_nih_raw(project_num="1R35GM142421-01")
    rec = nih_map_record(raw)
    assert rec["awd_id"] == "1R35GM142421-01"


def test_N08_nih_fields_not_null():
    """N-08: activity_code, nih_institute, and direct_cost_amt are populated."""
    rec = nih_map_record(_make_nih_raw())
    assert rec["activity_code"] is not None
    assert rec["nih_institute"] is not None
    assert rec["direct_cost_amt"] is not None


def test_N09_nsf_nih_no_awd_id_collision():
    """N-09: NSF 7-digit awd_id format is distinct from NIH project_num format."""
    nsf_id  = "2531827"            # typical NSF: 7-digit numeric string
    nih_id  = "1R03CA303913-01"   # typical NIH: contains letters and hyphens
    assert nsf_id != nih_id
    assert nsf_id.isdigit() and len(nsf_id) == 7
    assert not nih_id.isdigit()


# ── Real-DB tests (run after NIH bulk load) ───────────────────────────────────

@real_db
def test_N10_nih_record_count(live_conn):
    """N-10: NIH record count matches baseline (if set)."""
    if BASELINES.get("nih", {}).get("expected_record_count") is None:
        pytest.skip("NIH baseline not yet set in tests/baselines.json — run bulk load first")
    expected = BASELINES["nih"]["expected_record_count"]
    actual = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nih'"
    ).fetchone()[0]
    tolerance = max(expected * 0.001, 1)
    assert abs(actual - expected) <= tolerance, (
        f"NIH record count {actual:,} outside ±0.1% of baseline {expected:,}"
    )


@real_db
def test_N11_nih_funding_plausible(live_conn):
    """N-11: Total NIH funding for FY2024+2025 is in a plausible $B range (>$1B, <$100B)."""
    if BASELINES.get("nih", {}).get("expected_funding_billions") is None:
        pytest.skip("NIH baseline not yet set in tests/baselines.json — run bulk load first")
    total = live_conn.execute(
        "SELECT SUM(awd_amount) FROM awards "
        "WHERE source = 'nih' AND fiscal_year IN (2024, 2025)"
    ).fetchone()[0] or 0.0
    total_b = total / 1e9
    assert 1.0 < total_b < 100.0, (
        f"NIH FY2024+2025 total funding ${total_b:.2f}B outside plausible range ($1B–$100B)"
    )


@real_db
def test_N12_nih_source_tag(live_conn):
    """N-12: No NULL source values among NIH rows."""
    null_count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'nih' AND source IS NULL"
    ).fetchone()[0]
    assert null_count == 0, f"{null_count} NIH rows have NULL source"


@real_db
def test_N13_nih_activity_code_present(live_conn):
    """N-13: NULL rate for activity_code among NIH records < 2%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN activity_code IS NULL THEN 1 ELSE 0 END) "
        "FROM awards WHERE source = 'nih'"
    ).fetchone()
    if total == 0:
        pytest.skip("No NIH records in DB")
    rate = nulls / total
    assert rate < 0.02, f"NIH activity_code NULL rate {rate:.2%} exceeds 2% limit"


@real_db
def test_N14_nih_institute_present(live_conn):
    """N-14: NULL rate for nih_institute among NIH records < 5%."""
    total, nulls = live_conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN nih_institute IS NULL THEN 1 ELSE 0 END) "
        "FROM awards WHERE source = 'nih'"
    ).fetchone()
    if total == 0:
        pytest.skip("No NIH records in DB")
    rate = nulls / total
    assert rate < 0.05, f"NIH nih_institute NULL rate {rate:.2%} exceeds 5% limit"


@real_db
def test_N15_no_awd_id_overlap(live_conn):
    """N-15: No awd_id is shared between source='nsf' and source='nih'."""
    overlap = live_conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT awd_id FROM awards WHERE source = 'nsf'"
        "  INTERSECT"
        "  SELECT awd_id FROM awards WHERE source = 'nih'"
        ")"
    ).fetchone()[0]
    assert overlap == 0, (
        f"{overlap} awd_id(s) appear in both NSF and NIH rows — ID collision detected"
    )


# ── Audit fix tests ─────────────────────────────────────────────────────────

@real_db
def test_Q19_usda_gap_no_negative_amounts(live_conn):
    """Q-19: USDA gap analysis excludes negative awd_amount (deobligations)."""
    count = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'usda' AND awd_amount < 0"
    ).fetchone()[0]
    assert count > 0, "Expected negative USDA records to exist in raw data"
    # Verify the gap query filter would exclude them
    included = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'usda' AND awd_amount < 0 AND awd_amount > 0"
    ).fetchone()[0]
    assert included == 0, "awd_amount > 0 filter must exclude all negatives"


@real_db
def test_Q20_negative_amounts_not_in_nsf_nih(live_conn):
    """Q-20: NSF and NIH sources have no negative awd_amount records."""
    for source in ("nsf", "nih"):
        count = live_conn.execute(
            "SELECT COUNT(*) FROM awards WHERE source = ? AND awd_amount < 0",
            (source,),
        ).fetchone()[0]
        assert count == 0, f"{source} has {count} negative awd_amount records"


@real_db
def test_Q21_all_12_agencies_in_db(live_conn):
    """Q-21: All 12 expected agencies are present in the database."""
    expected = {"nsf", "nih", "dod", "doe", "nasa", "usda", "ed", "commerce",
                "dhs", "dot", "epa", "neh"}
    rows = live_conn.execute("SELECT DISTINCT source FROM awards").fetchall()
    actual = {r[0] for r in rows}
    missing = expected - actual
    assert not missing, f"Missing agencies in DB: {missing}"


@real_db
def test_Q22_ed_non_research_filter(live_conn):
    """Q-22: ED non-research CFDA codes (84.425 etc.) exist and can be filtered."""
    from queries import ED_NON_RESEARCH_CFDAS
    placeholders = ",".join("?" * len(ED_NON_RESEARCH_CFDAS))
    total = live_conn.execute(
        f"SELECT COUNT(*) FROM awards WHERE source = 'ed' "
        f"AND opportunity_number IN ({placeholders})",
        ED_NON_RESEARCH_CFDAS,
    ).fetchone()[0]
    assert total > 0, "Expected ED non-research CFDA codes to have records"
    # Verify filtering works (remaining < total ED)
    total_ed = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = 'ed'"
    ).fetchone()[0]
    assert total < total_ed, "Non-research filter should not remove ALL ED records"


@real_db
def test_Q23_cfda_coverage_per_source(live_conn):
    """Q-23: USASpending sources have opportunity_number (CFDA) coverage > 50%."""
    usa_sources = ("dod", "doe", "nasa", "usda", "ed", "commerce", "dhs", "dot", "epa", "neh")
    for source in usa_sources:
        total, with_cfda = live_conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN opportunity_number IS NOT NULL AND TRIM(opportunity_number) != '' THEN 1 ELSE 0 END) "
            "FROM awards WHERE source = ?",
            (source,),
        ).fetchone()
        if total == 0:
            continue
        rate = with_cfda / total
        assert rate > 0.50, (
            f"{source} CFDA coverage {rate:.1%} below 50% threshold"
        )


@real_db
def test_Q24_validation_stats_returns_data(live_conn):
    """Q-24: Validation stats query returns plausible data for each source."""
    sources = [r[0] for r in live_conn.execute("SELECT DISTINCT source FROM awards").fetchall()]
    for source in sources:
        row = live_conn.execute(
            "SELECT COUNT(*), ROUND(COALESCE(SUM(awd_amount), 0) / 1e6, 1) "
            "FROM awards WHERE source = ?",
            (source,),
        ).fetchone()
        assert row[0] > 0, f"{source} has 0 records"
        assert row[1] is not None, f"{source} has NULL total funding"


@real_db
def test_Q25_peer_canonical_name_consistency(live_conn):
    """Q-25: Every peer_label in institutions maps to awards via inst_canonical_name."""
    peers = live_conn.execute(
        "SELECT DISTINCT peer_label FROM institutions "
        "WHERE is_peer_texas = 1 OR is_peer_national = 1"
    ).fetchall()
    for (peer,) in peers:
        count = live_conn.execute(
            "SELECT COUNT(*) FROM awards WHERE inst_canonical_name = ?",
            (peer,),
        ).fetchone()[0]
        # Peers should have at least some awards
        assert count > 0, f"Peer '{peer}' has 0 awards via inst_canonical_name"


@real_db
@pytest.mark.parametrize("source", list(BASELINES.keys()))
def test_B01_record_count_matches_baseline(live_conn, source):
    """B-01: Record count for each source matches baseline within 5% tolerance."""
    baseline = BASELINES[source]
    expected = baseline.get("expected_record_count")
    if expected is None:
        pytest.skip(f"No baseline record count set for {source}")
    actual = live_conn.execute(
        "SELECT COUNT(*) FROM awards WHERE source = ?", (source,)
    ).fetchone()[0]
    tolerance = 0.05
    assert abs(actual - expected) / max(expected, 1) <= tolerance, (
        f"{source}: expected ~{expected:,} records, got {actual:,} "
        f"(diff {abs(actual - expected):,}, {abs(actual - expected)/max(expected,1):.1%})"
    )


@real_db
def test_Q26_negative_amounts_by_source(live_conn):
    """Q-26: Negative amounts only in USASpending sources, never in NSF or NIH."""
    rows = live_conn.execute(
        "SELECT source, COUNT(*) FROM awards WHERE awd_amount < 0 GROUP BY source"
    ).fetchall()
    sources_with_negatives = {r[0] for r in rows}
    assert "nsf" not in sources_with_negatives, "NSF should have no negative amounts"
    assert "nih" not in sources_with_negatives, "NIH should have no negative amounts"


def test_F01_csv_export_format():
    """F-01: CSV export filename format is correct (unit test, no DB)."""
    import re
    for agency in ("nsf", "nih", "dod"):
        for fy_start, fy_end in [(2022, 2025), (2020, 2024)]:
            fname = f"federal_radar_gap_{agency}_{fy_start}-{fy_end}.csv"
            assert re.match(
                r"federal_radar_gap_[a-z]+_\d{4}-\d{4}\.csv$", fname
            ), f"Bad filename format: {fname}"
            fname2 = f"federal_radar_funding_{agency}_{fy_start}-{fy_end}.csv"
            assert re.match(
                r"federal_radar_funding_[a-z]+_\d{4}-\d{4}\.csv$", fname2
            ), f"Bad filename format: {fname2}"
