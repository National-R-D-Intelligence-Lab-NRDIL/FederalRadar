# Federal Radar

A data pipeline and governance system for federal research award data.
Currently covers **83,845 NSF awards totaling ~$49.95B** (FY2019–FY2026),
with a validated, auditable SQLite database ready for VPR stakeholder use
and structured for expansion to NIH, DOD, and NASA.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Database Schema](#database-schema)
4. [Data Sources](#data-sources)
5. [Setup](#setup)
6. [Running the ETL (ZIP Bulk Load)](#running-the-etl-zip-bulk-load)
7. [Running the API Sync (Incremental)](#running-the-api-sync-incremental)
8. [Validating the Data](#validating-the-data)
9. [Running the Test Suite](#running-the-test-suite)
10. [Smoke Tests (Pre-Demo Checklist)](#smoke-tests-pre-demo-checklist)
11. [Known Data Characteristics](#known-data-characteristics)
12. [Multi-Agency Roadmap](#multi-agency-roadmap)
13. [Project Structure](#project-structure)

---

## Overview

Federal Radar ingests NSF federal award data from two sources:

- **Bulk ZIP archives** — annual JSON archives from NSF covering all awards
  per year, loaded once to establish the historical baseline.
- **Live NSF API** — incremental sync for recent/amended awards, run on a
  schedule to keep the database current.

Both sources are mapped to a unified schema, upserted idempotently, and
validated against a 102-test governance suite that enforces federal data
stewardship standards: accuracy, completeness, consistency, and auditability.

---

## Architecture

```
NSF ZIP Archives              NSF Public API
(data/raw/nsf/*.zip)          (api.nsf.gov)
        │                           │
        ▼                           ▼
  nsf_etl.py                nsf_api_fetcher.py
  map_record()               map_record()
  fiscal year derivation     date conversion
  PI extraction              pagination
        │                           │
        └──────────┬────────────────┘
                   ▼
             src/db.py
         upsert_nsf_awards_batch()
         INSERT ... ON CONFLICT DO UPDATE
         (created_at preserved; updated_at advanced)
                   │
                   ▼
        data/federal_awards.db
        SQLite, WAL mode, 1.65 GB
                   │
          ┌────────┴────────┐
          ▼                 ▼
    nsf_verify.py     tests/
    (ZIP vs API       test_data_governance.py
     comparison)      (102 governance tests)
```

### Fiscal Year Rule

NSF and all federal agencies follow the US government fiscal year:
**October 1 through September 30.**

An award with `obligation_date` in October, November, or December of year N
belongs to **fiscal year N+1**. An award dated January–September of year N
belongs to **fiscal year N**.

```python
# Implemented in both nsf_etl.py and nsf_api_fetcher.py
fiscal_year = year + 1 if month >= 10 else year
```

### Upsert Strategy

Records are inserted or updated using `ON CONFLICT DO UPDATE`, which:
- Sets `created_at` once at insert time — never changed again
- Advances `updated_at` on every update
- Replaces all other fields with the latest source data
- Is idempotent — running the same ETL twice produces the same result

---

## Database Schema

**Table:** `nsf_awards`

| Column | Type | Nullable | Description |
|---|---|---|---|
| `awd_id` | TEXT | NOT NULL | NSF award ID (primary key, typically 7-digit numeric) |
| `awd_titl_txt` | TEXT | NOT NULL | Award title |
| `inst_name` | TEXT | | Awardee institution name |
| `inst_state_code` | TEXT | | Institution US state/territory code |
| `awd_amount` | REAL | | Obligated funding amount in USD |
| `obligation_date` | TEXT | | Date of obligation (YYYY-MM-DD) |
| `project_start_date` | TEXT | | Project start date (YYYY-MM-DD) |
| `project_end_date` | TEXT | | Project expiration date (YYYY-MM-DD) |
| `awd_abstract_narration` | TEXT | | Award abstract |
| `dir_abbr` | TEXT | | NSF directorate abbreviation (e.g., ENG, MPS, BIO) |
| `div_abbr` | TEXT | | NSF division abbreviation |
| `pgm_ele_name` | TEXT | | Program element name |
| `pi_name` | TEXT | | Principal investigator full name |
| `agcy_id` | TEXT | | Agency identifier (`NSF` for all current records) |
| `fiscal_year` | INTEGER | | Derived US federal fiscal year |
| `raw_json` | TEXT | NOT NULL | Original source JSON (audit trail) |
| `created_at` | DATETIME | NOT NULL | Timestamp of first insert — never updated |
| `updated_at` | DATETIME | NOT NULL | Timestamp of most recent upsert |

**Pragmas:**
- `PRAGMA journal_mode = WAL` — enables concurrent reads during writes
- `PRAGMA synchronous = NORMAL` — balances durability and write speed
- `awd_id` is the primary key and conflict target for upserts

---

## Data Sources

### NSF Bulk ZIP Archives

**Location:** `data/raw/nsf/`
**Files:** `2016.zip` through `2026.zip`
**Format:** ZIP archives containing one JSON file per award
**Coverage:** All NSF awards with obligation dates in the archive year (note:
  obligation dates in the 2016–2018 archives map to FY2019+)
**URL:** `https://www.nsf.gov/awardsearch/download.jsp`

Each JSON file contains one award record with fields including institution,
PI list, program elements, funding amounts, and dates.

### NSF Public API

**Base URL:** `https://api.nsf.gov/services/v1/awards.json`
**Authentication:** None (public API)
**Rate limit:** No documented limit; be respectful (no parallel requests)
**Page size:** 25 records per request
**Use case:** Incremental sync for recent awards and amendments

---

## Setup

### Prerequisites

- Python 3.10 or later
- `pytest` for the test suite (`pip install pytest`)
- No other external dependencies — the pipeline uses only the Python standard library

### Directory structure

Ensure the raw data directory exists before running the ETL:

```bash
mkdir -p data/raw/nsf
```

Place the NSF ZIP files in `data/raw/nsf/`:

```
data/raw/nsf/
├── 2016.zip
├── 2017.zip
...
└── 2026.zip
```

### Initialize the database

```bash
python src/db.py
```

This creates `data/federal_awards.db` with the correct schema and WAL mode.
Safe to run multiple times — uses `CREATE TABLE IF NOT EXISTS`.

---

## Running the ETL (ZIP Bulk Load)

### Load all ZIPs

```bash
python scripts/nsf_etl.py
```

Processes all ZIP files in `data/raw/nsf/` in alphabetical order.
Prints progress every 1,000 records and a final summary table.
The first full load of all 11 ZIPs takes approximately 10–20 minutes.

### Load a single year

```bash
python scripts/nsf_etl.py --year 2025
```

Only processes ZIPs whose filename contains `2025`. Useful for reloading a
single year after an amended archive is released by NSF.

### Re-running is safe

The ETL is fully idempotent. Running it again on the same ZIP:
- Updates records where fields have changed
- Leaves records unchanged where nothing has changed
- Never creates duplicates
- Preserves `created_at` for existing records

---

## Running the API Sync (Incremental)

### Pull the last 1 day (default)

```bash
python scripts/nsf_api_fetcher.py
```

Fetches awards with `obligation_date` from yesterday to today and upserts them.

### Pull a longer window

```bash
python scripts/nsf_api_fetcher.py --days 30
```

### Compare API vs database (no upsert)

Fetch two specific awards and compare every field between the live API and the
current DB record:

```bash
python scripts/nsf_api_fetcher.py --test
```

### Spot-check recent awards

Check whether awards from the last N days are already in the database:

```bash
python scripts/nsf_api_fetcher.py --exists --days 7
```

### Cross-source comparison

Compare 5 sampled awards between the ZIP-loaded DB values and the live API:

```bash
python scripts/nsf_api_fetcher.py --compare
```

---

## Validating the Data

### ZIP vs API field-by-field comparison

```bash
python scripts/nsf_verify.py
```

Compares a set of sampled award IDs between the ZIP-loaded database values
and the live NSF API, printing a field-by-field match table.

---

## Running the Test Suite

The test suite enforces 9 data governance pillars and is the primary quality
gate before any stakeholder handoff or agency reload.

### Offline tests (no network, fast — ~20 seconds)

```bash
pytest tests/test_data_governance.py -v
```

### Full tests including live NSF API checks (~8 minutes)

```bash
FEDERAL_RADAR_NETWORK_TESTS=1 pytest tests/test_data_governance.py -v
```

### Run only a specific pillar

```bash
# Schema integrity only
pytest tests/test_data_governance.py -v -k "S0"

# Fiscal year edge cases only
pytest tests/test_data_governance.py -v -k "FY"

# Performance only
pytest tests/test_data_governance.py -v -k "P0"
```

### Expected results (clean database)

| Result | Offline | With Network |
|---|---|---|
| PASSED | 87 | 95 |
| XFAILED (documented flags) | 5 | 6 |
| SKIPPED | 10 | 0 |
| FAILED | 0 | 0 |

`XFAILED` tests are **not failures.** They are documented data characteristics
(see [Known Data Characteristics](#known-data-characteristics)).

### Updating baselines after a reload

If you intentionally reload the database (e.g., after NSF releases amended ZIPs),
update `tests/baselines.json` to match the new counts:

```bash
python -c "
import sqlite3, json
conn = sqlite3.connect('data/federal_awards.db')
count = conn.execute('SELECT COUNT(*) FROM nsf_awards').fetchone()[0]
total = conn.execute('SELECT SUM(awd_amount) FROM nsf_awards').fetchone()[0]
print(json.dumps({'expected_record_count': count, 'expected_funding_billions': round(total/1e9, 4)}, indent=2))
conn.close()
"
```

Paste the output into `tests/baselines.json`.

---

## Smoke Tests (Pre-Demo Checklist)

Run these before any VPR stakeholder demo or agency data handoff.
Should complete in under 2 minutes.

```bash
# 1. Database accessible and healthy
sqlite3 data/federal_awards.db "PRAGMA integrity_check;"
# Expected: ok

sqlite3 data/federal_awards.db "PRAGMA journal_mode;"
# Expected: wal

# 2. Row count and funding baseline
sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9, 2) FROM nsf_awards;"
# Expected: 83845|49.95 (approximately)

# 3. No duplicate award IDs
sqlite3 data/federal_awards.db "SELECT COUNT(*) FROM (SELECT awd_id FROM nsf_awards GROUP BY awd_id HAVING COUNT(*) > 1);"
# Expected: 0

# 4. No NULL titles
sqlite3 data/federal_awards.db "SELECT COUNT(*) FROM nsf_awards WHERE awd_titl_txt IS NULL;"
# Expected: 0

# 5. No NULL raw_json (audit trail intact)
sqlite3 data/federal_awards.db "SELECT COUNT(*) FROM nsf_awards WHERE raw_json IS NULL;"
# Expected: 0

# 6. Fiscal year distribution
sqlite3 data/federal_awards.db "SELECT fiscal_year, COUNT(*), ROUND(SUM(awd_amount)/1e6, 1) FROM nsf_awards GROUP BY fiscal_year ORDER BY fiscal_year;"

# 7. FY boundary correctness spot-check (Oct 1 awards → next FY)
sqlite3 data/federal_awards.db "SELECT awd_id, obligation_date, fiscal_year FROM nsf_awards WHERE obligation_date LIKE '%-10-01' LIMIT 5;"

# 8. API connectivity test
python scripts/nsf_api_fetcher.py --test
```

---

## Known Data Characteristics

These are documented properties of the data — not errors.

### FY2016–2018 Gap
ZIP files for 2016–2018 were loaded but produced **zero FY2016–2018 records**.
The awards in those archives have `obligation_date` values that fall in FY2019
and later. This reflects NSF's internal data — those archives contain awards
obligated in later years, not 2016–2018. The earliest records in the database
are FY2019.

### 10 Non-Standard Award IDs
Ten records have contract-style IDs (e.g., `49100421C0035`) rather than the
standard 7-digit numeric format. These are SBIR/contract awards and are valid
federal records.

### NULL Rate Summary

All fields are within federal data quality thresholds:

| Field | NULL Rate |
|---|---|
| `awd_amount` | 0.01% |
| `obligation_date` | 0.01% |
| `fiscal_year` | 0.01% |
| `inst_name` | 0.00% |
| `pi_name` | 0.00% |
| `dir_abbr` | 0.00% |
| `raw_json` | 0.00% |

### NSF Directorate Codes in This Dataset

| Code | Directorate |
|---|---|
| MPS | Mathematical and Physical Sciences |
| CSE | Computer and Information Science and Engineering |
| ENG | Engineering |
| GEO | Geosciences |
| EDU | STEM Education |
| BIO | Biological Sciences |
| TIP | Technology, Innovation and Partnerships |
| SBE | Social, Behavioral and Economic Sciences |
| O/D | Office of the Director |
| IRM / BFA / NSB / OCIO | Administrative/oversight offices |

### `agcy_id` Values
All ZIP-loaded records have `agcy_id = 'NSF'`. Records loaded via the API have
`agcy_id = NULL` (the API does not return an agency ID field). This is expected.

---

## Multi-Agency Roadmap

The schema and test suite are designed for multi-agency expansion. The full
roadmap is documented in `docs/project_status_and_roadmap.md`.

### Planned agencies in priority order

| Agency | Data Source | Complexity | Status |
|---|---|---|---|
| NIH | NIH ExPORTER + Reporter API | Low | Not started |
| NASA | USASpending bulk + API | Medium | Not started |
| DOD | USASpending bulk + API | High | Not started |

### Required schema changes before first new agency

```sql
-- 1. Add data source tracking
ALTER TABLE nsf_awards ADD COLUMN data_source TEXT;

-- 2. Rename for multi-agency use (optional but recommended)
ALTER TABLE nsf_awards RENAME TO federal_awards;
```

See `docs/project_status_and_roadmap.md` for field mapping tables, estimated
volumes, and step-by-step implementation notes for each agency.

---

## Project Structure

```
Federal Radar/
│
├── README.md                          # This file
│
├── data/
│   ├── federal_awards.db              # SQLite database (WAL mode, ~1.65 GB)
│   └── raw/
│       └── nsf/
│           ├── 2016.zip               # NSF bulk award archives
│           ├── 2017.zip
│           ├── ...
│           └── 2026.zip
│
├── scripts/
│   ├── nsf_etl.py                     # ZIP bulk loader — processes all annual ZIPs
│   ├── nsf_api_fetcher.py             # Incremental API sync and comparison tools
│   ├── nsf_verify.py                  # ZIP vs API field-by-field validation
│   └── nsf_api_test.py                # Ad-hoc API exploration
│
├── src/
│   └── db.py                          # Schema definition, upsert logic
│
├── tests/
│   ├── __init__.py
│   ├── test_data_governance.py        # 102-test governance suite (9 pillars)
│   └── baselines.json                 # Expected record count and funding totals
│
└── docs/
    └── project_status_and_roadmap.md  # Handoff document and multi-agency plan
```

---

## Quick Reference

| Task | Command |
|---|---|
| Initialize DB | `python src/db.py` |
| Load all ZIPs | `python scripts/nsf_etl.py` |
| Load one year | `python scripts/nsf_etl.py --year 2025` |
| API sync (1 day) | `python scripts/nsf_api_fetcher.py` |
| API sync (30 days) | `python scripts/nsf_api_fetcher.py --days 30` |
| Compare API vs DB | `python scripts/nsf_api_fetcher.py --test` |
| Check recent awards | `python scripts/nsf_api_fetcher.py --exists --days 7` |
| Run tests (offline) | `pytest tests/test_data_governance.py -v` |
| Run tests (full) | `FEDERAL_RADAR_NETWORK_TESTS=1 pytest tests/test_data_governance.py -v` |
| DB integrity check | `sqlite3 data/federal_awards.db "PRAGMA integrity_check;"` |
| Row count + funding | `sqlite3 data/federal_awards.db "SELECT COUNT(*), ROUND(SUM(awd_amount)/1e9,2) FROM nsf_awards;"` |
