"""
load_grantsgov.py
Load Grants.gov daily extract (JSONL) into federal_awards.db.

Usage:
    python scripts/load_grantsgov.py                          # loads today's JSONL
    python scripts/load_grantsgov.py --file path/to/file.jsonl
    python scripts/load_grantsgov.py --dry-run               # count only, no writes
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.db import (
    DB_PATH,
    _connect,
    init_db,
    log_refresh_end,
    log_refresh_start,
)

GRANTS_GOV_RAW_DIR = Path(__file__).parent.parent / "data" / "grants_gov" / "raw"
BATCH_SIZE = 500

UPSERT_OPP_SQL = """
INSERT INTO opportunities (
    opportunity_id, opportunity_number, opportunity_title,
    agency_code, agency_name, record_type, derived_status,
    opportunity_category, funding_instrument_type, category_of_funding_activity,
    eligible_applicants, post_date, close_date, archive_date, last_updated_date,
    fiscal_year, award_ceiling, award_floor, estimated_total_funding,
    expected_number_of_awards, cost_sharing_required, description,
    estimated_post_date, estimated_close_date, estimated_award_date,
    estimated_project_start, grantor_contact_email, grantor_contact_name,
    extracted_date, raw_json, created_at, updated_at
) VALUES (
    :opportunity_id, :opportunity_number, :opportunity_title,
    :agency_code, :agency_name, :record_type, :derived_status,
    :opportunity_category, :funding_instrument_type, :category_of_funding_activity,
    :eligible_applicants, :post_date, :close_date, :archive_date, :last_updated_date,
    :fiscal_year, :award_ceiling, :award_floor, :estimated_total_funding,
    :expected_number_of_awards, :cost_sharing_required, :description,
    :estimated_post_date, :estimated_close_date, :estimated_award_date,
    :estimated_project_start, :grantor_contact_email, :grantor_contact_name,
    :extracted_date, :raw_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
) ON CONFLICT(opportunity_id) DO UPDATE SET
    -- derived_status always wins: status transitions (posted → closed → archived)
    derived_status              = excluded.derived_status,
    -- all other fields: never overwrite good data with NULL
    opportunity_number          = COALESCE(excluded.opportunity_number,          opportunities.opportunity_number),
    opportunity_title           = COALESCE(excluded.opportunity_title,           opportunities.opportunity_title),
    agency_code                 = COALESCE(excluded.agency_code,                 opportunities.agency_code),
    agency_name                 = COALESCE(excluded.agency_name,                 opportunities.agency_name),
    record_type                 = COALESCE(excluded.record_type,                 opportunities.record_type),
    opportunity_category        = COALESCE(excluded.opportunity_category,        opportunities.opportunity_category),
    funding_instrument_type     = COALESCE(excluded.funding_instrument_type,     opportunities.funding_instrument_type),
    category_of_funding_activity = COALESCE(excluded.category_of_funding_activity, opportunities.category_of_funding_activity),
    eligible_applicants         = COALESCE(excluded.eligible_applicants,         opportunities.eligible_applicants),
    post_date                   = COALESCE(excluded.post_date,                   opportunities.post_date),
    close_date                  = COALESCE(excluded.close_date,                  opportunities.close_date),
    archive_date                = COALESCE(excluded.archive_date,                opportunities.archive_date),
    last_updated_date           = COALESCE(excluded.last_updated_date,           opportunities.last_updated_date),
    fiscal_year                 = COALESCE(excluded.fiscal_year,                 opportunities.fiscal_year),
    award_ceiling               = COALESCE(excluded.award_ceiling,               opportunities.award_ceiling),
    award_floor                 = COALESCE(excluded.award_floor,                 opportunities.award_floor),
    estimated_total_funding     = COALESCE(excluded.estimated_total_funding,     opportunities.estimated_total_funding),
    expected_number_of_awards   = COALESCE(excluded.expected_number_of_awards,   opportunities.expected_number_of_awards),
    cost_sharing_required       = COALESCE(excluded.cost_sharing_required,       opportunities.cost_sharing_required),
    description                 = COALESCE(excluded.description,                 opportunities.description),
    estimated_post_date         = COALESCE(excluded.estimated_post_date,         opportunities.estimated_post_date),
    estimated_close_date        = COALESCE(excluded.estimated_close_date,        opportunities.estimated_close_date),
    estimated_award_date        = COALESCE(excluded.estimated_award_date,        opportunities.estimated_award_date),
    estimated_project_start     = COALESCE(excluded.estimated_project_start,     opportunities.estimated_project_start),
    grantor_contact_email       = COALESCE(excluded.grantor_contact_email,       opportunities.grantor_contact_email),
    grantor_contact_name        = COALESCE(excluded.grantor_contact_name,        opportunities.grantor_contact_name),
    extracted_date              = excluded.extracted_date,
    raw_json                    = excluded.raw_json,
    updated_at                  = CURRENT_TIMESTAMP;
"""

INSERT_CFDA_SQL = """
INSERT OR IGNORE INTO opportunity_cfdas (opportunity_id, cfda_number)
VALUES (?, ?);
"""


def parse_date(s: str) -> str | None:
    """Convert mmddyyyy → ISO 'YYYY-MM-DD'. Returns None if blank or malformed."""
    if not s or len(s) != 8:
        return None
    try:
        mm, dd, yyyy = s[:2], s[2:4], s[4:]
        d = date(int(yyyy), int(mm), int(dd))
        return d.isoformat()
    except (ValueError, TypeError):
        return None


def derive_fiscal_year(iso: str) -> int | None:
    """Oct 1 boundary: Oct–Dec rolls to next calendar year."""
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
        return d.year + 1 if d.month >= 10 else d.year
    except (ValueError, TypeError):
        return None


def is_fy2019_plus(rec: dict) -> bool:
    """Filter gate: forecasts always pass; synopsis must have PostDate >= 2018-10-01."""
    if rec.get("record_type") == "forecast":
        return True
    iso = parse_date(rec.get("PostDate", ""))
    if not iso:
        return False
    return iso >= "2018-10-01"


def normalize_cfda_list(val) -> list[str]:
    """Accept str or list → clean list of CFDA strings."""
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if v]
    # string: may be comma-separated
    return [v.strip() for v in str(val).split(",") if v.strip()]


def serialize_multi(val) -> str | None:
    """List or string → comma-joined string for multi-value columns."""
    if val is None:
        return None
    if isinstance(val, list):
        joined = ",".join(str(v).strip() for v in val if v)
        return joined if joined else None
    return str(val).strip() or None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if f != 0.0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def map_record(rec: dict) -> dict:
    """JSONL dict → DB row dict for opportunities table."""
    post_iso = parse_date(rec.get("PostDate", ""))
    fiscal_year = derive_fiscal_year(post_iso)

    cost_sharing_raw = rec.get("CostSharingOrMatchingRequirement", "")
    if isinstance(cost_sharing_raw, str):
        cost_sharing = 1 if cost_sharing_raw.strip().lower() == "yes" else 0
    else:
        cost_sharing = int(bool(cost_sharing_raw))

    return {
        "opportunity_id":              str(rec["OpportunityID"]),
        "opportunity_number":          rec.get("OpportunityNumber"),
        "opportunity_title":           rec.get("OpportunityTitle", ""),
        "agency_code":                 rec.get("AgencyCode"),
        "agency_name":                 rec.get("AgencyName"),
        "record_type":                 rec.get("record_type", "synopsis"),
        "derived_status":              rec.get("derived_status", "posted"),
        "opportunity_category":        rec.get("OpportunityCategory"),
        "funding_instrument_type":     serialize_multi(rec.get("FundingInstrumentType")),
        "category_of_funding_activity": serialize_multi(rec.get("CategoryOfFundingActivity")),
        "eligible_applicants":         serialize_multi(rec.get("EligibleApplicants")),
        "post_date":                   post_iso,
        "close_date":                  parse_date(rec.get("CloseDate", "")),
        "archive_date":                parse_date(rec.get("ArchiveDate", "")),
        "last_updated_date":           parse_date(rec.get("LastUpdatedDate", "")),
        "fiscal_year":                 fiscal_year,
        "award_ceiling":               _safe_float(rec.get("AwardCeiling")),
        "award_floor":                 _safe_float(rec.get("AwardFloor")),
        "estimated_total_funding":     _safe_float(rec.get("EstimatedTotalProgramFunding")),
        "expected_number_of_awards":   _safe_int(rec.get("ExpectedNumberOfAwards")),
        "cost_sharing_required":       cost_sharing,
        "description":                 rec.get("Description"),
        "estimated_post_date":         parse_date(rec.get("EstimatedSynopsisPostDate", "")),
        "estimated_close_date":        parse_date(rec.get("EstimatedSynopsisCloseDate", "")),
        "estimated_award_date":        parse_date(rec.get("EstimatedAwardDate", "")),
        "estimated_project_start":     parse_date(rec.get("EstimatedProjectStartDate", "")),
        "grantor_contact_email":       rec.get("GrantorContactEmail"),
        "grantor_contact_name":        rec.get("GrantorContactName"),
        "extracted_date":              rec.get("extracted_date", date.today().isoformat()),
        "raw_json":                    json.dumps(rec),
    }


def load_from_jsonl(path: Path, dry_run: bool = False) -> tuple[int, int, int]:
    """
    Read JSONL, filter FY2019+, upsert in batches of BATCH_SIZE.
    Returns (read_count, skip_count, upserted_count).
    """
    if not path.exists():
        print(f"ERROR: file not found: {path}")
        sys.exit(1)

    init_db()

    read_count = 0
    skip_count = 0
    upserted_count = 0
    opp_batch: list[dict] = []
    cfda_batch: list[tuple] = []

    def flush(conn):
        nonlocal upserted_count
        if opp_batch:
            conn.executemany(UPSERT_OPP_SQL, opp_batch)
        if cfda_batch:
            conn.executemany(INSERT_CFDA_SQL, cfda_batch)
        conn.commit()
        upserted_count += len(opp_batch)
        opp_batch.clear()
        cfda_batch.clear()

    conn = _connect()
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                read_count += 1

                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    skip_count += 1
                    continue

                if not rec.get("OpportunityID"):
                    skip_count += 1
                    continue

                if not is_fy2019_plus(rec):
                    skip_count += 1
                    continue

                row = map_record(rec)
                opp_id = row["opportunity_id"]
                cfdas = normalize_cfda_list(rec.get("CFDANumbers"))

                opp_batch.append(row)
                for cfda in cfdas:
                    cfda_batch.append((opp_id, cfda))

                if read_count % 1000 == 0:
                    print(f"  Read {read_count:>6,}  queued {len(opp_batch):>4}  upserted {upserted_count:>6,}")

                if len(opp_batch) >= BATCH_SIZE:
                    if not dry_run:
                        flush(conn)
                    else:
                        upserted_count += len(opp_batch)
                        opp_batch.clear()
                        cfda_batch.clear()

        # flush remainder
        if not dry_run:
            flush(conn)
        else:
            upserted_count += len(opp_batch)

    finally:
        conn.close()

    return read_count, skip_count, upserted_count


def default_jsonl_path() -> Path:
    today = date.today().isoformat()
    return GRANTS_GOV_RAW_DIR / f"{today}_all.jsonl"


def main():
    parser = argparse.ArgumentParser(description="Load Grants.gov JSONL into federal_awards.db")
    parser.add_argument(
        "--file", metavar="FILE",
        help="Path to JSONL file (default: data/grants_gov/raw/YYYY-MM-DD_all.jsonl)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Count records only — no DB writes",
    )
    args = parser.parse_args()

    path = Path(args.file) if args.file else default_jsonl_path()
    print(f"Source: {path}")
    print(f"DB:     {DB_PATH}")
    if args.dry_run:
        print("Mode:   --dry-run (no writes)")
    print()

    log_id = None
    if not args.dry_run:
        log_id = log_refresh_start("grantsgov", str(path))

    try:
        read_count, skip_count, upserted_count = load_from_jsonl(path, dry_run=args.dry_run)

        print()
        print(f"Read:     {read_count:>8,}")
        print(f"Skipped:  {skip_count:>8,}  (pre-FY2019 or invalid)")
        print(f"Upserted: {upserted_count:>8,}")

        if log_id is not None:
            log_refresh_end(log_id, "success", read_count, upserted_count)

    except Exception as e:
        if log_id is not None:
            log_refresh_end(log_id, "failed", error_message=str(e))
        raise


if __name__ == "__main__":
    main()
